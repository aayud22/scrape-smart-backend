from fastapi import APIRouter, HTTPException
from ddgs import DDGS

router = APIRouter()

@router.get("/search")
async def web_search(query: str, max_results: int = 5):
    """
    Performs a live web search using DuckDuckGo without needing any API keys.
    Returns the top 'max_results' (default 5).
    """
    try:
        results = []
        # Using DDGS (DuckDuckGo Search) to fetch real-time web results
        with DDGS() as ddgs:
            # We loop through the generator to get exact number of results
            for r in ddgs.text(query, max_results=max_results):
                results.append(r)
                
        if not results:
            return {"status": "success", "query": query, "results": [], "message": "No results found."}
            
        return {
            "status": "success",
            "query": query,
            "results": results
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Search operation failed: {str(e)}")