from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from urllib.parse import urlparse, urljoin
from utils.scraper import fetch_and_parse

router = APIRouter()

class MapInput(BaseModel):
    url: str

@router.post("/map")
async def map_website_links(data: MapInput):
    """
    Discovers URLs on a given domain using a hybrid approach.
    It first attempts to locate standard XML sitemaps for efficiency, 
    falling back to extracting links directly from the homepage HTML if no sitemap is found.
    """
    try:
        base_url = data.url.rstrip('/')
        parsed_base = urlparse(base_url)
        domain = parsed_base.netloc
        base_domain = domain.replace("www.", "") # Normalizing domain allows matching "www.example.com" and "example.com"
        scheme = parsed_base.scheme

        links_data = []
        seen_urls = set()

        def add_link(url_to_add, link_title):
            """
            Sanitizes URLs and guarantees uniqueness before recording them.
            Why: Internal anchors (e.g. #section) technically point to the same page, preventing mapped duplicates.
            """
            clean_url = url_to_add.split('#')[0].rstrip('/')
            if not clean_url: 
                return
            
            parsed_clean = urlparse(clean_url)
            
            # Enforce that only internal links are mapped to avoid spidering out of the target domain
            if base_domain in parsed_clean.netloc and clean_url not in seen_urls:
                seen_urls.add(clean_url)
                
                # Automatically generate a human-readable title from the URL path if one is missing
                if not link_title or link_title == "No Title":
                    path_parts = parsed_clean.path.strip('/').split('/')
                    link_title = path_parts[-1].replace('-', ' ').title() if path_parts and path_parts[-1] else "Homepage"
                
                links_data.append({"url": clean_url, "title": link_title})

        # List of industry-standard sitemap paths (common in WordPress and custom setups)
        sitemap_urls = [
            f"{scheme}://{domain}/sitemap_index.xml",
            f"{scheme}://{domain}/wp-sitemap.xml",
            f"{scheme}://{domain}/sitemap.xml"
        ]

        sitemap_found = False
        
        # Attempt to populate the map using canonical sitemaps first
        for s_url in sitemap_urls:
            try:
                # We use a shorter timeout since missing sitemaps will hang unnecessarily
                _, sitemap_soup = fetch_and_parse(s_url, timeout=5)
                
                # Standard sitemaps enforce the <loc> tag for URLs
                locs = sitemap_soup.find_all('loc')
                if locs:
                    for loc in locs:
                        add_link(loc.get_text(strip=True), "")
                        # Prevent massive payload overhead by arbitrarily limiting mapped links to 100
                        if len(links_data) >= 100: 
                            break 
                    
                    if len(links_data) > 0:
                        sitemap_found = True
                        break # Halt checks as a valid sitemap adequately populated our data
            except HTTPException:
                # Silently bypass non-existent sitemaps to continue our fallback checks
                continue
            except Exception:
                continue

        # Trigger our HTML scraper fallback if all sitemap checks failed
        if not sitemap_found or len(links_data) < 2: 
            try:
                _, soup = fetch_and_parse(data.url, timeout=10)

                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href'].strip()
                    
                    # Ignore inline scripts and common client protocols
                    if href.startswith(('javascript:', 'mailto:', 'tel:')):
                        continue
                        
                    full_url = urljoin(base_url, href)
                    text = a_tag.get_text(strip=True) or "No Title"
                    
                    add_link(full_url, text)
                    if len(links_data) >= 100: 
                        break
            except Exception:
                # In the fallback, if fetching the root fails, we proceed gracefully so the fail-safe handles it
                pass

        # The ultimate fallback guarantees that the client at least receives an entry for their provided domain
        if len(links_data) == 0:
            add_link(base_url, "Homepage")

        return {
            "status": "success",
            "total_links_found": len(links_data),
            "links": links_data
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"An unexpected error occurred while mapping the website links: {str(e)}")
