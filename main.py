import uvicorn
import sys
import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from starlette.staticfiles import StaticFiles
import src.resources as resources
from src.core.qdrant_client import initialize_qdrant_indexer
from src.routes.chat_routes import router as chat_router

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n[LIFESPAN] Memulai inisialisasi resources...")

    resources.c = await initialize_qdrant_indexer(parser="docling", indexing=False)
    
    if resources.qdrant_client:
        print("\033[92m[CHECK] Qdrant SIAP.\033[0m")
    else:
        print("\033[91m[CHECK] WARNING: Qdrant tidak terkoneksi.\033[0m")
    
    yield
    
    print("\n[LIFESPAN] Membersihkan resources...")
    if resources.qdrant_client:
        await resources.qdrant_client.close()

app = FastAPI(title="DéFi RAG Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    while True:
        print("\n" + "="*50)
        print("   DéFi RAG Agent - MAIN CONTROL MENU")
        print("="*50)
        print("1. [START SERVER] Aktifkan System (API & Chat)")
        print("2. [DATA PREP]    Parsing PDF & Index ke Elasticsearch")
        print("0. [EXIT]         Keluar")
        print("-" * 50)
        
        try:
            pilihan = input("Masukkan pilihan (0-2): ").strip()
        except KeyboardInterrupt:
            print("\nKeluar...")
            sys.exit()

        if pilihan == "1":
            print("\n[INFO] Menjalankan Server Uvicorn...")
            print("[HINT] Tekan CTRL+C untuk mematikan server dan kembali ke menu.")

            try:
                uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
            except KeyboardInterrupt:
                print("\n[INFO] Server dimatikan manual.")
            
            print("[INFO] Kembali ke menu utama...")

        elif pilihan == "2":
            print("\n   --- PILIH METODE PARSING ---")
            print("   a. Docling (CPU Friendly)")
            print("   b. Qwen-VL (Butuh GPU/CUDA)")
            print("   c. Llamaparse (Butuh API)")
            
            sub = input("   Pilihan (a/b/c): ").lower().strip()
            
            if sub == 'a':
                print("\n[INFO] Menjalankan Parsing (Docling) + Indexing...")
                asyncio.run(initialize_qdrant_indexer(parser="docling", indexing=True))
                print("[SUCCESS] Selesai.")
                
            elif sub == 'b':
                try:
                    import torch
                    if torch.cuda.is_available():
                        print("\n\033[92m[CHECK] GPU NVIDIA Terdeteksi. Menggunakan Qwen.\033[0m")
                        print("[INFO] Menjalankan Parsing (Qwen) + Indexing...")
                        asyncio.run(initialize_qdrant_indexer(parser="qwen", indexing=True))
                        print("[SUCCESS] Selesai.")
                    else:
                        print("\n\033[91m[ERROR] Tidak bisa menggunakan Qwen!\033[0m")
                        print("Alasan: Tidak ada GPU CUDA yang terdeteksi.")
                        print("Saran: Gunakan opsi (a) Docling.\n")
                except ImportError:
                    print("\n\033[91m[ERROR] PyTorch tidak terinstall.\033[0m")
            elif sub == 'c':
                print("\n[INFO] Menjalankan Parsing (Llamaparse) + Indexing...")
                asyncio.run(initialize_qdrant_indexer(parser="llamaparse", indexing=True))
                print("[SUCCESS] Selesai.")
            else:
                print("   [!] Pilihan salah.")

        elif pilihan == "0":
            print("Bye bye!")
            sys.exit()
        
        else:
            print("[!] Pilihan tidak valid.")