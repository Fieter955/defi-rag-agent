import os
import shutil
import re
from pathlib import Path
from elasticsearch import Elasticsearch
from langchain.text_splitter import MarkdownHeaderTextSplitter
from src import resources
from src.utils.parse_document import parsing_with_Qwen, parsing_with_Docling, parsing_with_llamaparse
from langchain_text_splitters import MarkdownHeaderTextSplitter
#from qdrant_client.http import models
import torch.nn.functional as F
from qdrant_client import QdrantClient, models

async def get_table_metadata(content):
    """
    Menggunakan LLM untuk menganalisis tabel dalam konten markdown
    dan menghasilkan pertanyaan potensial untuk metadata.
    """
    print("      ... Mengontak LLM untuk analisis tabel ...")
    
    prompt = f"""
    Diberikan potongan dokumen Markdown berikut yang berisi TABEL data tentang universitas. Pastikan anda paham konteksnya adalah dokumen perkuliahan:
    "{content}"
        
    Tugas:
    Berikan saya 10 kemungkinan pertanyaan yang paling mungkin ditanyakan (probabilitas tinggi) jika ada mahasiswa, dosen, atau pegawai ingin bertanya sesuatu berdasarkan kolom dan isi tabel yang ada
        
    Format Output (Plain text):
    Pertanyaan: [1. Pertanyan 1, Pertanyaan 2 ....]
    """

    try:
        response = await resources.llm.ainvoke(prompt)
        return response.content
    except Exception as e:
        print(f"      [!] Error LLM: {e}")
        return None

