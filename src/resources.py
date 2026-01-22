from src.config.firebase_config import init_firebase
from qdrant_client import QdrantClient
from src.core.llm import init_llm, evaluator_llm, init_llm_gemma, init_llm_gemma3_12b

#Inisialisasi komponen - komponen yang akan dipakai dalam system
db = init_firebase()
llm = init_llm()
llm_gemma = init_llm_gemma()
llm_gemma3_12b = init_llm_gemma3_12b()
evaluator = evaluator_llm()

qdrant_client = QdrantClient(
    host="localhost",
    port=6334,
    prefer_grpc=True
)
