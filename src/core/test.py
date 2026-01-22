import re
import asyncio
import ollama
import torch
from typing import List
from langchain_core.documents import Document
from qdrant_client import QdrantClient, models
from qdrant_client.models import SparseVector
from transformers import AutoTokenizer, AutoModelForMaskedLM

# ==========================================
# 1. KONFIGURASI
# ==========================================
DENSE_MODEL = "qwen3-embedding:4b" 
RERANKER_MODEL = "xitao/bge-reranker-v2-m3:latest" 
LLM_MODEL = "gemma:7b-instruct"

SPARSE_MODEL_ID = "naver/splade-v3"
COLLECTION_NAME = "hybrid_qwen_splade_optimized"

# Inisialisasi Client
client = QdrantClient(path="./qdrant_custom_db_qwen")

# ==========================================
# 2. EMBEDDER CLASS
# ==========================================
class OllamaHybridEmbedder:
    def __init__(self):
        print(f"[*] Initializing Models... (Using {DENSE_MODEL})")
        self.sparse_tokenizer = AutoTokenizer.from_pretrained(SPARSE_MODEL_ID)
        self.sparse_model = AutoModelForMaskedLM.from_pretrained(SPARSE_MODEL_ID)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.sparse_model.to(self.device)

    def get_dense(self, text: str) -> List[float]:
        response = ollama.embeddings(model=DENSE_MODEL, prompt=text)
        return response['embedding']

    def get_sparse(self, text: str) -> SparseVector:
        inputs = self.sparse_tokenizer(text, return_tensors="pt", padding=True, truncation=True).to(self.device)
        with torch.no_grad():
            outputs = self.sparse_model(**inputs)
        
        logits = outputs.logits[0]
        relu_log = torch.log(1 + torch.relu(logits))
        max_val, _ = torch.max(relu_log * inputs["attention_mask"][0].unsqueeze(-1), dim=0)
        
        indices = torch.nonzero(max_val).squeeze().cpu().tolist()
        values = max_val[indices].cpu().tolist()
        if isinstance(indices, int): indices, values = [indices], [values]
        return SparseVector(indices=indices, values=values)

embedder = OllamaHybridEmbedder()

# ==========================================
# 3. RERANKER LOGIC (ANTI-CRASH)
# ==========================================
async def ollama_rerank(query: str, docs: List[Document], top_k: int = 3) -> List[Document]:
    if not docs: 
        return []
    
    print(f"[*] Reranking {len(docs)} documents...")
    scored_docs = []
    
    for doc in docs:
        prompt = (f"Instruksi: Berikan skor relevansi (0.0 - 1.0) antara dokumen dan pertanyaan.\n"
                  f"Pertanyaan: {query}\n"
                  f"Dokumen: {doc.page_content}\n"
                  f"Skor (Hanya angka):")
        
        try:
            # Gunakan generate dengan timeout singkat agar tidak menggantung jika runner crash
            response = ollama.generate(model=RERANKER_MODEL, prompt=prompt)
            # Regex untuk menangkap angka desimal
            match = re.search(r"(\d+\.\d+|\d+)", response['response'])
            score = float(match.group(1)) if match else 0.0
        except Exception as e:
            print(f"[!] Rerank error for a doc: {e}")
            score = 0.0
            
        doc.metadata["relevance_score"] = score
        scored_docs.append(doc)

    # Sort & Filter
    scored_docs.sort(key=lambda x: x.metadata.get("relevance_score", 0), reverse=True)
    return scored_docs[:top_k]

# ==========================================
# 4. RETRIEVAL PIPELINE
# ==========================================
async def retrieve_from_qdrant(question: str, k: int = 3) -> List[Document]:
    # 1. Deteksi Kode MK (Lebih toleran terhadap spasi/karakter)
    clean_query = question.replace("|", "") # Membersihkan typo 'ku|liah'
    codes = re.findall(r'[A-Z]{3}\s?\d{4}', clean_query)
    
    q_dense = embedder.get_dense(clean_query)
    q_sparse = embedder.get_sparse(clean_query)

    # 2. Filter logic
    search_filter = None
    if codes:
        print(f"[*] Detected Course Code: {codes[0]}")
        search_filter = models.Filter(
            should=[ # Gunakan 'should' (OR) agar jika filter gagal, vektor tetap bekerja
                models.FieldCondition(key="text", match=models.MatchText(text=codes[0]))
            ]
        )

    # 3. Hybrid Search
    try:
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(query=q_dense, using="dense_vector", limit=20),
                models.Prefetch(query=q_sparse, using="sparse_vector", limit=20),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=search_filter,
            limit=10 
        )
    except Exception as e:
        print(f"[!] Qdrant Search Error: {e}")
        return []

    initial_docs = []
    for hit in results.points:
        content = hit.payload.get('text') or hit.payload.get('content') or ""
        initial_docs.append(Document(page_content=content, metadata=hit.payload.get('metadata', {})))

    print(f"[*] Found {len(initial_docs)} raw candidates from Qdrant.")
    
    # 4. Reranking
    return await ollama_rerank(clean_query, initial_docs, top_k=k)

# ==========================================
# 5. GENERATOR CHAIN
# ==========================================
async def rrf_retriever_chain(question: str):
    docs = await retrieve_from_qdrant(question, k=3)
    
    if not docs:
        return {"answer": "Maaf, saya tidak menemukan dokumen terkait di database.", "source_documents": []}

    context = "\n".join([f"- {d.page_content}" for d in docs])

    prompt_text = f"""
    Tugas: Jawab pertanyaan berdasarkan KONTEKS di bawah.
    Aturan:
    - Gunakan pola SPOK.
    - Jangan gunakan kata ganti orang (saya, kami).
    - Jika tidak ada di konteks, katakan tidak tahu.
    - Langsung ke inti jawaban.

    KONTEKS:
    {context}

    PERTANYAAN:
    {question}

    JAWABAN:
    """

    response = ollama.generate(model=LLM_MODEL, prompt=prompt_text)
    
    return {
        "answer": response['response'].strip(),
        "source_documents": docs
    }

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    query = "Apa indikator visual yang menandakan bahwa data transaksi berhasil ditambahkan dalam aplikasi SPK-Driver?"
    
    try:
        # Jalankan async loop
        result = asyncio.run(rrf_retriever_chain(query))
        
        print("\n" + "="*30)
        print(f"QUERY: {query}")
        print(f"ANSWER: {result['answer']}")
        print("="*30 + "\n")
        
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        # PENTING: Menutup koneksi qdrant agar tidak error saat shutdown
        client.close()
        print("[*] Database connection closed.")