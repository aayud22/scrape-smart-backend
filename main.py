from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Import our modularized routers
from api.chat import router as chat_router
from api.score import router as score_router
from api.map import router as map_router
from api.scrape import router as scrape_router
from api.search import router as search_router

# Load environment variables to ensure secure access to API keys
load_dotenv()

# Initialize FastAPI application
app = FastAPI(title="ScrapeSmart API")

# Configure CORS middleware to permit requests from the frontend applications
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5000", 
        "https://scrape-smart-ai-chatbot.vercel.app",
        "https://scrape-smart-ai.vercel.app" 
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the modularized endpoints
app.include_router(chat_router)
app.include_router(score_router)
app.include_router(map_router)
app.include_router(scrape_router)
app.include_router(search_router)

# The server is now cleanly modularized for enterprise scalability setup!
