from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

from app.rag.langchain_retriever import retriever

import os
from dotenv import load_dotenv

load_dotenv()


llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GEMINI_API_KEY"),
    temperature=0,
)


prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are an AI software engineering assistant.

Answer the user's question using the provided
repository context.

Do not invent repository details.

If the context does not contain enough information,
say that you do not have enough repository context.

Always mention relevant file paths when possible.

Repository context:

{context}
""",
        ),
        (
            "human",
            "{question}",
        ),
    ]
)

def format_docs(docs):
    return "\n\n".join(
        f"""
File: {doc.metadata.get("file_path")}

{doc.page_content}
"""
        for doc in docs
    )


def answer_question(question: str):

    docs = retriever.invoke(question)

    context = format_docs(docs)

    response = prompt.invoke(
        {
            "context": context,
            "question": question,
        }
    )

    answer = llm.invoke(response)

    return answer.content