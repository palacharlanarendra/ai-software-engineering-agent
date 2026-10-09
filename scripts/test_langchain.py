from app.ai.langchain_llm import llm


response = llm.invoke(
    "Explain what RAG means in one sentence."
)

print(response.content)