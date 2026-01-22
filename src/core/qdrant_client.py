
import re
import os
from typing import Optional
import uuid
from flask import json
import torch
import shutil
import torch.nn.functional as F
from glob import glob
from src import resources
from pathlib import Path
from langchain_text_splitters import MarkdownHeaderTextSplitter
from transformers import AutoModel, AutoTokenizer, AutoModelForMaskedLM, BitsAndBytesConfig
from qdrant_client.models import PointStruct, SparseVector, Distance, VectorParams, SparseVectorParams
from src.utils.parse_document import parsing_with_Qwen, parsing_with_Docling, parsing_with_llamaparse





DENSE_MODEL_ID = "Qwen/Qwen3-Embedding-4B"
SPARSE_MODEL_ID = "naver/splade-v3"
QDRANT_PATH = "./qdrant_custom_db_qwen"
COLLECTION_NAME = "hybrid_qwen_splade_optimized"


device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Running on: {device}")

# Konfigurasi Kuantisasi 4-bit
bnb_config = None
if device == "cuda":
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16
    )


#CLASS EMBEDDER (DENSE + SPARSE)
def last_token_pool(last_hidden_states: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Helper function khusus untuk Qwen/GTE embedding agar ambil token terakhir"""
    left_padding = (attention_mask[:, -1].sum() == attention_mask.shape[0])
    if left_padding:
        return last_hidden_states[:, -1]
    else:
        sequence_lengths = attention_mask.sum(dim=1) - 1
        batch_size = last_hidden_states.shape[0]
        return last_hidden_states[torch.arange(batch_size, device=last_hidden_states.device), sequence_lengths]

class CustomEmbedder:
    def __init__(self):
        print("Loading Dense Model (Qwen 4-bit)...")
        self.dense_tokenizer = AutoTokenizer.from_pretrained(DENSE_MODEL_ID, trust_remote_code=True)
        self.dense_model = AutoModel.from_pretrained(
            DENSE_MODEL_ID,
            trust_remote_code=True,
            quantization_config=bnb_config,
            device_map="auto" if device == "cuda" else None,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32
        )
        if device == "cpu": self.dense_model.to("cpu")

        print("Loading Sparse Model (Splade v3)...")
        self.sparse_tokenizer = AutoTokenizer.from_pretrained(SPARSE_MODEL_ID)
        self.sparse_model = AutoModelForMaskedLM.from_pretrained(SPARSE_MODEL_ID)
        self.sparse_model.to(device)

    def get_dense_vector(self, text):
        inputs = self.dense_tokenizer(
            text, max_length=8192, padding=True, truncation=True, return_tensors='pt'
        )
        inputs = {k: v.to(self.dense_model.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.dense_model(**inputs)
            embeddings = last_token_pool(outputs.last_hidden_state, inputs['attention_mask'])
            embeddings = F.normalize(embeddings, p=2, dim=1)
            
        return embeddings[0].cpu().tolist()

    def get_sparse_vector(self, text):
        inputs = self.sparse_tokenizer(
            text, return_tensors="pt", padding=True, truncation=True
        )
        inputs = {k: v.to(self.sparse_model.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.sparse_model(**inputs)
        logits = outputs.logits[0]
        relu_log = torch.log(1 + torch.relu(logits))
        attention_mask = inputs["attention_mask"][0].unsqueeze(-1)
        weighted_log = relu_log * attention_mask
        max_val, _ = torch.max(weighted_log, dim=0)
        indices = torch.nonzero(max_val).squeeze().cpu().tolist()
        values = max_val[indices].cpu().tolist()
        if isinstance(indices, int):
            indices = [indices]
            values = [values]
            
        return SparseVector(indices=indices, values=values)


#SETUP DATABASE QDRANT
embedder = CustomEmbedder()
print(f"\nMembuka database Qdrant lokal di: {QDRANT_PATH}")
client = resources.qdrant_client

async def get_table_metadata(content):
    """
    Menggunakan LLM untuk menganalisis tabel dalam konten markdown
    dan menghasilkan sebuah deskripsi singkat tentang tabel yang ada pada chunk.
    """
    print("      ... Mengontak LLM untuk analisis tabel ...")
    
    prompt = f"""
    Diberikan potongan dokumen berikut yang berisi TABEL data tentang universitas. Pastikan anda paham konteksnya adalah dokumen perkuliahan:
    "{content}"
        
    Tugas:
    Berikan deskripsi singkat tentang tabel tersebut
        
    Format Output (Plain text):
    "Tabel ini berisi informasi tentang ...."
    """

    try:
        response = await resources.llm.ainvoke(prompt)
        return response.content
    except Exception as e:
        print(f"      [!] Error LLM: {e}")
        return None
    


import re
import json
import logging
from typing import Optional, List

# Setup logging sederhana
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_column_count(line: str) -> int:
    """
    Helper untuk menghitung jumlah kolom dalam satu baris tabel Markdown.
    Contoh: "| col1 | col2 |" -> 2
    """
    if not line or '|' not in line:
        return 0
    # Hilangkan pipe di awal dan akhir lalu split
    segments = line.strip().strip('|').split('|')
    return len(segments)

def fallback_table_comparison(current_chunk: str, previous_chunk: str) -> bool:
    """
    Membandingkan struktur kolom antara akhir chunk sebelumnya 
    dan awal chunk saat ini tanpa bergantung pada header.
    """
    # Cari baris terakhir di chunk sebelumnya yang mengandung pipe
    prev_lines = [l.strip() for l in previous_chunk.strip().split('\n') if '|' in l]
    # Cari baris pertama di chunk saat ini yang mengandung pipe
    curr_lines = [l.strip() for l in current_chunk.strip().split('\n') if '|' in l]

    if not prev_lines or not curr_lines:
        return False

    # Kita bandingkan baris terakhir tabel lama dengan baris pertama tabel baru
    last_prev_row = prev_lines[-1]
    first_curr_row = curr_lines[0]

    # Abaikan jika baris tersebut adalah separator "|---|---|"
    if re.match(r'^\s*\|?[-:\s|]+\|?\s*$', last_prev_row):
        last_prev_row = prev_lines[-2] if len(prev_lines) > 1 else last_prev_row

    prev_cols = extract_column_count(last_prev_row)
    curr_cols = extract_column_count(first_curr_row)

    # Jika jumlah kolom sama dan > 0, asumsikan tabel berlanjut
    is_same = prev_cols > 0 and prev_cols == curr_cols
    if is_same:
        logger.info(f"Fallback: Table continuation detected via column count ({prev_cols} cols).")
    
    return is_same

def chunk_start_with_table(content: str, threshold: int = 20) -> bool:
    """
    Mendeteksi apakah sebuah chunk dimulai langsung dengan tabel (Markdown/HTML).
    Sangat berguna untuk menentukan kapan harus memanggil LLM untuk pengecekan merger.
    """
    content_stripped = content.lstrip()
    if not content_stripped:
        return False

    # Regex untuk baris data Markdown atau baris header
    MD_TABLE_ROW = r'^\s*\|.*\|'
    # Regex untuk tag tabel HTML
    HTML_TABLE_TAG = r'^\s*<(table|tr|thead|tbody)'

    lines = content_stripped.split('\n')
    
    # Cek 3 baris pertama untuk toleransi whitespace/karakter kecil
    accumulated_text_len = 0
    for line in lines[:3]:
        if re.match(MD_TABLE_ROW, line) or re.search(HTML_TABLE_TAG, line, re.I):
            if accumulated_text_len <= threshold:
                return True
        accumulated_text_len += len(line)
        
    return False

async def is_table_same_as_previous_chunk(
    current_chunk: str, 
    previous_chunk: str
) -> bool:
    """
    Fungsi utama menggunakan LLM untuk menganalisis kesinambungan tabel.
    """
    

    prompt = f"""Analisis apakah tabel di 'CHUNK SEKARANG' adalah lanjutan langsung dari tabel di 'CHUNK SEBELUMNYA'.

    CHUNK SEBELUMNYA:
    \"\"\"{previous_chunk}\"\"\"

    CHUNK SEKARANG:
    \"\"\"{current_chunk}\"\"\"

    Tugas:
    Tentukan is_same_table = true jika:
    1. Struktur kolom (jumlah & nama kolom) konsisten.
    2. Data di chunk sekarang adalah baris tambahan dari data di chunk sebelumnya.
    3. Tidak ada judul tabel baru atau paragraf pemisah yang jelas.

    Jawab hanya dalam format JSON:
    {{
        "reasoning": "penjelasan singkat",
        "is_same_table": True/False
    }}"""

    try:
        # Pemanggilan LLM
        response = await resources.llm.ainvoke(prompt)
        
        # Ekstrak konten (mendukung berbagai wrapper seperti LangChain/Ollama)
        raw_content = response.content if hasattr(response, 'content') else str(response)
        
        # Cari blok JSON dalam teks
        json_match = re.search(r'\{.*\}', raw_content, re.DOTALL)
        if not json_match:
            raise ValueError("LLM tidak mengembalikan JSON yang valid")
            
        result = json.loads(json_match.group(0))
        
        logger.info(f"LLM Reasoning: {result.get('reasoning')}")
        logger.info(f"LLM Result: {result.get('is_same_table')}")
        return bool(result.get("is_same_table", False))

    except Exception as e:
        logger.error(f"Error LLM Analysis: {e}. Switching to fallback.")
        # Jika LLM gagal (timeout/quota), gunakan logika jumlah kolom
        return fallback_table_comparison(current_chunk, previous_chunk)




async def initialize_qdrant_indexer(parser: str, indexing: bool = False):
    """
    Fungsi utama untuk inisialisasi dan indexing:
    1. Cek koneksi & Index Qdrant.
    2. Parsing PDF ke Markdown (jika indexing=True).
    3. Chunking Markdown berdasarkan Header.
    4. Filtering Chunk (SUPER STRICT MODE).
    5. Upload ke Qdrant.
    """
    print("Memulai inisialisasi Qdrant Indexer...")
    
    try:
        print(f"\nMembuka database Qdrant lokal di: {QDRANT_PATH}")

        if not client.collection_exists(COLLECTION_NAME):
            print("Collection belum ada. Membuat Collection baru...")
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config={
                    "dense_vector": VectorParams(size=2560, distance=Distance.COSINE) 
                },
                sparse_vectors_config={
                    "sparse_vector": SparseVectorParams()
                }
            )
        elif not indexing:
            print(f"\033[92mKoleksi: '{COLLECTION_NAME}' sudah ada.\033[0m")
            return client
        
        if parser == "qwen":
            print("Parsing PDF ke Markdown menggunakan Qwen-VL...")
            parsing_with_Qwen()
        elif parser == "docling":
            parsing_with_Docling()
        else:
            print("Parsing PDF ke Markdown menggunakan Docling...")
            parsing_with_llamaparse()

        print("\nMemulai proses chunking dan indexing ke Qdrant...")

        headers_to_split_on = [("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]
        md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)

        #FUNGSI UTILITY (CLEANING & SPLITTING)
        def clean_title(filename):
            """Membersihkan nama file dari ekstensi dan timestamp (misal: _250130_133808)"""
            name = os.path.splitext(filename)[0]
            1
            name = re.sub(r'[-_]\d{6,}.*', '', name)
            name = name.replace("-", " ").replace("_", " ")
            return " ".join(name.split())
        
        data_dir = Path("./data")
        PROCESSED_MD_FOLDER = data_dir / "processed_markdowns"
        OUTPUT_MD_FOLDER = data_dir / "output_markdowns"
        
        os.makedirs(PROCESSED_MD_FOLDER, exist_ok=True)

        #md_files = glob.glob(os.path.join(OUTPUT_MD_FOLDER, "*.md"))
        md_files = list(OUTPUT_MD_FOLDER.glob("*.md"))
        print(f"Ditemukan {len(md_files)} file Markdown.")
        
        skipped_count = 0
        points = []
        print("Mulai proses embedding...")
        for file_index, file_path in enumerate(md_files):
            file_name = os.path.basename(file_path)

            doc_title = clean_title(file_name)
            
            with open(file_path, "r", encoding="utf-8") as f:
                file_content = f.read()
                
            docs = md_splitter.split_text(file_content)
            total_chunks = len(docs)
            
            print(f"\nFile [{file_index+1}/{len(md_files)}]: {file_name}")
            print(f"Clean Title: '{doc_title}'")

            # Regex untuk Markdown Table (yang sudah kamu punya)
            TABLE_PATTERN = r"\|.*\|.*\n\|.*[-]{3,}.*\|"
            POTENTIAL_TABLE_ROW_PATTERN = r"^\s*\|.*\|\s*$"

            # Regex untuk HTML Table (mendeteksi tag pembuka <table ... >)
            # \b memastikan itu kata "table", [^>]* menangani atribut seperti class/style
            HTML_TABLE_PATTERN = r"<table\b[^>]*>"

            last_processed_content = ""
            detected_tables_in_previous_chunk = False
            for i, doc in enumerate(docs):
                # --- LOGIKA FILTERING STRICT ---
                clean_content = doc.page_content.strip()
                
                # Cek 1: Kosong?
                if not clean_content:
                    skipped_count += 1
                    continue

                # Cek 2: Minimal satu huruf/angka?
                if not re.search(r"[a-zA-Z0-9]", clean_content):
                    skipped_count += 1
                    continue

                # Cek 3: Diawali tanda baca aneh?
                if clean_content[0] in ['.', '…', '。']:
                    skipped_count += 1
                    continue

                header_keys = [name for _, name in headers_to_split_on]
                found_headers = []
                for key in header_keys:
                    if key in doc.metadata:
                        found_headers.append(doc.metadata[key])
                context_chain = [doc_title] + found_headers
                breadcrumb_str = " > ".join(context_chain)
                final_text = f"{breadcrumb_str} : {clean_content}"

                print(f"Chunk [{i+1}/{total_chunks}] | {breadcrumb_str}")


                # --- PROSES DETEKSI TABEL (UPDATED) ---
                
                # Cek Markdown Table
                # 1. Cek apakah ada struktur tabel lengkap (untuk tabel baru)
                is_complete_table = re.search(TABLE_PATTERN, clean_content, re.DOTALL)

                # 2. Cek apakah chunk dimulai dengan baris tabel (untuk tabel lanjutan)
                # Gunakan fungsi yang sudah Anda buat sebelumnya
                is_continuation_pattern = chunk_start_with_table(clean_content)
                
                # Cek HTML Table (case-insensitive)
                is_html_table = re.search(HTML_TABLE_PATTERN, clean_content, re.IGNORECASE)
                
                # Jika salah satu benar, maka dianggap mengandung tabel
                has_table = bool(is_complete_table or is_continuation_pattern or is_html_table)

                final_content = final_text
                if has_table:
                    print('Terdeteksi ada tabel di chunk ini.')
                    # 1. Cek apakah ini awal chunk yang langsung tabel DAN sebelumnya juga ada tabel
                    if chunk_start_with_table(clean_content) and detected_tables_in_previous_chunk:
                        # 2. Tanya LLM apakah ini tabel yang sama
                        is_same = await is_table_same_as_previous_chunk(
                            clean_content, last_processed_content
                        )
                        
                        if is_same:
                            print(f"   > Chunk #{i+1}: Tabel Lanjutan Terdeteksi. Menggabungkan...")
                            # Ambil konten sebelumnya dan gabungkan
                            # Catatan: Kita menggabungkan clean_content-nya saja agar breadcrumb tidak double di tengah
                            final_content = f"{last_processed_content}\n{clean_content}"
                            # Opsional: Hapus point sebelumnya dari list 'points' jika ingin mengganti dengan yang baru
                            if points: points.pop() 
                        else:
                            # Tabel baru meskipun sebelumnya ada tabel
                            metadata_str = await get_table_metadata(final_text)
                            final_content = f"{breadcrumb_str} > {metadata_str} : {clean_content}"
                    else:
                        # Kasus: Tabel pertama kali ditemukan di file ini
                        print(f"   > Chunk #{i+1}: Tabel Baru. Membuat Metadata...")
                        metadata_str = await get_table_metadata(final_text)
                        final_content = f"{breadcrumb_str} > {metadata_str} : {clean_content}"
                    
                    detected_tables_in_previous_chunk = True
                else:
                    detected_tables_in_previous_chunk = False

                last_processed_content = final_content # Simpan untuk chunk berikutnya
  

                try:
                    d_vec = embedder.get_dense_vector(final_content)
                    s_vec = embedder.get_sparse_vector(final_content)

                    if file_index == 0 and i == 0:
                        print(f"Detected Dense Vector Size: {len(d_vec)}")

                    metadata = doc.metadata
                    metadata["source_file"] = file_name
                    metadata["doc_title"] = doc_title
                    metadata["id"] = f"{doc_title}_{i}"
                    
                    points.append(PointStruct(
                        id=str(uuid.uuid4()), 
                        vector={
                            "dense_vector": d_vec,
                            "sparse_vector": s_vec
                        },
                        payload={
                            "preprocessed_content": final_content,
                            "original_content": clean_content,
                            "metadata": metadata
                        }
                    ))
                except Exception as e:
                    print(f"Error embedding chunk: {e}")
            
            print(f"skipped_count: {skipped_count} chunks yang di-skip karena filter strict.")
            output_md_path = os.path.join(OUTPUT_MD_FOLDER, f"{file_name}.md")
            

                
            print(f"--> Markdown tersimpan di: {output_md_path}")

            shutil.move(file_path, os.path.join(PROCESSED_MD_FOLDER, file_name))
            print(f"--> File asli dipindahkan ke: {PROCESSED_MD_FOLDER}")

            

        if points:
            print(f"\nMengupload {len(points)} points ke Qdrant...")
            BATCH_SIZE = 50
            for i in range(0, len(points), BATCH_SIZE):
                batch = points[i:i+BATCH_SIZE]
                client.upsert(collection_name=COLLECTION_NAME, points=batch)
                print(f"   Saved batch {i} - {i+len(batch)}")
            print("Semua data berhasil diupload!")
        else:
            print("Tidak ada data point yang dihasilkan.")
        return client

    except Exception as e:
        print(f"\n\033[91mError init qdrant: {str(e)}\033[0m")
        return None