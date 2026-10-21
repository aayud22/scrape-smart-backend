# ScrapeSmart API

FastAPI backend for [ScrapeSmart AI](https://github.com/aayud22/scrape-smart-ai-chatbot-frontend).
It fetches a public web page and provides four things for the frontend: a basic SEO score,
a Markdown version of the page, a list of the site's pages, and AI answers about the page.

## Endpoints

All endpoints take JSON `{"url": "https://example.com"}` and return `{"status": "success", ...}`.

| Endpoint | Extra input | Returns |
| --- | --- | --- |
| `POST /score` | none | `seo_score` (0-100) and `details`, a list of ✅/⚠️/❌ messages |
| `POST /scrape` | none | `markdown`, the page converted to Markdown (scripts and styles removed) |
| `POST /map` | none | `links`: up to 100 `{url, title}` pages, plus `total_links_found` |
| `POST /chat` | `question` (1-4000 chars) | `bot_reply`, an answer from Gemini |
| `GET /health` | none | `{"status": "ok"}` |

Errors use FastAPI's `{"detail": "..."}` format with short, user-safe messages.

### How each endpoint works

- **/score** is a simple rule-based check, not a full audit: title (20), meta description (20),
  one H1 (20; 10 if there are several), at least one H2 (10), and image alt text (30, proportional).
- **/map** reads `sitemap_index.xml`, `wp-sitemap.xml` or `sitemap.xml` (following up to 3 child
  sitemaps), and falls back to links on the page itself. It keeps only the site's own host and
  its subdomains.
- **/chat** sends Gemini the page's SEO data and the first 5,000 characters of visible text. Page
  text is treated as untrusted data in the prompt.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # then set GOOGLE_API_KEY
uvicorn main:app --reload --port 8000
```

Interactive docs are at http://localhost:8000/docs. Run the tests with `pytest`; they use fake
network calls and need no API key.

### Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `GOOGLE_API_KEY` | for `/chat` | Gemini API key. Without it only `/chat` fails; the other endpoints keep working. |
| `GEMINI_MODEL` | no | Model name, default `gemini-2.5-flash` |
| `CORS_ORIGINS` | no | Comma-separated allowed origins; replaces the defaults |

On a host such as Render, set these as environment variables in the dashboard and redeploy after
changing them. Example start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`.

## Safety measures

Because anyone can send this service a URL, the fetcher (`utils/scraper.py`) is deliberately strict:

- Only `http`/`https` on ports 80 and 443; no embedded credentials.
- The hostname must resolve to public addresses only. Loopback, private, link-local (including
  cloud metadata addresses), reserved and multicast ranges are refused.
- Redirects are followed manually (max 5) and every hop is validated again.
- Responses are limited to 2 MB and must be HTML, XML or text.
- Provider and internal errors are logged on the server and never returned to the client.
- Successful fetches are cached in memory for 5 minutes (up to 20 pages), so one analysis session
  does not re-download the same page for every request.

## Known limitations

- **DNS rebinding:** the address check happens just before the request, so a hostile DNS server
  that changes its answer between the two could still bypass it. Pinning the resolved IP is not
  implemented.
- **No rate limiting:** a public `/chat` endpoint can be used up by anyone. Keep the Gemini key on a
  free or capped quota, and add rate limiting before wider use.
- **Pages that need JavaScript** to render their content are read as the raw HTML only.
- **robots.txt is not read.** The fetcher uses `cloudscraper` to get through basic anti-bot
  protection, so only analyze sites you are allowed to access.
- **In-memory cache** is per process and is lost on restart.
- Free hosting tiers sleep when idle, so the first request after a pause can take a while.
