import ipaddress
import socket

import pytest

from utils import scraper

HOSTS = {"example.com": "93.184.216.34", "internal.test": "10.0.0.5"}


def fake_getaddrinfo(host, port, type=0, **kwargs):
    """Resolve known test hosts and IP literals without touching the network."""
    if host in HOSTS:
        ip = HOSTS[host]
    else:
        try:
            ipaddress.ip_address(host)
            ip = host
        except ValueError:
            raise socket.gaierror("unknown host")
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (ip, port))]


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=(b"<html><title>T</title></html>",)):
        self.status_code = status
        self.headers = {"Content-Type": "text/html; charset=utf-8"} if headers is None else headers
        self._chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size=65536):
        yield from self._chunks

    def close(self):
        self.closed = True


class FakeScraper:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **kwargs):
        assert kwargs.get("allow_redirects") is False, "redirects must be followed manually"
        self.urls.append(url)
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(scraper.socket, "getaddrinfo", fake_getaddrinfo)
    scraper._cache.clear()
    yield
    scraper._cache.clear()


@pytest.fixture
def use_scraper(monkeypatch):
    def _use(*responses):
        fake = FakeScraper(*responses)
        monkeypatch.setattr(scraper.cloudscraper, "create_scraper", lambda **kw: fake)
        return fake

    return _use
