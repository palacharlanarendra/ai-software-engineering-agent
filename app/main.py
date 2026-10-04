from fastapi import FastAPI
from pydantic import BaseModel
from app.ai.agent import run_agent
from app.tools.repository import search_code
from app.ai.embeddings import create_embedding
app = FastAPI(title="AI Software Engineering Agent")
# Fast API

class ChatRequest(BaseModel):
    message: str

@app.get("/")
def health_check():
    return {
        "status": "ok",
        "service": "AI Software Engineering Agent"
    }

@app.post("/chat")
def chat(request: ChatRequest):
    response = run_agent(request.message)
    return {
        "response": response
    }