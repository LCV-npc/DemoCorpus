"""Validation helpers for outbound scraper requests.

The scraper is an SSRF boundary: every requested URL must be public HTTP(S),
including redirect targets.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeURL(ValueError):
    """Raised when a URL is not safe for the scraper to request."""


def validate_public_http_url(url: str) -> str:
    """Return a normalized URL only if its host resolves to public IPs."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURL("Only absolute http(s) URLs are allowed")
    if parsed.username or parsed.password:
        raise UnsafeURL("Credential-bearing URLs are not allowed")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".local"):
        raise UnsafeURL("Local network targets are not allowed")

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise UnsafeURL("URL host could not be resolved") from exc

    if not addresses:
        raise UnsafeURL("URL host has no address")

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise UnsafeURL("Private, loopback, and link-local targets are not allowed")

    return parsed.geturl()
