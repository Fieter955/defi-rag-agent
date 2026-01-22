from firebase_config import init_firebase
from llm import init_llm, evaluator_llm, init_llm_gemma, init_llm_gemma3_12b

#Inisialisasi komponen - komponen yang akan dipakai dalam system
db = init_firebase()
llm = init_llm()
llm_gemma = init_llm_gemma()
llm_gemma3_12b = init_llm_gemma3_12b()
evaluator = evaluator_llm()

es_client = None
qdrant_client = None