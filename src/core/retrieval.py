import torch
import re
import asyncio
import hashlib
from typing import List, Optional, Dict
from langchain_core.documents import Document
from transformers import AutoModel, AutoTokenizer, AutoModelForMaskedLM, BitsAndBytesConfig
from qdrant_client import QdrantClient, models
from qdrant_client.models import SparseVector
from sentence_transformers import CrossEncoder
from langchain_core.prompts import PromptTemplate
from src import resources
import torch.nn.functional as F


#FUNGSI UNTUK RETRIEVAL DENGAN RRF DAN PARALLEL QUERY EXPANSION
async def rrf_retriever_chain(question: str, list_of_queries: List[str] = None, thinking: bool = True) -> Dict:
    """
    Custom retriever chain dengan parallel query expansion dan RRF.
    FIXED: Deduplication bug yang menghapus terlalu banyak dokumen.
    """
    print(f"[RETRIEVAL] Starting retrieval for question: {question[:50]}...")
    
    if not list_of_queries:
        list_of_queries = [question]
    
    print(f"[RETRIEVAL] Using {len(list_of_queries)} query variations")
    
    # 1. Parallel retrieval untuk semua query
    retrieval_tasks = []
    for query in list_of_queries:
        task = retrieve_from_qdrant(
            query, 
            k=3, 
            thinking=thinking
        )
        retrieval_tasks.append(task)
    
    # Jalankan semua retrieval secara parallel
    try:
        all_retrieved_results = await asyncio.gather(*retrieval_tasks, return_exceptions=True)
        print(f"berikut adalah hasil dari all_retrieved_results: {all_retrieved_results}")
    except Exception as e:
        print(f"[ERROR] Parallel retrieval failed: {e}")
        all_retrieved_results = []
        for query in list_of_queries:
            try:
                docs = await retrieve_from_qdrant(query, k=3, thinking=thinking)
                all_retrieved_results.append(docs)
            except Exception as e2:
                print(f"[ERROR] Failed to retrieve for query '{query}': {e2}")
                all_retrieved_results.append([])
    
    # 2. Gabungkan semua dokumen dengan deduplikasi yang TIDAK terlalu agresif
    all_docs = []
    seen_content_hashes = set()
    
    for i, docs in enumerate(all_retrieved_results):
        if isinstance(docs, Exception):
            print(f"[WARNING] Query {i} returned error: {docs}")
            continue
            
        print(f"[RETRIEVAL] Query '{list_of_queries[i][:50]}...' → {len(docs)} raw docs")

        for doc in docs:
            # Gunakan hash seluruh konten untuk deduplikasi yang akurat
            full_content_hash = hashlib.md5(doc.metadata["id"].encode()).hexdigest()
            
            if full_content_hash not in seen_content_hashes:
                seen_content_hashes.add(full_content_hash)
                all_docs.append(doc)
            else:
                # Hanya log jika benar-benar duplikat exact
                print(f"[DEDUP] Skipping exact duplicate: {doc.page_content[:80]}...")
    
    print(f"[RETRIEVAL] After dedup: {len(all_docs)} unique documents (from {sum(len(d) if not isinstance(d, Exception) else 0 for d in all_retrieved_results)} total)")
    
    
    # 3. Jika thinking aktif, lakukan reranking global
    if thinking and len(all_docs) > 0:
        print(f"[RETRIEVAL] Performing global reranking on {len(all_docs)} documents...")
        top_docs = await cross_rerank(query=question, docs=all_docs, top_k=3)
    elif len(all_docs) > 0:
        # Gunakan RRF scoring untuk non-thinking mode
        print(f"[RETRIEVAL] Using RRF scoring for {len(all_docs)} documents...")
        
        # Hitung RRF scores
        rrf_scores = {}
        k = 60
        
        for query_idx, docs in enumerate(all_retrieved_results):
            if isinstance(docs, Exception):
                continue
                
            for rank, doc in enumerate(docs):
                full_content_hash = hashlib.md5(doc.page_content.encode()).hexdigest()
                
                if full_content_hash not in rrf_scores:
                    rrf_scores[full_content_hash] = {"doc": doc, "score": 0}
                rrf_scores[full_content_hash]["score"] += 1 / (k + rank + 1)
        
        # Sort dan ambil top 3
        ranked_docs = sorted(rrf_scores.values(), 
                           key=lambda x: x["score"], 
                           reverse=True)
        top_docs = [item["doc"] for item in ranked_docs[:3]]
        
        # Tambahkan score ke metadata
        for i, item in enumerate(ranked_docs[:3]):
            if i < len(top_docs):
                top_docs[i].metadata["relevance_score"] = item["score"]
    else:
        top_docs = []
        print("[RETRIEVAL] No documents found after deduplication")
    
        
    return {
        "source_documents": top_docs,
        "query_expansions": list_of_queries,
        "unique_docs_found": len(all_docs),
        "total_raw_docs": sum(len(d) if not isinstance(d, Exception) else 0 for d in all_retrieved_results)
    }

