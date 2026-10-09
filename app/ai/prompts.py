from langchain_core.prompts import ChatPromptTemplate


code_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are an AI software engineering assistant.

Answer questions about the repository accurately.
Do not invent repository details.
""",
        ),
        (
            "human",
            "{question}",
        ),
    ]
)