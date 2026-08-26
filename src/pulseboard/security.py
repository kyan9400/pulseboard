"""Write protection and outbound request validation."""

import asyncio
import ipaddress
import secrets
import socket
from urllib.parse import urlsplit

from fastapi import Header, HTTPException, Request, status


async def validate_target_url(url: str, *, allow_private_targets: bool) -> None:
    """Reject credentials and non-public destinations before every network check."""

    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only absolute HTTP and HTTPS URLs can be monitored")
    if parsed.username or parsed.password:
        raise ValueError("credentials are not allowed in monitor URLs")
    if allow_private_targets:
        return

    try:
        direct_ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        direct_ip = None

    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address]
    if direct_ip is not None:
        addresses = {direct_ip}
    else:
        loop = asyncio.get_running_loop()
        try:
            records = await loop.getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as error:
            raise ValueError(f"target hostname could not be resolved: {parsed.hostname}") from error
        addresses = {ipaddress.ip_address(record[4][0]) for record in records}

    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("private, local, reserved, and link-local targets are blocked")


async def require_write_access(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    configured_key: str | None = request.app.state.settings.api_key
    if configured_key and (
        x_api_key is None or not secrets.compare_digest(x_api_key, configured_key)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid X-API-Key header is required.",
        )
