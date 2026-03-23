"""SSH local port forwarding for datasource connections."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import socket
import subprocess
from typing import Protocol


class TunnelProcess(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def kill(self) -> None: ...


@dataclass(slots=True, frozen=True)
class ActiveTunnel:
    profile_id: str
    target_ref: str
    remote_host: str
    remote_port: int
    local_port: int
    process: TunnelProcess


class SSHTunnelManager:
    """Manage long-lived SSH port forwards keyed by datasource profile."""

    def __init__(self, launcher: object | None = None) -> None:
        self._launcher = launcher or subprocess.Popen
        self._tunnels: dict[str, ActiveTunnel] = {}

    def open_tunnel(
        self,
        *,
        profile_id: str,
        target_ref: str,
        remote_host: str,
        remote_port: int,
    ) -> ActiveTunnel:
        current = self._tunnels.get(profile_id)
        if current is not None and current.process.poll() is None:
            if current.remote_host == remote_host and current.remote_port == remote_port:
                return current
            self.close_tunnel(profile_id)

        local_port = self._allocate_local_port()
        process = self._launcher(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ExitOnForwardFailure=yes",
                "-N",
                "-L",
                f"{local_port}:{remote_host}:{remote_port}",
                target_ref,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        tunnel = ActiveTunnel(
            profile_id=profile_id,
            target_ref=target_ref,
            remote_host=remote_host,
            remote_port=int(remote_port),
            local_port=local_port,
            process=process,
        )
        self._tunnels[profile_id] = tunnel
        return tunnel

    def close_tunnel(self, profile_id: str) -> None:
        tunnel = self._tunnels.pop(profile_id, None)
        if tunnel is None:
            return
        process = tunnel.process
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except Exception:
                process.kill()
                process.wait(timeout=1.0)

    def shutdown(self) -> None:
        for profile_id in list(self._tunnels):
            self.close_tunnel(profile_id)

    def list_tunnels(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        stale: list[str] = []
        for profile_id, tunnel in self._tunnels.items():
            returncode = tunnel.process.poll()
            alive = returncode is None
            items.append(
                {
                    "profile_id": profile_id,
                    "target_ref": tunnel.target_ref,
                    "remote_host": tunnel.remote_host,
                    "remote_port": tunnel.remote_port,
                    "local_port": tunnel.local_port,
                    "alive": alive,
                    "returncode": returncode,
                }
            )
            if not alive:
                stale.append(profile_id)
        for profile_id in stale:
            self._tunnels.pop(profile_id, None)
        return items

    @staticmethod
    def _allocate_local_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
