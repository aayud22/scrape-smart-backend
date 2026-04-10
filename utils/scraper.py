import cloudscraper
from bs4 import BeautifulSoup
from fastapi import HTTPException
import requests

# --- START OF UTILITY FUNCTIONS ---

def fetch_and_parse(url: str, timeout: int = 15):
    """
    Centralized utility to fetch a webpage using CloudScraper and parse it with BeautifulSoup.
    
    Why: 
    - Eliminates repetitive setup code across endpoints (DRY principle).
    - Uses 'cloudscraper' universally to bypass basic anti-bot protections (e.g., Cloudflare) ensuring consistent access.
    - Standardizes the HTTP headers and timeout values to mimic a genuine desktop browser request.
    - Centralizes error handling so that any scraping failure immediately surfaces as an informative HTTP 400 error.
    """
    try:
        # Configure the scraper to imitate a Chrome browser on Windows, improving request success rates
        scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        
        # Include comprehensive headers to prevent 403 Forbidden errors from strict firewalls
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        }
        
        # Execute the network request. Timeout defaults to a standard 15s to balance speed and reliability.
        response = scraper.get(url, headers=headers, timeout=timeout)
        
        # We explicitly check for success to catch and handle common non-200 responses gracefully
        if response.status_code != 200:
            raise Exception(f"Received unexpected HTTP status code: {response.status_code}")
            
        # Parse the HTML content using BeautifulSoup for downstream data extraction
        soup = BeautifulSoup(response.text, 'html.parser')
        
        return response, soup
    except requests.exceptions.ConnectionError:
        raise HTTPException(status_code=400, detail="Website not found or offline. Please check the URL and try again.")
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=400, detail="The website took too long to respond. It might be down.")
    except Exception as e:
        # Wrap any network or parsing error in a standard FastAPI HTTPException for a predictable API response format
        raise HTTPException(status_code=400, detail=f"Failed to scrape website '{url}': {str(e)}")

# --- END OF UTILITY FUNCTIONS ---
