from rag.chunker import chunk_code

code = """
def create_order(order):
    validate_order(order)
    save_order(order)
    return order


def cancel_order(order):
    validate_order(order)
    cancel(order)
    return order
"""

chunks = chunk_code(
    code,
    "orders/service.py",
    chunk_size=5,
    overlap=2,
)

for chunk in chunks:
    print("-----")
    print(chunk.file_path)
    print(chunk.chunk_index)
    print(chunk.content)