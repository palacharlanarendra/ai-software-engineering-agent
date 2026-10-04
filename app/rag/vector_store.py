from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


client = QdrantClient(
    url="http://localhost:6333"
)


COLLECTION_NAME = "code_chunks"

client.create_collection(
    collection_name=COLLECTION_NAME,
    vectors_config=VectorParams(
        size=3072,
        distance=Distance.COSINE,
    ),
)