
class RrfEmbederE5:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"🚀 Initializing Embedder on: {self.device}")
        
        # --- DENSE: E5-Base ---
        self.dense_id = "intfloat/multilingual-e5-base"
        print(f"⏳ Loading Dense: {self.dense_id} (No Quantization)...")
        self.dense_tokenizer = AutoTokenizer.from_pretrained(self.dense_id)
        self.dense_model = AutoModel.from_pretrained(self.dense_id).to(self.device)

        # --- SPARSE: Splade v3 ---
        self.sparse_id = "naver/splade-v3"
        print(f"⏳ Loading Sparse: {self.sparse_id}...")
        self.sparse_tokenizer = AutoTokenizer.from_pretrained(self.sparse_id)
        self.sparse_model = AutoModelForMaskedLM.from_pretrained(self.sparse_id).to(self.device)

    def _average_pool(self, last_hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        """Helper khusus E5 (Average Pooling)"""
        last_hidden = last_hidden_states.masked_fill(~attention_mask[..., None].bool(), 0.0)
        return last_hidden.sum(dim=1) / attention_mask.sum(dim=1)[..., None]

    def get_dense_vector(self, text: str):
        """
        Generate dense vector menggunakan E5-Base.
        WAJIB: Menambahkan prefix 'query: ' untuk retrieval tasks.
        """
        # Prefix wajib untuk E5 side query
        text_formatted = f"query: {text}"
        
        inputs = self.dense_tokenizer(
            text_formatted, 
            max_length=512, 
            padding=True, 
            truncation=True, 
            return_tensors='pt'
        ).to(self.device)

        with torch.no_grad():
            outputs = self.dense_model(**inputs)
            embeddings = self._average_pool(outputs.last_hidden_state, inputs['attention_mask'])
            embeddings = F.normalize(embeddings, p=2, dim=1)
            
        return embeddings[0].cpu().tolist()

    def get_sparse_vector(self, text: str):
        """Generate sparse vector menggunakan SPLADE v3"""
        inputs = self.sparse_tokenizer(
            text, 
            return_tensors="pt", 
            padding=True, 
            truncation=True
        ).to(self.device)

        with torch.no_grad():
            outputs = self.sparse_model(**inputs)
        
        logits = outputs.logits[0]
        attention_mask = inputs["attention_mask"][0].unsqueeze(-1)
        
        # SPLADE Logic: log(1 + ReLU(logits))
        relu_log = torch.log(1 + torch.relu(logits))
        weighted_log = relu_log * attention_mask
        max_val, _ = torch.max(weighted_log, dim=0)
        
        # Ekstrak index dan value yang tidak nol
        indices = torch.nonzero(max_val).squeeze().cpu().tolist()
        values = max_val[indices].cpu().tolist()
        
        if isinstance(indices, int):
            indices = [indices]
            values = [values]
            
        return SparseVector(indices=indices, values=values)

# ==========================================
# 2. INISIALISASI
# ==========================================

# 1. Init Model
embedding_model_e5 = RrfEmbederE5()

# 2. Koneksi ke Qdrant Local
print("\n💽 Membuka database Qdrant lokal...")
client = QdrantClient(path="./qdrant_custom_db") 

# PENTING: Gunakan nama collection yang sesuai dengan embedding E5 (768 dim)
# Jika Anda menggunakan collection lama (Qwen), ini akan error karena dimensi mismatch.
COLLECTION_NAME = "hybrid_e5_splade_no_quant" 

if not client.collection_exists(COLLECTION_NAME):
    print(f"⚠️ PERINGATAN: Koleksi '{COLLECTION_NAME}' tidak ditemukan!")
    print("Pastikan Anda sudah menjalankan script 'Create Collection & Ingest' sebelumnya.")

# ==========================================
# 3. FUNGSI RETRIEVAL
# ==========================================

async def retrieve_from_qdrant_e5(question: str, k: int = 3, thinking=False) -> List[Document]:
    """
    Retrieval Hybrid (Dense E5 + Sparse Splade) -> RRF Fusion
    Output: List of LangChain Documents
    """
    print(f"\n🔍 Searching for: '{question}'")

    try:
        # 1. Embed Query
        # get_dense_vector sudah otomatis menambah "query: " di dalamnya
        q_dense = embedding_model_e5.get_dense_vector(question)
        q_sparse = embedding_model_e5.get_sparse_vector(question)
        
        # 2. Search dengan RRF (Reciprocal Rank Fusion)
        results = client.query_points(
            collection_name=COLLECTION_NAME,
            prefetch=[
                models.Prefetch(
                    query=q_dense,
                    using="dense_vector",
                    limit=10  # Ambil top-10 kandidat dense
                ),
                models.Prefetch(
                    query=q_sparse,
                    using="sparse_vector",
                    limit=10  # Ambil top-10 kandidat sparse
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k # Final result limit
        )

        langchain_docs = []

        for i, hit in enumerate(results.points, start=1):
            score = hit.score
            payload = hit.payload
            content = payload.get('text', '')
            metadata = payload.get('metadata', {})
            
            # Print untuk debugging (sesuai request)
            print(f"--- RESULT {i} ---")
            print(f"Score (RRF): {score:.4f}")
            print(f"File: {metadata.get('source_file', 'unknown')}")
            print(f"Text Snippet:\n{content[:200]}...") # Print 200 char pertama saja biar rapi
            print("-" * 40)

            # Convert ke LangChain Document agar kompatibel dengan Chain/LLM nantinya
            doc = Document(
                page_content=content,
                metadata={
                    "score": score,
                    **metadata
                }
            )
            langchain_docs.append(doc)

        return langchain_docs

    except Exception as e:
        print(f"❌ Error saat retrieval Qdrant: {e}")
        return []