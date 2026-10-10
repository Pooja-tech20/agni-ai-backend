"""
Basic SSRF guard for URLs that the *server* will call on a user's behalf
(function webhooks, webhook settings, ...).

This only checks the URL text. The code that actually sends the request must
ALSO resolve the hostname and refuse private/loopback/link-local addresses at
send time (DNS can change after validation), and must not follow redirects
to such addresses.
"""
import ipaddress
import re
from urllib.parse import urlsplit

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".corp")
# A real hostname never ends in a numeric label, so "2130706433" or "0x7f.1"
# are IP addresses in disguise (they resolve to 127.0.0.1 on many systems).
_NUMERIC_LABEL = re.compile(r"^(0x[0-9a-f]+|\d+)$", re.IGNORECASE)


def check_public_http_url(url: str) -> str:
    """Return the URL if it looks safe to call, otherwise raise ValueError."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://")
    if parts.username or parts.password:
        raise ValueError("URL must not contain a username or password")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("URL has no host")
    parts.port  # noqa: B018  (raises ValueError for an invalid port)

    if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
        raise ValueError("URL points to an internal host, which is not allowed")

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if _NUMERIC_LABEL.match(host.rsplit(".", 1)[-1]):
            raise ValueError("Use a normal hostname or a standard IP address")
        return url.strip()

    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not ip.is_global:
        raise ValueError("URL points to a private or internal address, which is not allowed")
    return url.strip()