from app.ai.prompts import code_prompt

messages = code_prompt.invoke(
    {
        "question": "Where is the FastAPI app created?"
    }
)

print(messages)