"""Core-side client for isolated managed plugin hosts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
from threading import RLock
from typing import TextIO

from cockpit.plugins.runtime.contracts import PluginHostStartup
from cockpit.shared.utils import make_id


class PluginHostError(RuntimeError):
    """Raised when the isolated plugin host cannot satisfy a request."""


class PluginHostClient:
    """Own a single managed plugin host subprocess."""

    def __init__(
        self,
        *,
        plugin_id: str,
        module_name: str,
        install_path: Path,
        project_root: Path,
        allowed_permissions: tuple[str, ...],
        app_version: str,
        startup_timeout: float = 5.0,
        request_timeout: float = 5.0,
    ) -> None:
        self._plugin_id = plugin_id
        self._module_name = module_name
        self._install_path = install_path
        self._project_root = project_root
        self._core_source_root = Path(__file__).resolve().parents[3]
        self._allowed_permissions = allowed_permissions
        self._app_version = app_version
        self._startup_timeout = startup_timeout
        self._request_timeout = request_timeout
        self._process: subprocess.Popen[str] | None = None
        self._socket: socket.socket | None = None
        self._reader: TextIO | None = None
        self._writer: TextIO | None = None
        self._lock = RLock()
        self._startup: PluginHostStartup | None = None
        self._last_error: str | None = None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def startup(self) -> PluginHostStartup | None:
        return self._startup

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> PluginHostStartup:
        with self._lock:
            if self.is_running() and self._startup is not None:
                return self._startup
            self._cleanup_process()
            parent_sock, child_sock = socket.socketpair()
            env = dict(os.environ)
            existing_pythonpath = env.get("PYTHONPATH", "")
            pythonpath_parts = [str(self._core_source_root)]
            if existing_pythonpath:
                pythonpath_parts.append(existing_pythonpath)
            env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
            env["COCKPIT_PLUGIN_HOST_FD"] = str(child_sock.fileno())
            argv = [
                sys.executable,
                "-u",
                "-m",
                "cockpit.plugins.runtime.host_main",
                "--plugin-id",
                self._plugin_id,
                "--module",
                self._module_name,
                "--install-path",
                str(self._install_path),
                "--project-root",
                str(self._project_root),
                "--allowed-permissions",
                json.dumps(list(self._allowed_permissions)),
                "--app-version",
                self._app_version,
            ]
            process = subprocess.Popen(
                argv,
                cwd=str(self._project_root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                pass_fds=(child_sock.fileno(),),
            )
            child_sock.close()
            self._process = process
            self._socket = parent_sock
            self._reader = parent_sock.makefile("r", encoding="utf-8")
            self._writer = parent_sock.makefile("w", encoding="utf-8", buffering=1)
            try:
                startup_message = self._read_message(timeout=self._startup_timeout)
                if startup_message.get("ok") is not True:
                    self._last_error = str(
                        startup_message.get("error", "Plugin host startup failed.")
                    )
                    raise PluginHostError(self._last_error)
                startup = PluginHostStartup.from_payload(startup_message.get("payload", {}))
                startup.pid = process.pid
                self._startup = startup
                self._last_error = None
                return startup
            except Exception as exc:
                error_text = self._read_stderr()
                self._last_error = error_text or str(exc)
                self._cleanup_process()
                raise PluginHostError(self._last_error) from exc

    def stop(self) -> None:
        with self._lock:
            process = self._process
            if process is None:
                return
            if process.poll() is None:
                try:
                    self._send_message(
                        {
                            "request_id": make_id("plgreq"),
                            "method": "shutdown",
                            "params": {},
                        }
                    )
                    self._read_message(timeout=1.5, allow_process_exit=True)
                except Exception:
                    pass
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            self._cleanup_process()

    def call(self, method: str, params: dict[str, object]) -> dict[str, object]:
        with self._lock:
            if not self.is_running():
                self.start()
            request_id = make_id("plgreq")
            self._send_message(
                {
                    "request_id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            response = self._read_message(timeout=self._request_timeout)
            if response.get("request_id") != request_id:
                raise PluginHostError(
                    f"Plugin host response mismatch for '{self._plugin_id}'."
                )
            if response.get("ok") is not True:
                error_message = str(response.get("error", "Plugin host request failed."))
                self._last_error = error_message
                raise PluginHostError(error_message)
            payload = response.get("result", {})
            if not isinstance(payload, dict):
                return {}
            self._last_error = None
            return payload

    def diagnostics(self) -> dict[str, object]:
        return {
            "running": self.is_running(),
            "pid": self._process.pid if self.is_running() and self._process is not None else None,
            "last_error": self._last_error,
            "module": self._module_name,
        }

    def _send_message(self, payload: dict[str, object]) -> None:
        if self._writer is None:
            raise PluginHostError("Plugin host writer is not available.")
        try:
            self._writer.write(json.dumps(payload, sort_keys=True) + "\n")
            self._writer.flush()
        except OSError as exc:
            self._last_error = str(exc)
            self._cleanup_process()
            raise PluginHostError(str(exc)) from exc

    def _read_message(
        self,
        *,
        timeout: float,
        allow_process_exit: bool = False,
    ) -> dict[str, object]:
        if self._socket is None or self._reader is None:
            raise PluginHostError("Plugin host channel is not available.")
        readable, _, _ = select.select([self._socket], [], [], timeout)
        if not readable:
            self._last_error = f"Timed out waiting for plugin host '{self._plugin_id}'."
            raise PluginHostError(self._last_error)
        line = self._reader.readline()
        if not line:
            if allow_process_exit:
                return {}
            process = self._process
            error_text = self._read_stderr()
            if process is not None and process.poll() is None:
                process.terminate()
            self._cleanup_process()
            self._last_error = error_text or f"Plugin host '{self._plugin_id}' exited unexpectedly."
            raise PluginHostError(self._last_error)
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            self._last_error = (
                f"Plugin host '{self._plugin_id}' produced invalid protocol output."
            )
            raise PluginHostError(self._last_error) from exc
        if not isinstance(payload, dict):
            self._last_error = "Plugin host protocol message must be a JSON object."
            raise PluginHostError(self._last_error)
        return payload

    def _read_stderr(self) -> str:
        process = self._process
        if process is None or process.stderr is None:
            return ""
        try:
            return process.stderr.read().strip()
        except OSError:
            return ""

    def _cleanup_process(self) -> None:
        if self._reader is not None:
            self._reader.close()
        if self._writer is not None:
            self._writer.close()
        if self._socket is not None:
            self._socket.close()
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=1)
            except Exception:
                process.kill()
                process.wait(timeout=1)
        if process is not None and process.stderr is not None:
            process.stderr.close()
        self._reader = None
        self._writer = None
        self._socket = None
        self._process = None