async def initialize_elasticsearch_indexer(parsing: str, indexing: bool = False):
    """
    Fungsi utama untuk inisialisasi dan indexing:
    1. Cek koneksi & Index Elasticsearch.
    2. Parsing PDF ke Markdown (jika indexing=True).
    3. Chunking Markdown berdasarkan Header.
    4. Filtering Chunk (SUPER STRICT MODE).
    5. Upload ke Elasticsearch.
    """
    print("Memulai inisialisasi Elasticsearch Indexer...")
    
    try:
        INDEX_NAME = "dokumen_rag_thesis"
        es_client = Elasticsearch("http://localhost:9200")
        
        # --- 1. Cek Koneksi Elasticsearch ---
        if not es_client.ping():
            print("\033[91mGagal ping ke Elasticsearch.\033[0m")
            return None

        # --- 2. Cek/Buat Index ---
        if not es_client.indices.exists(index=INDEX_NAME):
            print(f"\033[93mMembuat index '{INDEX_NAME}' baru...\033[0m")
            es_client.indices.create(
                index=INDEX_NAME,
                mappings={
                    "properties": {
                        "title": {"type": "text", "analyzer": "standard"},
                        "content": {"type": "text", "analyzer": "standard"},
                    }
                }
            )
        elif not indexing:
            print(f"\033[92mIndex '{INDEX_NAME}' sudah ada.\033[0m")
            return es_client
        
        if not indexing:
            return es_client

        if parsing == "qwen":
            print("Parsing PDF ke Markdown menggunakan Qwen-VL...")
            parsing_with_Qwen()
        elif parsing == "docling":
            parsing_with_Docling()
        else:
            print("Parsing PDF ke Markdown menggunakan Docling...")
            parsing_with_llamaparse()

        print("\nMemulai proses chunking dan indexing ke Elasticsearch...")

        headers_to_split_on = [("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]
        md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
        
        data_dir = Path("./data")
        PROCESSED_MD_FOLDER = data_dir / "processed_markdowns"
        OUTPUT_MD_FOLDER = data_dir / "output_markdowns"
        
        os.makedirs(PROCESSED_MD_FOLDER, exist_ok=True)
        
        md_files = [f for f in os.listdir(OUTPUT_MD_FOLDER) if f.lower().endswith('.md')]
        
        for md_file in md_files:
            md_path = os.path.join(OUTPUT_MD_FOLDER, md_file)

            with open(md_path, "r", encoding="utf-8") as f:
                file_content = f.read()
                split_docs = md_splitter.split_text(file_content)
            
            print(f"\nMemeriksa {len(split_docs)} chunks dari {md_file}...")
            

            # Regex untuk Markdown Table (yang sudah kamu punya)
            TABLE_PATTERN = r"\|.*\|.*\n\|.*[-]{3,}.*\|"

            # Regex untuk HTML Table (mendeteksi tag pembuka <table ... >)
            # \b memastikan itu kata "table", [^>]* menangani atribut seperti class/style
            HTML_TABLE_PATTERN = r"<table\b[^>]*>" 

            final_docs_to_index = []
            skipped_count = 0

            for i, doc in enumerate(split_docs):
                raw_content = doc.page_content
                
                # --- LOGIKA FILTERING STRICT ---
                clean_content = raw_content.strip()
                
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
                
                # -----------------------------------------------

                # --- PROSES DETEKSI TABEL (UPDATED) ---
                
                # Cek Markdown Table
                is_markdown_table = re.search(TABLE_PATTERN, raw_content, re.DOTALL)
                
                # Cek HTML Table (case-insensitive)
                is_html_table = re.search(HTML_TABLE_PATTERN, raw_content, re.IGNORECASE)
                
                # Jika salah satu benar, maka dianggap mengandung tabel
                has_table = bool(is_markdown_table or is_html_table)
                has_table = False 

                if has_table:
                    print(f"   > Chunk #{i}: Tabel Ditemukan! Memproses metadata...")
                    metadata_str = await get_table_metadata(raw_content)
                    
                    if metadata_str:
                        doc.page_content = (
                            f"{raw_content}\n\n"
                            f"\n"
                            f"{metadata_str}\n"
                            f"-------------------"
                        )
                print(doc.metadata)
                final_docs_to_index.append(doc)

            print(f"   -> {skipped_count} chunks 'sampah/kosong' berhasil dibuang.")
            print(f"   -> {len(final_docs_to_index)} chunks valid siap di-index.")

            # --- 5. Indexing ke Elasticsearch ---
            print(f"Memulai push ke Elasticsearch...")
            
            for i, doc in enumerate(final_docs_to_index):
                # Double check terakhir
                if doc.page_content.strip():
                    header_path = [doc.metadata[key] for key in sorted(doc.metadata.keys()) if "Header" in key]
                    title_text = " > ".join(header_path) if header_path else "Untitled Section"
                    
                    custom_id = f"{md_file}_chunk_{i}"
                    
                    es_client.index(
                        index=INDEX_NAME, 
                        document={
                            "title": title_text, 
                            "content": doc.page_content
                        }, 
                        id=custom_id
                    )
            
            es_client.indices.refresh(index=INDEX_NAME)
            print("\n\033[92mIndexing selesai.\033[0m")
            
            shutil.move(md_path, os.path.join(PROCESSED_MD_FOLDER, md_file))
            print(f"--> File asli dipindahkan ke: {PROCESSED_MD_FOLDER}")
            
        return es_client

    except Exception as e:
        print(f"\n\033[91mError init Elasticsearch: {str(e)}\033[0m")
        return None
    




async def initialize_rrf_indexer(parsing: str = "docling", indexing: bool = False):

    print("Memulai inisialisasi RRF Indexer...")
    
    try:

        # Inisialisasi Qdrant (Local Mode)
        print("\n💽 Membuka database Qdrant lokal...")
        rrf_client = QdrantClient(path="./qdrant_custom_db") 
        COLLECTION_NAME = "hybrid_qwen_splade"


        if not rrf_client.collection_exists(COLLECTION_NAME):

            print("⚙️ Membuat Collection baru...")
            rrf_client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config={
                    "dense_vector": models.VectorParams(
                        size=2560,
                        distance=models.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    "sparse_vector": models.SparseVectorParams()
                }
            )
        elif not indexing:
            print(f"\033[92mCollection '{COLLECTION_NAME}' sudah ada.\033[0m")
            return rrf_client
 




        if parsing == "qwen":
            print("Parsing PDF ke Markdown menggunakan Qwen-VL...")
            parsing_with_Qwen()
        elif parsing == "docling":
            parsing_with_Docling()
        else:
            print("Parsing PDF ke Markdown menggunakan Docling...")
            parsing_with_llamaparse()

        print("\nMemulai proses chunking dan indexing ke RRF...")










        headers_to_split_on = [("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]
        md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
        
        data_dir = Path("./data")
        PROCESSED_MD_FOLDER = data_dir / "processed_markdowns"
        OUTPUT_MD_FOLDER = data_dir / "output_markdowns"
        
        os.makedirs(PROCESSED_MD_FOLDER, exist_ok=True)
        
        md_files = [f for f in os.listdir(OUTPUT_MD_FOLDER) if f.lower().endswith('.md')]







        
        for md_file in md_files:
            md_path = os.path.join(OUTPUT_MD_FOLDER, md_file)

            with open(md_path, "r", encoding="utf-8") as f:
                file_content = f.read()
                split_docs = md_splitter.split_text(file_content)
            
            print(f"\nMemeriksa {len(split_docs)} chunks dari {md_file}...")
            

            # Regex untuk Markdown Table (yang sudah kamu punya)
            TABLE_PATTERN = r"\|.*\|.*\n\|.*[-]{3,}.*\|"

            # Regex untuk HTML Table (mendeteksi tag pembuka <table ... >)
            # \b memastikan itu kata "table", [^>]* menangani atribut seperti class/style
            HTML_TABLE_PATTERN = r"<table\b[^>]*>" 

            final_docs_to_index = []
            skipped_count = 0

            for i, doc in enumerate(split_docs):
                raw_content = doc.page_content
                
                # --- LOGIKA FILTERING STRICT ---
                clean_content = raw_content.strip()
                
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
                
                # -----------------------------------------------

                # --- PROSES DETEKSI TABEL (UPDATED) ---
                
                # Cek Markdown Table
                is_markdown_table = re.search(TABLE_PATTERN, raw_content, re.DOTALL)
                
                # Cek HTML Table (case-insensitive)
                is_html_table = re.search(HTML_TABLE_PATTERN, raw_content, re.IGNORECASE)
                
                # Jika salah satu benar, maka dianggap mengandung tabel
                has_table = bool(is_markdown_table or is_html_table)
                has_table = False 

                if has_table:
                    print(f"   > Chunk #{i}: Tabel Ditemukan! Memproses metadata...")
                    metadata_str = await get_table_metadata(raw_content)
                    
                    if metadata_str:
                        doc.page_content = (
                            f"{raw_content}\n\n"
                            f"\n"
                            f"{metadata_str}\n"
                            f"-------------------"
                        )
                print(doc.metadata)
                final_docs_to_index.append(doc)

            print(f"   -> {skipped_count} chunks 'sampah/kosong' berhasil dibuang.")
            print(f"   -> {len(final_docs_to_index)} chunks valid siap di-index.")











            # --- 5. Indexing ke Elasticsearch ---
            print(f"Memulai push ke RRF...")
            
            for i, doc in enumerate(final_docs_to_index):
                # Double check terakhir
                if doc.page_content.strip():
                    header_path = [doc.metadata[key] for key in sorted(doc.metadata.keys()) if "Header" in key]
                    title_text = " > ".join(header_path) if header_path else "Untitled Section"
                    
                    custom_id = f"{md_file}_chunk_{i}"
                    
                    rrf_client.index(
                        index=INDEX_NAME, 
                        document={
                            "title": title_text, 
                            "content": doc.page_content
                        }, 
                        id=custom_id
                    )
            
            es_clirrf_clientnt.indices.refresh(index=INDEX_NAME)
            print("\n\033[92mIndexing selesai.\033[0m")
            
            shutil.move(md_path, os.path.join(PROCESSED_MD_FOLDER, md_file))
            print(f"--> File asli dipindahkan ke: {PROCESSED_MD_FOLDER}")
            
        return rrf_client

    except Exception as e:
        print(f"\n\033[91mError init rrf: {str(e)}\033[0m")
        return None