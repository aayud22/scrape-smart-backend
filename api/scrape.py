from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import markdownify
from utils.scraper import fetch_and_parse

router = APIRouter()

class ScrapeInput(BaseModel):
    url: str

@router.post("/scrape")
async def scrape_raw_data(data: ScrapeInput):
    """
    Extracts webpage text content and translates standard HTML tags into Markdown format.
    Why: LLMs or text-based processors parse structural formatting natively and efficiently across Markdown files.
    """
    try:
        # Fetch the target HTML using our centralized scraper Utility
        response, _ = fetch_and_parse(data.url)
        
        # Transform structural HTML blocks (like headers) into native markdown equivalents
        raw_markdown = markdownify.markdownify(response.text, heading_style="ATX")
        
        # Eliminate excessive whitespace and empty lines to provide robust and clean markdown output
        clean_markdown = "\n".join([line for line in raw_markdown.splitlines() if line.strip()])
        
        return {
            "status": "success",
            "markdown": clean_markdown
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"An unexpected error occurred while extracting raw markdown: {str(e)}")
