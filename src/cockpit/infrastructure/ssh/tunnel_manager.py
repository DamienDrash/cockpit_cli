"""SSH local port forwarding for datasource connections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import socket
import subprocess
from typing import Protocol

from cockpit.shared.utils import utc_now


class TunnelProcess(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def kill(self) -> None: ...


@dataclass(slots=True)
class ActiveTunnel:
    profile_id: str
    target_ref: str
    remote_host: str
    remote_port: int
    local_port: int
    process: TunnelProcess
    opened_at: datetime
    last_checked_at: datetime
    reconnect_count: int = 0
    last_failure: str | None = None


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
                current.last_checked_at = utc_now()
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
        returncode = process.poll()
        if returncode is not None:
            raise RuntimeError(
                f"SSH tunnel for {profile_id} exited immediately with code {returncode}."
            )
        current_time = utc_now()
        reconnect_count = (current.reconnect_count + 1) if current is not None else 0
        tunnel = ActiveTunnel(
            profile_id=profile_id,
            target_ref=target_ref,
            remote_host=remote_host,
            remote_port=int(remote_port),
            local_port=local_port,
            process=process,
            opened_at=current_time,
            last_checked_at=current_time,
            reconnect_count=reconnect_count,
        )
        self._tunnels[profile_id] = tunnel
        return tunnel

    def reconnect_tunnel(self, profile_id: str) -> ActiveTunnel:
        tunnel = self._tunnels.get(profile_id)
        if tunnel is None:
            raise LookupError(f"Tunnel '{profile_id}' was not found.")
        reconnect_count = tunnel.reconnect_count + 1
        self.close_tunnel(profile_id)
        reopened = self.open_tunnel(
            profile_id=profile_id,
            target_ref=tunnel.target_ref,
            remote_host=tunnel.remote_host,
            remote_port=tunnel.remote_port,
        )
        reopened.reconnect_count = reconnect_count
        return reopened

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
        return self.snapshot_tunnels()

    def snapshot_tunnels(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for profile_id, tunnel in self._tunnels.items():
            tunnel.last_checked_at = utc_now()
            returncode = tunnel.process.poll()
            alive = returncode is None
            if not alive and tunnel.last_failure is None:
                tunnel.last_failure = f"process exited with code {returncode}"
            items.append(
                {
                    "profile_id": profile_id,
                    "target_ref": tunnel.target_ref,
                    "remote_host": tunnel.remote_host,
                    "remote_port": tunnel.remote_port,
                    "local_port": tunnel.local_port,
                    "alive": alive,
                    "returncode": returncode,
                    "reconnect_count": tunnel.reconnect_count,
                    "opened_at": tunnel.opened_at.isoformat(),
                    "last_checked_at": tunnel.last_checked_at.isoformat(),
                    "last_failure": tunnel.last_failure,
                }
            )
        return items

    @staticmethod
    def _allocate_local_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
