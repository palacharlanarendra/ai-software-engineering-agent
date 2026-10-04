import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.tools.repository import (
    list_files,
    read_file,
    search_code,
)

load_dotenv()

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


TOOLS = [
    list_files,
    read_file,
    search_code,
]


def run_agent(prompt: str) -> str:

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=TOOLS,
        ),
    )

    return response.text