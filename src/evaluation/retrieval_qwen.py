import torch
import re
import asyncio
import torch.nn.functional as F
from typing import List, Optional
from langchain_core.documents import Document
from transformers import AutoModel, AutoTokenizer, AutoModelForMaskedLM, BitsAndBytesConfig
from qdrant_client import QdrantClient, models
from qdrant_client.models import SparseVector
from sentence_transformers import CrossEncoder

# ==========================================
# 1. KONFIGURASI & GLOBAL VARIABLES
# ==========================================
DENSE_MODEL_ID = "Qwen/Qwen3-Embedding-4B"
SPARSE_MODEL_ID = "naver/splade-v3"
RERANKER_ID = "BAAI/bge-reranker-v2-m3"
#RERANKER_ID = "BAAI/bge-reranker-large"  # Alternatif Reranker Lebih Kuat
COLLECTION_NAME = "hybrid_qwen_splade_optimized"

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Running on: {device}")

# Konfigurasi Kuantisasi 4-bit untuk menghemat VRAM
bnb_config = None
if device == "cuda":
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16
    )

# Inisialisasi Qdrant Lokal
client = QdrantClient(path="./qdrant_custom_db_qwen")

# ==========================================
# 2. UTILITY FUNCTIONS
# ==========================================

def extract_course_codes(query: str) -> List[str]:
    """Mendeteksi format 3 Huruf + Spasi Opsional + 4 Angka."""
    pattern = r'\b[A-Z]{3}\s?\d{4}\b'
    return re.findall(pattern, query)

