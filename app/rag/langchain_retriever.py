from langchain_qdrant import QdrantVectorStore
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from qdrant_client import QdrantClient

import os
from dotenv import load_dotenv

load_dotenv()


COLLECTION_NAME = "code_chunks"

qdrant_client = QdrantClient(
    url="http://localhost:6333"
)


embeddings = GoogleGenerativeAIEmbeddings(
    model="models/gemini-embedding-001",
    google_api_key=os.getenv("GEMINI_API_KEY"),
)


vector_store = QdrantVectorStore(
    client=qdrant_client,
    collection_name=COLLECTION_NAME,
    embedding=embeddings,
)


retriever = vector_store.as_retriever(
    search_kwargs={
        "k": 5
    }
)