# Model constants
DENSE_MODEL_ID = "Qwen/Qwen3-Embedding-4B"
SPARSE_MODEL_ID = "naver/splade-v3"
RERANKER_ID = "BAAI/bge-reranker-v2-m3"
COLLECTION_NAME = "hybrid_qwen_splade_optimized"

device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"[MODEL] Running on: {device}")

# Konfigurasi kuantisasi
bnb_config = None
if device == "cuda":
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16
    )

client = resources.qdrant_client

#fungsi bantu untuk ekstrak kode mata kuliah
def extract_course_codes(query: str) -> List[str]:
    """Ekstrak kode mata kuliah dari query."""
    pattern = r'\b[A-Z]{3}\s?\d{4}\b'
    matches = re.findall(pattern, query)
    return [m.replace(" ", "") for m in matches if not m.startswith("KIP")]

#fungsi bantu untuk pooling token terakhir
def last_token_pool(last_hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Pooling khusus untuk model Qwen/GTE."""
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    return last_hidden_states[torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths]

_cross_encoder_model = None


#funsi bantu untuk mendapatkan cross encoder
def get_cross_encoder():
    """Lazy loading untuk cross encoder."""
    global _cross_encoder_model
    if _cross_encoder_model is None:
        print(f"[MODEL] Loading Reranker: {RERANKER_ID}")
        _cross_encoder_model = CrossEncoder(RERANKER_ID)
    return _cross_encoder_model


#fungsi bantu untuk reranking silang
async def cross_rerank(query: str, docs: List[Document], top_k: int = 3) -> List[Document]:
    """Rerank dokumen menggunakan cross encoder."""
    if not docs:
        return []
    
    print(f"[RERANK] Reranking {len(docs)} documents...")
    
    model = get_cross_encoder()
    pairs = [(query, d.page_content) for d in docs]
    
    try:
        with torch.no_grad():
            scores = model.predict(
                pairs,
                batch_size=32,
                show_progress_bar=False,
                convert_to_tensor=True
            )
            
            if torch.is_tensor(scores):
                scores = scores.cpu().numpy().tolist()
        
        # Gabungkan dokumen dengan scores
        scored_docs = list(zip(docs, scores))
        scored_docs.sort(key=lambda x: x[1], reverse=True)
        
        # Ambil top_k dan tambahkan score ke metadata
        final_docs = []
        for doc, score in scored_docs[:top_k]:
            doc.metadata["relevance_score"] = float(score)
            final_docs.append(doc)
        
        print(f"[RERANK] Top score: {scored_docs[0][1]:.4f}" if scored_docs else "[RERANK] No scores")
        
        # Cleanup memory
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        return final_docs
        
    except Exception as e:
        print(f"[ERROR] Cross reranking failed: {e}")
        return docs[:top_k]

#class untuk embedder RRF yang menggabungkan dense dan sparse
class RrfEmbeder:
    """Embedder untuk dense dan sparse vectors."""
    def __init__(self):
        print("[MODEL] Loading Dense Model (Qwen 4-bit)...")
        self.dense_tokenizer = AutoTokenizer.from_pretrained(DENSE_MODEL_ID, trust_remote_code=True)
        self.dense_model = AutoModel.from_pretrained(
            DENSE_MODEL_ID,
            trust_remote_code=True,
            quantization_config=bnb_config,
            device_map="auto" if device == "cuda" else None,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32
        )
        
        print("[MODEL] Loading Sparse Model (Splade v3)...")
        self.sparse_tokenizer = AutoTokenizer.from_pretrained(SPARSE_MODEL_ID)
        self.sparse_model = AutoModelForMaskedLM.from_pretrained(SPARSE_MODEL_ID)
        self.sparse_model.to(device)
        self.sparse_model.eval()
    
    def get_dense_vector(self, text: str) -> List[float]:
        """Generate dense embedding."""
        inputs = self.dense_tokenizer(
            text,
            max_length=8192,
            padding=True,
            truncation=True,
            return_tensors='pt'
        ).to(self.dense_model.device)
        
        with torch.no_grad():
            outputs = self.dense_model(**inputs)
            embeddings = last_token_pool(outputs.last_hidden_state, inputs['attention_mask'])
            embeddings = F.normalize(embeddings, p=2, dim=1)
        
        return embeddings[0].cpu().tolist()
    
    def get_sparse_vector(self, text: str) -> SparseVector:
        """Generate sparse embedding."""
        inputs = self.sparse_tokenizer(
            text,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512
        ).to(self.sparse_model.device)
        
        with torch.no_grad():
            outputs = self.sparse_model(**inputs)
        
        logits = outputs.logits[0]
        relu_log = torch.log(1 + torch.relu(logits))
        
        # Apply attention mask
        attention_mask = inputs["attention_mask"][0].unsqueeze(-1)
        masked_log = relu_log * attention_mask
        
        max_val, _ = torch.max(masked_log, dim=0)
        
        # Ambil indices dan values non-zero
        indices = torch.nonzero(max_val).squeeze()
        values = max_val[indices]
        
        if indices.dim() == 0:
            indices = [indices.item()]
            values = [values.item()]
        else:
            indices = indices.cpu().tolist()
            values = values.cpu().tolist()
        
        return SparseVector(indices=indices, values=values)

embedding_model = RrfEmbeder()



#fungsi retrieval utama dengan logika khusus untuk Kode Mata Kuliah
async def retrieve_from_qdrant(
    question: str,
    k: int = 3,
    thinking: bool = False
) -> List[Document]:
    """
    Fungsi retrieval utama dengan logika khusus untuk Kode Mata Kuliah.
    """
    codes_found = extract_course_codes(question)
    
    try:
        q_dense = embedding_model.get_dense_vector(question)
        q_sparse = embedding_model.get_sparse_vector(question)
        
        if codes_found:
            print(f"[RETRIEVAL] Course code detected: {codes_found[0]}. Running 1 exact + 2 hybrid.")
            
            # Exact match untuk kode MK
            res_exact = client.query_points(
                collection_name=COLLECTION_NAME,
                query=q_dense,
                using="dense_vector",
                query_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="text",
                            match=models.MatchText(text=codes_found[0])
                        )
                    ]
                ),
                limit=1
            )
            
            # Hybrid search untuk konteks
            res_hybrid = client.query_points(
                collection_name=COLLECTION_NAME,
                prefetch=[
                    models.Prefetch(query=q_dense, using="dense_vector", limit=15),
                    models.Prefetch(query=q_sparse, using="sparse_vector", limit=15),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=2
            )
            
            # Gabungkan hasil
            combined_hits = res_exact.points + res_hybrid.points
            seen_ids = set()
            final_docs = []
            
            for hit in combined_hits:
                if hit.id not in seen_ids:
                    final_docs.append(Document(
                        page_content=hit.payload.get('preprocessed_content', ''),
                        metadata=hit.payload.get('metadata', {})
                    ))
                    seen_ids.add(hit.id)
            
            return final_docs[:3]
            
        else:
            # Tentukan limit berdasarkan mode
            if thinking:
                k = 10
            else:
                k = k
            
            print(f"[RETRIEVAL] Searching Qdrant with limit {k}...")
            
            # Hybrid search normal
            res_normal = client.query_points(
                collection_name=COLLECTION_NAME,
                prefetch=[
                    models.Prefetch(query=q_dense, using="dense_vector", limit=20),
                    models.Prefetch(query=q_sparse, using="sparse_vector", limit=20),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=k
            )
            
            # Konversi ke Document
            initial_docs = [
                Document(
                    page_content=hit.payload.get('preprocessed_content', ''),
                    metadata=hit.payload.get('metadata', {})
                )
                for hit in res_normal.points
            ]
            
            print(f"[RETRIEVAL] Qdrant returned {len(initial_docs)} documents")
            
            return initial_docs[:k]
            
    except Exception as e:
        print(f"[ERROR] Retrieval failed: {e}")
        import traceback
        traceback.print_exc()
        return []

