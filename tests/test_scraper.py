import pytest
import requests
from fastapi import HTTPException

from tests.conftest import FakeResponse
from utils import scraper
from utils.scraper import UnsafeURLError, fetch_and_parse, validate_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://224.0.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://internal.test/",
    ],
)
def test_blocks_non_public_addresses(url):
    with pytest.raises(UnsafeURLError):
        validate_public_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://example.com/",
        "javascript:alert(1)",
        "//example.com/",
        "",
        "http://user:pass@example.com/",
        "http://example.com:8080/",
        "http://example.com:22/",
    ],
)
def test_blocks_bad_schemes_ports_and_credentials(url):
    with pytest.raises(UnsafeURLError):
        validate_public_url(url)


def test_allows_public_sites():
    validate_public_url("https://example.com/path?q=1")
    validate_public_url("http://example.com")
    validate_public_url("https://93.184.216.34/")


def test_unresolvable_host_is_a_connection_error():
    with pytest.raises(requests.exceptions.ConnectionError):
        validate_public_url("https://does-not-exist.invalid/")


def test_redirect_to_internal_address_is_blocked_before_it_is_requested(use_scraper):
    fake = use_scraper(
        FakeResponse(302, {"Location": "http://169.254.169.254/latest/meta-data/"}, chunks=())
    )
    with pytest.raises(HTTPException) as exc:
        fetch_and_parse("https://example.com/")
    assert exc.value.status_code == 400
    assert fake.urls == ["https://example.com/"]  # the internal URL was never requested


def test_safe_redirects_are_followed(use_scraper):
    fake = use_scraper(
        FakeResponse(301, {"Location": "/home"}, chunks=()),
        FakeResponse(200, chunks=(b"<html><title>Home</title></html>",)),
    )
    page, soup = fetch_and_parse("https://example.com/")
    assert fake.urls == ["https://example.com/", "https://example.com/home"]
    assert soup.title.string == "Home"
    assert page.url == "https://example.com/home"


def test_too_many_redirects(use_scraper):
    use_scraper(*[FakeResponse(302, {"Location": "/again"}, chunks=()) for _ in range(10)])
    with pytest.raises(HTTPException) as exc:
        fetch_and_parse("https://example.com/")
    assert "too many" in exc.value.detail


def test_response_size_is_capped(use_scraper):
    big = b"x" * (scraper.MAX_RESPONSE_BYTES // 2 + 1)
    use_scraper(FakeResponse(200, chunks=(big, big)))
    with pytest.raises(HTTPException) as exc:
        fetch_and_parse("https://example.com/")
    assert "too large" in exc.value.detail


def test_declared_content_length_is_rejected_early(use_scraper):
    headers = {"Content-Type": "text/html", "Content-Length": str(scraper.MAX_RESPONSE_BYTES + 1)}
    use_scraper(FakeResponse(200, headers, chunks=(b"never read",)))
    with pytest.raises(HTTPException) as exc:
        fetch_and_parse("https://example.com/")
    assert "too large" in exc.value.detail


def test_non_web_content_is_rejected(use_scraper):
    use_scraper(FakeResponse(200, {"Content-Type": "application/pdf"}))
    with pytest.raises(HTTPException) as exc:
        fetch_and_parse("https://example.com/file.pdf")
    assert "web page" in exc.value.detail


def test_non_200_status_is_reported_without_internals(use_scraper):
    use_scraper(FakeResponse(404, chunks=()))
    with pytest.raises(HTTPException) as exc:
        fetch_and_parse("https://example.com/missing")
    assert exc.value.status_code == 400
    assert "404" in exc.value.detail


def test_unexpected_errors_do_not_leak_details(monkeypatch):
    def boom(url, timeout):
        raise RuntimeError("secret internal detail 10.1.2.3")

    monkeypatch.setattr(scraper, "_download", boom)
    with pytest.raises(HTTPException) as exc:
        fetch_and_parse("https://example.com/")
    assert "secret" not in exc.value.detail and "10.1.2.3" not in exc.value.detail


def test_timeouts_get_their_own_message(monkeypatch):
    def slow(url, timeout):
        raise requests.exceptions.ConnectTimeout()  # subclass of ConnectionError AND Timeout

    monkeypatch.setattr(scraper, "_download", slow)
    with pytest.raises(HTTPException) as exc:
        fetch_and_parse("https://example.com/")
    assert "too long" in exc.value.detail


def test_cache_avoids_refetching_and_returns_independent_soups(use_scraper):
    fake = use_scraper(FakeResponse(200, chunks=(b"<html><script>x</script><p>hi</p></html>",)))
    _, first = fetch_and_parse("https://example.com/")
    first.find("script").decompose()  # callers mutate their soup
    _, second = fetch_and_parse("https://example.com/")
    assert len(fake.urls) == 1
    assert second.find("script") is not None


def test_cache_expires(use_scraper, monkeypatch):
    fake = use_scraper(FakeResponse(200), FakeResponse(200))
    fetch_and_parse("https://example.com/")
    monkeypatch.setattr(scraper, "CACHE_TTL_SECONDS", -1)
    fetch_and_parse("https://example.com/")
    assert len(fake.urls) == 2


def test_cache_is_bounded(use_scraper, monkeypatch):
    monkeypatch.setattr(scraper, "CACHE_MAX_ENTRIES", 2)
    use_scraper(*[FakeResponse(200) for _ in range(3)])
    for i in range(3):
        fetch_and_parse(f"https://example.com/{i}")
    assert len(scraper._cache) == 2
