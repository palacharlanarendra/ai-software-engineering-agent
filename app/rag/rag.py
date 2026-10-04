import os
from dotenv import load_dotenv
load_dotenv()
from google import genai

from app.rag.retriever import search_code_semantic

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


def answer_with_rag(
    question: str,
    limit: int = 5,
) -> str:

    # 1. Retrieve relevant code
    results = search_code_semantic(
        question,
        limit=limit,
    )

    # 2. Build context
    context_parts = []

    for i, result in enumerate(results, start=1):

        payload = result.payload

        context_parts.append(
            f"""
--- Context {i} ---
File: {payload["file_path"]}
Chunk: {payload["chunk_index"]}

{payload["content"]}
"""
        )

    context = "\n".join(context_parts)

    # 3. Give retrieved context to the LLM
    prompt = f"""
You are an AI software engineering assistant.

Answer the user's question using ONLY the repository
context provided below.

Do not invent files, functions, classes, or behavior.

If the provided context is insufficient, clearly say:
"I don't have enough repository context to answer that."

Mention relevant file paths when possible.

User question:
{question}

Repository context:
{context}
"""

    # 4. Generate grounded answer
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )

    return response.text