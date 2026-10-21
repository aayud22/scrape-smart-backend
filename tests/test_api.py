import pytest
from bs4 import BeautifulSoup
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from api import chat, map as map_api, score, scrape
from api.map import is_internal

client = TestClient(main.app)


def soup_of(html: str):
    return BeautifulSoup(html, "html.parser")


def patch_fetch(monkeypatch, module, html=None, error=None):
    def fake(url, timeout=15):
        if error:
            raise error
        return object(), soup_of(html)

    monkeypatch.setattr(module, "fetch_and_parse", fake)


PERFECT = """<html><head><title>T</title><meta name="description" content="d"></head>
<body><h1>One</h1><h2>Two</h2><img src="a.png" alt="a"></body></html>"""


# ---------- /health and CORS ----------
def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_cors_allows_the_frontend_and_rejects_others():
    ok = client.options(
        "/score",
        headers={
            "Origin": "https://scrape-smart-ai.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert ok.headers.get("access-control-allow-origin") == "https://scrape-smart-ai.vercel.app"

    bad = client.options(
        "/score",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers


def test_search_route_is_gone():
    assert client.get("/search", params={"query": "x"}).status_code == 404


# ---------- /score: the frontend parses these exact strings ----------
def test_score_contract_perfect_page(monkeypatch):
    patch_fetch(monkeypatch, score, PERFECT)
    body = client.post("/score", json={"url": "https://example.com"}).json()
    assert body["status"] == "success"
    assert body["seo_score"] == 100
    assert body["details"] == [
        "✅ Title Tag is present.",
        "✅ Meta Description is present.",
        "✅ Perfect! Only one H1 tag found.",
        "✅ Proper use of H2 tags for content structure.",
        "✅ All 1 images have alt text.",
    ]


def test_score_contract_bad_page(monkeypatch):
    patch_fetch(monkeypatch, score, "<html><body><h1>a</h1><h1>b</h1><img src=x></body></html>")
    body = client.post("/score", json={"url": "https://example.com"}).json()
    assert body["seo_score"] == 10
    assert any(d.startswith("❌ Missing Title Tag") for d in body["details"])
    assert any(d.startswith("⚠️ Multiple H1") for d in body["details"])
    assert any(d.startswith("❌ 1 out of 1 images are missing alt text") for d in body["details"])


def test_scraper_errors_pass_through_with_their_status(monkeypatch):
    patch_fetch(monkeypatch, score, error=HTTPException(400, "Website not found or offline."))
    r = client.post("/score", json={"url": "https://example.com"})
    assert r.status_code == 400 and r.json()["detail"] == "Website not found or offline."


@pytest.mark.parametrize(
    "module,path",
    [(score, "/score"), (scrape, "/scrape"), (chat, "/chat")],
)
def test_unexpected_errors_never_leak_details(monkeypatch, module, path):
    patch_fetch(monkeypatch, module, error=RuntimeError("secret detail gemini-2.5-flash key"))
    payload = {"url": "https://example.com"}
    if path == "/chat":
        payload["question"] = "hi"
    r = client.post(path, json=payload)
    assert r.status_code == 500
    assert "secret" not in r.text and "gemini" not in r.text


# ---------- /scrape ----------
def test_scrape_returns_markdown_without_script_text(monkeypatch):
    html = "<html><head><style>.a{color:red}</style></head><body><h1>Title</h1><script>var secret=1</script><p>Body</p></body></html>"
    patch_fetch(monkeypatch, scrape, html)
    body = client.post("/scrape", json={"url": "https://example.com"}).json()
    assert body["status"] == "success"
    assert "# Title" in body["markdown"] and "Body" in body["markdown"]
    assert "secret" not in body["markdown"] and "color:red" not in body["markdown"]


# ---------- /chat ----------
class FakeLLM:
    def __init__(self, error=None):
        self.error, self.prompt = error, None

    def invoke(self, prompt):
        self.prompt = prompt
        if self.error:
            raise self.error

        class R:
            content = "answer"

        return R()


def test_chat_success_and_prompt_hardening(monkeypatch):
    html = "<html><head><title>Shop</title></head><body><script>TRACKING()</script><p>We sell tea.</p></body></html>"
    patch_fetch(monkeypatch, chat, html)
    llm = FakeLLM()
    monkeypatch.setattr(chat, "get_llm", lambda: llm)

    r = client.post("/chat", json={"url": "https://example.com", "question": "What is sold?"})
    assert r.json() == {"status": "success", "bot_reply": "answer"}
    assert "We sell tea." in llm.prompt
    assert "TRACKING" not in llm.prompt  # script text removed from the context
    assert "UNTRUSTED" in llm.prompt and "<page_content>" in llm.prompt


def test_chat_provider_error_is_hidden_from_the_client(monkeypatch):
    patch_fetch(monkeypatch, chat, PERFECT)
    err = RuntimeError("Error calling model 'gemini-2.5-flash' (INVALID_ARGUMENT): API key not valid")
    monkeypatch.setattr(chat, "get_llm", lambda: FakeLLM(error=err))

    r = client.post("/chat", json={"url": "https://example.com", "question": "hi"})
    assert r.status_code == 503
    assert r.json()["detail"] == "The AI service is temporarily unavailable. Please try again later."
    assert "gemini" not in r.text and "API key" not in r.text


def test_missing_api_key_only_breaks_chat(monkeypatch):
    chat.get_llm.cache_clear()
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    patch_fetch(monkeypatch, chat, PERFECT)
    patch_fetch(monkeypatch, score, PERFECT)

    r = client.post("/chat", json={"url": "https://example.com", "question": "hi"})
    assert r.status_code == 503 and "key" not in r.text.lower()
    assert client.post("/score", json={"url": "https://example.com"}).status_code == 200
    chat.get_llm.cache_clear()


def test_chat_rejects_oversized_or_empty_input():
    big = client.post("/chat", json={"url": "https://example.com", "question": "x" * 4001})
    empty = client.post("/chat", json={"url": "https://example.com", "question": ""})
    assert big.status_code == 422 and empty.status_code == 422


# ---------- /map ----------
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://example.com/a", True),
        ("https://www.example.com/a", True),
        ("https://blog.example.com/a", True),
        ("https://example.com.evil.io/a", False),
        ("https://notexample.com/a", False),
        ("https://evil.io/example.com", False),
        ("mailto:a@example.com", False),
    ],
)
def test_is_internal_compares_whole_hostnames(url, expected):
    assert is_internal(url, "example.com") is expected


def map_fetcher(pages):
    def fake(url, timeout=15):
        if url not in pages:
            raise HTTPException(400, "nope")
        return object(), soup_of(pages[url])

    return fake


def test_map_expands_sitemap_index_and_skips_external_links(monkeypatch):
    monkeypatch.setattr(map_api, "ensure_public_url", lambda u: None)
    pages = {
        "https://example.com/sitemap_index.xml": "<sitemapindex><sitemap><loc>https://example.com/post-sitemap.xml</loc></sitemap></sitemapindex>",
        "https://example.com/post-sitemap.xml": "<urlset><url><loc>https://example.com/blog/hello-world</loc></url><url><loc>https://example.com.evil.io/x</loc></url></urlset>",
    }
    monkeypatch.setattr(map_api, "fetch_and_parse", map_fetcher(pages))
    body = client.post("/map", json={"url": "https://example.com"}).json()
    urls = [l["url"] for l in body["links"]]
    assert urls == ["https://example.com/blog/hello-world"]
    assert body["links"][0]["title"] == "Hello World"
    assert body["total_links_found"] == 1


def test_map_falls_back_to_homepage_links(monkeypatch):
    monkeypatch.setattr(map_api, "ensure_public_url", lambda u: None)
    home = '<a href="/about">About us</a><a href="https://other.com/x">Out</a><a href="mailto:a@b.c">m</a><a href="/about#team">dup</a>'
    monkeypatch.setattr(map_api, "fetch_and_parse", map_fetcher({"https://example.com": home}))
    body = client.post("/map", json={"url": "https://example.com"}).json()
    assert body["links"] == [{"url": "https://example.com/about", "title": "About us"}]


def test_map_rejects_private_urls_instead_of_returning_a_fake_homepage():
    r = client.post("/map", json={"url": "http://127.0.0.1/"})
    assert r.status_code == 400
    assert r.json()["detail"] == "This address is not allowed."


def test_map_caps_the_number_of_links(monkeypatch):
    monkeypatch.setattr(map_api, "ensure_public_url", lambda u: None)
    locs = "".join(f"<url><loc>https://example.com/p{i}</loc></url>" for i in range(300))
    monkeypatch.setattr(
        map_api, "fetch_and_parse", map_fetcher({"https://example.com/sitemap_index.xml": f"<urlset>{locs}</urlset>"})
    )
    body = client.post("/map", json={"url": "https://example.com"}).json()
    assert body["total_links_found"] == 100
