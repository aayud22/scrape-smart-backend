import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # must run before the routers read environment variables

from api.chat import router as chat_router  # noqa: E402
from api.map import router as map_router  # noqa: E402
from api.score import router as score_router  # noqa: E402
from api.scrape import router as scrape_router  # noqa: E402

logging.basicConfig(level=logging.INFO)

DEFAULT_ORIGINS = [
    "http://localhost:3000",
    "https://scrape-smart-ai.vercel.app",
    "https://scrape-smart-ai-chatbot.vercel.app",
]

# Comma-separated list in CORS_ORIGINS overrides the defaults.
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()] or DEFAULT_ORIGINS

app = FastAPI(title="ScrapeSmart API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

app.include_router(chat_router)
app.include_router(score_router)
app.include_router(map_router)
app.include_router(scrape_router)


@app.get("/health")
def health():
    """Lightweight check for uptime monitors; does not touch any external service."""
    return {"status": "ok"}
