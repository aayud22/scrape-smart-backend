from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from utils.scraper import fetch_and_parse
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

# Initialize the generative AI model to process text and answer questions
# Note: Ensure load_dotenv() is called in the main application entry point
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")

class ChatInput(BaseModel):
    url: str
    question: str

@router.post("/chat")
async def chat_with_website(data: ChatInput):
    """
    Scrapes a webpage, extracts its content along with technical SEO data, 
    and uses an LLM to answer a user's question based on the provided context.
    """
    try:
        # Fetch and parse the target HTML using our centralized scraper utility
        response, soup = fetch_and_parse(data.url)

        # Extract precise SEO metadata for technical audits
        title = soup.title.string.strip() if soup.title and soup.title.string else "Missing Title"
        
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_desc = meta_desc_tag["content"].strip() if meta_desc_tag and meta_desc_tag.get("content") else "Missing Meta Description"
        
        h1_tags = [h1.get_text(strip=True) for h1 in soup.find_all('h1')]
        h2_count = len(soup.find_all('h2'))
        
        images = soup.find_all('img')
        total_images = len(images)
        images_with_alt = sum(1 for img in images if img.get('alt') and img.get('alt').strip())

        # Extract all visible text to provide content context to the LLM (capped to save tokens)
        text_content = soup.get_text(separator=' ', strip=True)[:5000]

        # Construct a rigorous prompt instructing the LLM on handling both SEO and general queries
        prompt = f"""
        You are ScrapeSmart AI, a highly technical SEO and Web Analyst.
        
        Analyze the following exact SEO metadata and content scraped from the website ({data.url}):
        
        --- TECHNICAL SEO DATA ---
        - Title Tag: {title}
        - Meta Description: {meta_desc}
        - H1 Tags: {h1_tags} (Count: {len(h1_tags)})
        - H2 Tags Count: {h2_count}
        - Image SEO: {total_images} total images, {images_with_alt} images have 'alt' text.
        
        --- PAGE CONTENT (Preview) ---
        {text_content}...
        
        User Question: "{data.question}"
        
        Instructions:
        1. If the user asks about SEO (e.g., "Is this SEO friendly?"), DO NOT look for the word "SEO" in the content. 
        2. Evaluate the actual "TECHNICAL SEO DATA" provided above. 
        3. Point out strengths (e.g., proper H1, good title length) and weaknesses (e.g., missing meta descriptions, missing alt tags).
        4. Give a definitive, expert answer using professional formatting (bullet points, bold text).
        5. If the question is NOT about SEO, just answer it normally using the Page Content.
        """
        
        # Invoke the AI to generate the response based on our explicit instructions
        ai_response = llm.invoke(prompt)
        
        return {
            "status": "success",
            "bot_reply": ai_response.content
        }
        
    except HTTPException:
        # Re-raise standard HTTPExceptions initiated by our utility to preserve status code and detail
        raise
    except Exception as e:
        # Catch unexpected logical mapping failures
        raise HTTPException(status_code=400, detail=f"An unexpected error occurred during chat processing: {str(e)}")