def last_token_pool(last_hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Pooling khusus untuk model Qwen/GTE."""
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths]

# ==========================================
# 3. RERANKER (CROSS-ENCODER)
# ==========================================
_cross_encoder_model = None

def get_cross_encoder():
    global _cross_encoder_model
    if _cross_encoder_model is None:
        print(f"Loading Reranker: {RERANKER_ID}")
        _cross_encoder_model = CrossEncoder(RERANKER_ID)
    return _cross_encoder_model

async def cross_rerank(query: str, docs: List[Document], top_k: int = 3) -> List[Document]:
    if not docs: return []
    model = get_cross_encoder()
    pairs = [(query, d.page_content) for d in docs]
    
    # 1. Gunakan context manager untuk mencegah penyimpanan gradient
    with torch.no_grad():
        scores = model.predict(
            pairs, 
            batch_size=32, # Atur batch size agar tidak meledak di VRAM
            show_progress_bar=False,
            convert_to_tensor=True # Mempercepat proses jika model ada di GPU
        )
        
        # Pindahkan skor ke CPU dan ubah ke list segera
        if torch.is_tensor(scores):
            scores = scores.cpu().numpy().tolist()

    # 2. Gabungkan dokumen dengan skornya
    combined = sorted(list(zip(docs, scores)), key=lambda x: x[1], reverse=True)
    
    final_docs = []
    for doc, score in combined[:top_k]:
        doc.metadata["relevance_score"] = float(score)
        final_docs.append(doc)

    # 3. BERSIHKAN VRAM DARI TENSOR SEMENTARA
    if torch.cuda.is_available():
        # Menghapus referensi variabel yang memegang tensor besar (jika ada)
        del scores
        # Memaksa PyTorch melepas reserved memory kembali ke GPU
        torch.cuda.empty_cache()

    return final_docs

# ==========================================
# 4. EMBEDDER CLASS (DENSE & SPARSE)
# ==========================================

class RrfEmbeder:
    def __init__(self):
        print("Loading Dense Model (Qwen 4-bit)...")
        self.dense_tokenizer = AutoTokenizer.from_pretrained(DENSE_MODEL_ID, trust_remote_code=True)
        self.dense_model = AutoModel.from_pretrained(
            DENSE_MODEL_ID, trust_remote_code=True,
            quantization_config=bnb_config,
            device_map="auto" if device == "cuda" else None,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32
        )
        
        print("Loading Sparse Model (Splade v3)...")
        self.sparse_tokenizer = AutoTokenizer.from_pretrained(SPARSE_MODEL_ID)
        self.sparse_model = AutoModelForMaskedLM.from_pretrained(SPARSE_MODEL_ID)
        self.sparse_model.to(device)

    def get_dense_vector(self, text: str):
        inputs = self.dense_tokenizer(text, max_length=8192, padding=True, truncation=True, return_tensors='pt').to(self.dense_model.device)
        with torch.no_grad():
            outputs = self.dense_model(**inputs)
            embeddings = last_token_pool(outputs.last_hidden_state, inputs['attention_mask'])
            embeddings = F.normalize(embeddings, p=2, dim=1)
        return embeddings[0].cpu().tolist()

    def get_sparse_vector(self, text: str):
        inputs = self.sparse_tokenizer(text, return_tensors="pt", padding=True, truncation=True).to(self.sparse_model.device)
        with torch.no_grad():
            outputs = self.sparse_model(**inputs)
        logits = outputs.logits[0]
        relu_log = torch.log(1 + torch.relu(logits))
        max_val, _ = torch.max(relu_log * inputs["attention_mask"][0].unsqueeze(-1), dim=0)
        
        indices = torch.nonzero(max_val).squeeze().cpu().tolist()
        values = max_val[indices].cpu().tolist()
        if isinstance(indices, int): indices, values = [indices], [values]
        return SparseVector(indices=indices, values=values)

# Inisialisasi Model
embedding_model = RrfEmbeder()

# ==========================================
# 5. CORE RETRIEVAL PIPELINE
# ==========================================

async def retrieve_from_qdrant(question: str, k: int = 3, thinking=True) -> List[Document]:
    """
    Fungsi retrieval utama dengan logika khusus untuk Kode Mata Kuliah.
    """
    codes_found = extract_course_codes(question)
    
    try:
        # Generate Embeddings
        q_dense = embedding_model.get_dense_vector(question)
        q_sparse = embedding_model.get_sparse_vector(question)

        # --- SKENARIO 1: KODE MATA KULIAH TERDETEKSI ---
        if codes_found:
            print(f"[INFO] Kode MK Terdeteksi: {codes_found[0]}. Menjalankan 1 Exact + 2 Hybrid.")
            
            # A. Exact Match via Payload Filter (Pasti Ketemu)
            res_exact = client.query_points(
                collection_name=COLLECTION_NAME,
                query=q_dense, 
                using="dense_vector", # Memperbaiki error 'vector not found'
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="text", # Berdasarkan hasil print kamu
                            match=models.MatchText(text=codes_found[0])
                        )
                    ]
                ),
                limit=1
            )
            
            # B. Hybrid Search RRF (Cari Konteks Tambahan)
            res_hybrid = client.query_points(
                collection_name=COLLECTION_NAME,
                prefetch=[
                    models.Prefetch(query=q_dense, using="dense_vector", limit=15),
                    models.Prefetch(query=q_sparse, using="sparse_vector", limit=15),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=2
            )
            
            # Gabungkan Hasil & Hapus Duplikat
            combined_hits = res_exact.points + res_hybrid.points
            seen_ids = set()
            final_docs = []
            for hit in combined_hits:
                if hit.id not in seen_ids:
                    final_docs.append(Document(
                        page_content=hit.payload.get('text', ''),
                        metadata=hit.payload.get('metadata', {})
                    ))
                    seen_ids.add(hit.id)
            
            return final_docs[:3]

        # --- SKENARIO 2: PENCARIAN UMUM (TANPA KODE MK) ---
        else:
            # Jika thinking=True (Reranker aktif), ambil lebih banyak kandidat
            search_limit = 20 if thinking else k
            
            res_normal = client.query_points(
                collection_name=COLLECTION_NAME,
                prefetch=[
                    models.Prefetch(query=q_dense, using="dense_vector", limit=20),
                    models.Prefetch(query=q_sparse, using="sparse_vector", limit=20),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=search_limit
            )
            
            initial_docs = [
                Document(page_content=hit.payload.get('text', ''), metadata=hit.payload.get('metadata', {}))
                for hit in res_normal.points
            ]
            
            if thinking:
                print(f"[INFO] Reranking {len(initial_docs)} dokumen...")
                return await cross_rerank(query=question, docs=initial_docs, top_k=k)
            
            return initial_docs[:k]

    except Exception as e:
        print(f"Error pada Retrieval: {e}")
        return []
