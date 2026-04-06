from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_community.document_loaders import WebBaseLoader
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
import os

# Load env
load_dotenv()

# Initialize the AI Model (Using Gemini 2.5 Flash for speed)
llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")

# Initialize the FastAPI application with the project name
app = FastAPI(title="ScrapeSmart API")

# Add CORS middleware to allow requests from the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5000"], # Frontend ka address
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define the Input Data Structure (Requires URL and User Question)
class ChatInput(BaseModel):
    url: str
    question: str

# Create the POST Endpoint for chat
@app.post("/chat")
async def chat_with_website(data: ChatInput):
    try:
        # Step A: Load and extract text from the provided URL
        loader = WebBaseLoader(data.url)
        documents = loader.load()
        scraped_text = documents[0].page_content
        
        # Step B: Construct the prompt for the AI (Prompt Engineering)
        prompt = f"""
        Your name is ScrapeSmart AI. Carefully read the website data provided below:
        
        --- DATA START ---
        {scraped_text}
        --- DATA END ---
        
        Based on this data, answer the user's question: "{data.question}"
        
        Rule: If the answer is not found in the data above, politely state that "Information is not available on the website." Do not guess or make up answers.
        """
        
        # Step C: Send the prompt to Gemini and get the response
        response = llm.invoke(prompt)
        
        # Step D: Send the generated answer back to the frontend
        return {
            "status": "success",
            "bot_reply": response.content
        }
        
    except Exception as e:
        # Handle exceptions (e.g., invalid URL, network issues)
        raise HTTPException(status_code=400, detail=str(e))