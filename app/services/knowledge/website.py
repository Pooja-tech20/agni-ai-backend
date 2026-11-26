
"""Extract readable content from public websites."""

import http.client
import ipaddress
import socket
import ssl
import certifi

from urllib.parse import urlsplit, urljoin, quote

from bs4 import BeautifulSoup

from app.services.knowledge.extractor import (
    KnowledgeExtractionError,
    validate_content,
)


MAX_RESPONSE_SIZE = 2_000_000
REQUEST_TIMEOUT = 10
MAX_REDIRECTS = 3


def validate_url(url: str):
    """Allow only public HTTP and HTTPS destinations."""

    if any(ord(char) < 32 for char in url):
        raise KnowledgeExtractionError("Invalid URL.")

    parsed = urlsplit(url)

    if parsed.scheme not in {"http", "https"}:
        raise KnowledgeExtractionError(
            "Only HTTP and HTTPS URLs are supported."
        )

    if not parsed.hostname:
        raise KnowledgeExtractionError("Invalid hostname.")

    if parsed.username or parsed.password:
        raise KnowledgeExtractionError(
            "URLs containing credentials are not allowed."
        )

    port = parsed.port or (
        443 if parsed.scheme == "https" else 80
    )

    expected_port = (
        443 if parsed.scheme == "https" else 80
    )

    if port != expected_port:
        raise KnowledgeExtractionError(
            "Non-standard website ports are not allowed."
        )

    hostname = parsed.hostname.encode("idna").decode("ascii")

    addresses = socket.getaddrinfo(
        hostname,
        port,
        type=socket.SOCK_STREAM,
    )

    public_ips = []

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])

        if isinstance(ip, ipaddress.IPv6Address):
            if ip.ipv4_mapped:
                ip = ip.ipv4_mapped

        if (
            not ip.is_global
            or ip.is_multicast
            or ip.is_reserved
            or getattr(ip, "is_site_local", False)
        ):
            raise KnowledgeExtractionError(
                "Private or restricted network URLs "
                "are not allowed."
            )

        public_ips.append(str(ip))

    if not public_ips:
        raise KnowledgeExtractionError(
            "Website hostname could not be resolved."
        )

    return parsed, hostname, port, public_ips[0]


def fetch_page(url: str):
    """Fetch a website using its validated public IP."""

    parsed, hostname, port, ip = validate_url(url)

    if parsed.scheme == "https":
        connection = http.client.HTTPSConnection(
            hostname,
            port,
            timeout=REQUEST_TIMEOUT,
            context=ssl.create_default_context(
                cafile=certifi.where()
            ),
        )
    else:
        connection = http.client.HTTPConnection(
            hostname,
            port,
            timeout=REQUEST_TIMEOUT,
        )

    # Connect to the validated IP instead of resolving
    # the hostname again. HTTPS still verifies the hostname.
    connection._create_connection = (
        lambda address, timeout, source_address:
        socket.create_connection(
            (ip, port),
            timeout,
            source_address,
        )
    )

    path = quote(
        parsed.path or "/",
        safe="/%:@!$&'()*+,;=-._~",
    )

    if parsed.query:
        path += "?" + quote(
            parsed.query,
            safe="%=&?/:+;,@!$'()*-._~",
        )

    try:
        connection.request(
            "GET",
            path,
            headers={
                "User-Agent": "JeevaAI-KnowledgeBase/1.0",
                "Accept": "text/html,text/plain",
                "Accept-Encoding": "identity",
            },
        )

        response = connection.getresponse()

        if response.status in {301, 302, 303, 307, 308}:
            location = response.getheader("Location")

            if not location:
                raise KnowledgeExtractionError(
                    "Invalid website redirect."
                )

            return None, urljoin(url, location)

        if response.status != 200:
            raise KnowledgeExtractionError(
                f"Website returned HTTP {response.status}."
            )

        content_type = response.headers.get_content_type()

        if content_type not in {
            "text/html",
            "text/plain",
            "application/xhtml+xml",
        }:
            raise KnowledgeExtractionError(
                "Unsupported website content type."
            )

        encoding = response.getheader(
            "Content-Encoding", "identity"
        )

        if encoding.lower() != "identity":
            raise KnowledgeExtractionError(
                "Unsupported response encoding."
            )

        data = response.read(MAX_RESPONSE_SIZE + 1)

        if len(data) > MAX_RESPONSE_SIZE:
            raise KnowledgeExtractionError(
                "Website content exceeds the size limit."
            )

        if content_type == "text/plain":
            charset = (
                response.headers.get_content_charset()
                or "utf-8"
            )
            return data.decode(
                charset, errors="replace"
            ), None

        soup = BeautifulSoup(data, "html.parser")

        for element in soup(
            [
                "script",
                "style",
                "noscript",
                "iframe",
                "nav",
                "footer",
                "header",
                "svg",
            ]
        ):
            element.decompose()

        text = soup.get_text(
            separator="\n",
            strip=True,
        )

        return text, None

    finally:
        connection.close()


def extract_website(url: str) -> str:
    """Extract readable text from a public webpage."""

    try:
        for _ in range(MAX_REDIRECTS + 1):

            content, redirect = fetch_page(url)

            if redirect:
                url = redirect
                continue

            return validate_content(content or "")

        raise KnowledgeExtractionError(
            "Too many website redirects."
        )

    except KnowledgeExtractionError:
        raise

    except Exception as exc:
        raise KnowledgeExtractionError(
            "Failed to extract website content."
        ) from exc
