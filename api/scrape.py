import markdownify
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from utils.errors import internal_error
from utils.scraper import fetch_and_parse

router = APIRouter()


class ScrapeInput(BaseModel):
    url: str = Field(max_length=2048)


@router.post("/scrape")
def scrape_raw_data(data: ScrapeInput):
    """Convert a web page's HTML into clean Markdown."""
    try:
        _, soup = fetch_and_parse(data.url)

        # Scripts and styles are not content; drop them before converting.
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        raw_markdown = markdownify.markdownify(str(soup), heading_style="ATX")
        clean_markdown = "\n".join(
            line for line in raw_markdown.splitlines() if line.strip()
        )

        return {"status": "success", "markdown": clean_markdown}

    except HTTPException:
        raise
    except Exception:
        raise internal_error("Something went wrong while extracting the page content.")
