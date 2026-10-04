from app.rag.rag import answer_with_rag


question = "How does the chunking function split code into chunks?"

answer = answer_with_rag(question)

print("\nANSWER:\n")
print(answer)