"""Helpers for rewriting datasource connection URLs."""

from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit


def connection_host_and_port(connection_url: str) -> tuple[str | None, int | None]:
    parsed = urlsplit(connection_url)
    if parsed.scheme.startswith("sqlite"):
        return None, None
    return parsed.hostname, parsed.port


def rewrite_connection_url(
    connection_url: str,
    *,
    host: str,
    port: int,
) -> str:
    parsed = urlsplit(connection_url)
    username = parsed.username
    password = parsed.password
    host_text = host
    if ":" in host_text and not host_text.startswith("["):
        host_text = f"[{host_text}]"
    credentials = ""
    if username is not None:
        credentials = quote(username, safe="")
        if password is not None:
            credentials += f":{quote(password, safe='')}"
        credentials += "@"
    netloc = f"{credentials}{host_text}:{int(port)}"
    return urlunsplit(
        (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
    )
