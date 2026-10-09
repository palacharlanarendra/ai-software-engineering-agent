from app.rag.langchain_rag import answer_question


question = "How does the chunking function split code?"

answer = answer_question(question)

print("\nANSWER:\n")
print(answer)