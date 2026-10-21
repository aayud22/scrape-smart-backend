from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.errors import internal_error
from utils.scraper import ensure_public_url, fetch_and_parse

router = APIRouter()

MAX_LINKS = 100
MAX_CHILD_SITEMAPS = 3


class MapInput(BaseModel):
    url: str = Field(max_length=2048)


def _host(url: str) -> str:
    """Lower-cased hostname without a leading 'www.'."""
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def is_internal(url: str, base_host: str) -> bool:
    """True for the site's own host or one of its subdomains.

    Compares whole hostnames; a substring test would wrongly accept hosts such
    as 'example.com.evil.io' or 'notexample.com'.
    """
    host = _host(url)
    return bool(host) and (host == base_host or host.endswith("." + base_host))


def _read_sitemap(sitemap_url: str):
    """Return (page_urls, child_sitemap_urls) for a sitemap, or ([], []) on any failure."""
    try:
        _, soup = fetch_and_parse(sitemap_url, timeout=5)
    except HTTPException:
        return [], []

    pages, children = [], []
    for loc in soup.find_all("loc"):
        value = loc.get_text(strip=True)
        if not value:
            continue
        if value.lower().split("?")[0].endswith(".xml"):
            children.append(value)  # a sitemap index lists other sitemaps
        else:
            pages.append(value)
    return pages, children


@router.post("/map")
def map_website_links(data: MapInput):
    """Discover pages on a site: sitemap(s) first, homepage links as a fallback."""
    ensure_public_url(data.url)

    try:
        base_url = data.url.rstrip("/")
        parsed_base = urlparse(base_url)
        base_host = _host(base_url)
        origin = f"{parsed_base.scheme}://{parsed_base.netloc}"

        links_data, seen_urls = [], set()

        def add_link(url_to_add: str, link_title: str) -> None:
            clean_url = url_to_add.split("#")[0].rstrip("/")
            if not clean_url or clean_url in seen_urls or not is_internal(clean_url, base_host):
                return
            seen_urls.add(clean_url)

            if not link_title or link_title == "No Title":
                parts = urlparse(clean_url).path.strip("/").split("/")
                link_title = parts[-1].replace("-", " ").title() if parts and parts[-1] else "Homepage"

            links_data.append({"url": clean_url, "title": link_title})

        # 1) Sitemaps. A sitemap index points to child sitemaps, which hold the pages.
        for sitemap_url in (
            f"{origin}/sitemap_index.xml",
            f"{origin}/wp-sitemap.xml",
            f"{origin}/sitemap.xml",
        ):
            pages, children = _read_sitemap(sitemap_url)
            for child in children[:MAX_CHILD_SITEMAPS]:
                if is_internal(child, base_host):
                    child_pages, _ = _read_sitemap(child)
                    pages.extend(child_pages)

            for page_url in pages:
                add_link(page_url, "")
                if len(links_data) >= MAX_LINKS:
                    break
            if links_data:
                break

        # 2) Fallback: links found on the page itself.
        if len(links_data) < 2:
            try:
                _, soup = fetch_and_parse(data.url, timeout=10)
                for a_tag in soup.find_all("a", href=True):
                    href = a_tag["href"].strip()
                    if href.startswith(("javascript:", "mailto:", "tel:")):
                        continue
                    add_link(urljoin(base_url + "/", href), a_tag.get_text(strip=True) or "No Title")
                    if len(links_data) >= MAX_LINKS:
                        break
            except HTTPException:
                pass

        if not links_data:
            add_link(base_url, "Homepage")

        return {
            "status": "success",
            "total_links_found": len(links_data),
            "links": links_data,
        }

    except HTTPException:
        raise
    except Exception:
        raise internal_error("Something went wrong while mapping the website.")
