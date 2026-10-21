from __future__ import annotations

import ipaddress
import logging
import socket
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import cloudscraper
from fastapi import HTTPException
import requests

logger = logging.getLogger("scrapesmart")

MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2 MB
CACHE_TTL_SECONDS = 300  # 5 minutes
CACHE_MAX_ENTRIES = 20
MAX_REDIRECTS = 5

_cache: dict[str, tuple[str, str, float]] = {}


class UnsafeURLError(ValueError):
    """Raised when a URL is deemed unsafe (private IP, bad scheme/port, etc.)."""
    pass


class ScrapedPage:
    def __init__(self, url: str, text: str = "", status_code: int = 200, headers: dict | None = None):
        self.url = url
        self.text = text
        self.status_code = status_code
        self.headers = headers or {}


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def validate_public_url(url: str) -> None:
    """Validate that a URL is well-formed and targets a public host on port 80/443."""
    if not url or not isinstance(url, str):
        raise UnsafeURLError("URL must be a non-empty string.")

    parsed = urlsplit(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise UnsafeURLError(f"Unsupported URL scheme '{scheme}'. Only http and https are allowed.")

    if parsed.username or parsed.password:
        raise UnsafeURLError("Embedded credentials in URL are not allowed.")

    if parsed.port is not None and parsed.port not in (80, 443):
        raise UnsafeURLError(f"Port {parsed.port} is not allowed. Only ports 80 and 443 are allowed.")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError("URL must contain a valid hostname.")

    port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)

    try:
        addrinfo = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, socket.error) as e:
        raise requests.exceptions.ConnectionError(f"Could not resolve host '{hostname}': {e}")

    if not addrinfo:
        raise requests.exceptions.ConnectionError(f"No address found for host '{hostname}'.")

    for item in addrinfo:
        sockaddr = item[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise UnsafeURLError(f"Invalid IP address: {ip_str}")

        if not _is_public_ip(ip):
            raise UnsafeURLError(f"Host '{hostname}' resolves to a non-public IP ({ip_str}).")


def ensure_public_url(url: str) -> None:
    """Validate that a URL is public or raise HTTPException with status 400."""
    try:
        validate_public_url(url)
    except UnsafeURLError:
        raise HTTPException(status_code=400, detail="This address is not allowed.")
    except requests.exceptions.Timeout:
        raise HTTPException(
            status_code=400,
            detail="The website took too long to respond. It might be down.",
        )
    except requests.exceptions.ConnectionError:
        raise HTTPException(
            status_code=400,
            detail="Website not found or offline. Please check the URL and try again.",
        )


def _download(url: str, timeout: int = 15) -> tuple[str, str]:
    """Download a web page, following redirects manually and validating each target."""
    try:
        validate_public_url(url)
    except UnsafeURLError:
        raise HTTPException(status_code=400, detail="This address is not allowed.")

    scraper_client = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )

    current_url = url
    redirects_followed = 0

    while True:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        }

        response = scraper_client.get(
            current_url, headers=headers, timeout=timeout, allow_redirects=False
        )

        if response.status_code in (301, 302, 303, 307, 308):
            redirects_followed += 1
            if redirects_followed > MAX_REDIRECTS:
                raise HTTPException(status_code=400, detail="The website redirected too many times.")

            location = response.headers.get("Location")
            if not location:
                raise HTTPException(status_code=400, detail="Redirect response missing Location header.")

            next_url = urljoin(current_url, location)
            try:
                validate_public_url(next_url)
            except UnsafeURLError:
                raise HTTPException(status_code=400, detail="This address is not allowed.")

            current_url = next_url
            continue

        if response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Received status code {response.status_code} from website.",
            )

        content_type = response.headers.get("Content-Type", "")
        if content_type:
            media_type = content_type.split(";")[0].strip().lower()
            allowed = ("text/html", "application/xhtml+xml", "application/xml", "text/xml", "text/plain")
            if not any(t in media_type for t in allowed):
                raise HTTPException(
                    status_code=400,
                    detail="The requested URL is not a supported web page.",
                )

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > MAX_RESPONSE_BYTES:
                    raise HTTPException(
                        status_code=400,
                        detail="The page content is too large to process.",
                    )
            except ValueError:
                pass

        chunks = []
        total_bytes = 0
        try:
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total_bytes += len(chunk)
                if total_bytes > MAX_RESPONSE_BYTES:
                    raise HTTPException(
                        status_code=400,
                        detail="The page content is too large to process.",
                    )
                chunks.append(chunk)
        finally:
            if hasattr(response, "close"):
                response.close()

        raw_data = b"".join(chunks)
        encoding = getattr(response, "encoding", None) or "utf-8"
        try:
            text = raw_data.decode(encoding, errors="replace")
        except Exception:
            text = raw_data.decode("utf-8", errors="replace")

        return current_url, text


def fetch_and_parse(url: str, timeout: int = 15):
    """Fetch a public webpage, validate safety rules, and return (page, soup)."""
    now = time.time()
    if url in _cache:
        cached_final_url, cached_text, cached_time = _cache[url]
        if now - cached_time < CACHE_TTL_SECONDS:
            soup = BeautifulSoup(cached_text, "html.parser")
            return ScrapedPage(url=cached_final_url, text=cached_text), soup
        else:
            _cache.pop(url, None)

    try:
        final_url, html_text = _download(url, timeout=timeout)
    except HTTPException:
        raise
    except requests.exceptions.Timeout:
        raise HTTPException(
            status_code=400,
            detail="The website took too long to respond. It might be down.",
        )
    except requests.exceptions.ConnectionError:
        raise HTTPException(
            status_code=400,
            detail="Website not found or offline. Please check the URL and try again.",
        )
    except Exception:
        logger.exception("Unexpected error fetching %s", url)
        raise HTTPException(
            status_code=400,
            detail="Failed to scrape website.",
        )

    soup = BeautifulSoup(html_text, "html.parser")

    if url in _cache:
        del _cache[url]
    elif len(_cache) >= CACHE_MAX_ENTRIES:
        oldest_key = next(iter(_cache))
        del _cache[oldest_key]
    _cache[url] = (final_url, html_text, now)

    return ScrapedPage(url=final_url, text=html_text), soup
