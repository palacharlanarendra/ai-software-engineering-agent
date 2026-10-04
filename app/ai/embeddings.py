import os

from dotenv import load_dotenv
from google import genai

load_dotenv()


client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

def create_embedding(text: str) -> list[float]:

    response = client.models._embed_content(
        model="gemini-embedding-001",
        contents=text,
    )

    return response.embeddings[0].values