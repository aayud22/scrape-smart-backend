from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from utils.scraper import fetch_and_parse

router = APIRouter()

class ScoreInput(BaseModel):
    url: str

@router.post("/score")
async def get_seo_score(data: ScoreInput):
    """
    Computes an instant SEO score out of 100 based on core technical elements 
    (Title, Meta Description, Headings, and Image Alt Attributes).
    """
    try:
        # Fetch and parse the target HTML using our centralized scraper
        response, soup = fetch_and_parse(data.url)

        # Extract SEO metadata required for scoring
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        meta_desc_tag = soup.find("meta", attrs={"name": "description"})
        meta_desc = meta_desc_tag["content"].strip() if meta_desc_tag and meta_desc_tag.get("content") else ""
        h1_tags = len(soup.find_all('h1'))
        h2_tags = len(soup.find_all('h2'))
        
        # --- IMAGE ACCESSIBILITY LOGIC (Only for scoring, not extracting URLs) ---
        images = soup.find_all('img')
        total_images = len(images)
        images_with_alt = sum(1 for img in images if img.get('alt') and img.get('alt').strip())

        # Initialize base values for the rule-based scoring algorithm
        score = 0
        feedback = []

        # Determine Title points
        if title:
            score += 20
            feedback.append("✅ Title Tag is present.")
        else:
            feedback.append("❌ Missing Title Tag (-20 pts).")

        # Determine Meta Description points
        if meta_desc:
            score += 20
            feedback.append("✅ Meta Description is present.")
        else:
            feedback.append("❌ Missing Meta Description (-20 pts).")

        # Determine H1 constraints
        if h1_tags == 1:
            score += 20
            feedback.append("✅ Perfect! Only one H1 tag found.")
        elif h1_tags > 1:
            score += 10
            feedback.append("⚠️ Multiple H1 tags found. Best practice is to use only one (-10 pts).")
        else:
            feedback.append("❌ Missing H1 Tag (-20 pts).")

        # Determine H2 points
        if h2_tags > 0:
            score += 10
            feedback.append("✅ Proper use of H2 tags for content structure.")
        else:
            feedback.append("❌ No H2 tags found. Content structure could be improved (-10 pts).")

        # Evaluate image accessibility
        if total_images == 0:
            score += 30
            feedback.append("✅ No images found, so no missing alt texts.")
        else:
            alt_percentage = images_with_alt / total_images
            image_score = int(30 * alt_percentage)
            score += image_score
            if image_score == 30:
                feedback.append(f"✅ All {total_images} images have alt text.")
            else:
                missing = total_images - images_with_alt
                feedback.append(f"❌ {missing} out of {total_images} images are missing alt text (-{30 - image_score} pts).")

        return {
            "status": "success",
            "url": data.url,
            "seo_score": score,
            "details": feedback
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"An unexpected error occurred while calculating the SEO score: {str(e)}")