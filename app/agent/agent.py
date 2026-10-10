# import os

# from dotenv import load_dotenv

# from langchain_google_genai import ChatGoogleGenerativeAI

# from app.agent.tools import (
#     list_repository_files,
#     read_repository_file,
#     search_repository,
#     semantic_repository_search,
# )

# load_dotenv()


# llm = ChatGoogleGenerativeAI(
#     model="gemini-2.5-flash",
#     google_api_key=os.getenv("GEMINI_API_KEY"),
#     temperature=0,
# )


# tools = [
#     list_repository_files,
#     read_repository_file,
#     search_repository,
#     semantic_repository_search,
# ]


# llm_with_tools = llm.bind_tools(tools)


# response = llm_with_tools.invoke(
#     "Where is the chunking function implemented?"
# )

# print(response)

# agent loop below - langchain

import os
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent
from app.ai.llm import llm

from app.agent.tools import (
    list_repository_files,
    read_repository_file,
    search_repository,
    semantic_repository_search,
    check_python_syntax,
    propose_python_syntax_fix,
    apply_proposed_python_fix
)

load_dotenv()

tools = [
    list_repository_files,
    read_repository_file,
    search_repository,
    semantic_repository_search,
    check_python_syntax,
    propose_python_syntax_fix
]

llm_with_tools = llm.bind_tools(tools)


tool_map = {
    tool.name: tool
    for tool in tools
}

# manual agent loop

# def run_agent(question: str):

#     messages = [
#         HumanMessage(content=question)
#     ]

#     for _ in range(5):

#         response = llm_with_tools.invoke(messages)

#         messages.append(response)

#         # No tool call = final answer
#         if not response.tool_calls:
#             return response.content

#         # Execute requested tools
#         for tool_call in response.tool_calls:

#             tool_name = tool_call["name"]
#             tool_args = tool_call["args"]
#             tool_call_id = tool_call["id"]

#             tool = tool_map[tool_name]

#             result = tool.invoke(tool_args)

#             messages.append(
#                 ToolMessage(
#                     content=str(result),
#                     tool_call_id=tool_call_id,
#                 )
#             )

#     return "Agent reached the maximum number of iterations."

agent = create_react_agent(
    model=llm,
    tools=tools,
)


def run_agent(question: str) -> str:
    result = agent.invoke({
        "messages": [
            {"role": "user", "content": question}
        ]
    })

    return result["messages"][-1].content

if __name__ == "__main__":

    answer = run_agent(
        "Where is the chunking function implemented?"
    )

    print("\nFINAL ANSWER:\n")
    print(answer)