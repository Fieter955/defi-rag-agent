import os
import base64
import requests
from pdf2image import convert_from_path

# --- KONFIGURASI ---
PDF_PATH = "C:\\Users\\Ilmu Komputer\\OneDrive\\Desktop\\portofolio\\RAG\\defi-rag-agent\\data\\input_pdfs\\tiga_empat_merged.pdf"
SERVER_URL = "http://localhost:5001/v1/chat/completions" # Endpoint KoboldCPP
OUTPUT_FILE = "hasil_ocr.md"
# Jika 
#  belum di PATH, masukkan lokasinya di sini:
# POPPLER_PATH = r"C:\path\to\poppler-xx\Library\bin"

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def process_pdf_to_ocr(pdf_path):
    print(f"[*] Mengubah PDF ke Gambar...")
    # Ubah PDF ke list gambar (1 gambar per halaman)
    pages = convert_from_path(pdf_path, 300) # 300 DPI untuk akurasi terbaik
    
    full_markdown = ""
    
    for i, page in enumerate(pages):
        temp_image = f"temp_page_{i}.jpg"
        page.save(temp_image, "JPEG")
        
        print(f"[>] Memproses Halaman {i+1}...")
        base64_image = encode_image(temp_image)
        
        # Payload untuk Vision Model
# Payload yang dioptimasi untuk Bahasa Indonesia + Markdown (Tanpa HTML)
        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Anda adalah asisten OCR profesional khusus dokumen bahasa Indonesia. "
                        "Tugas Anda: Ekstrak teks secara verbatim (apa adanya) dan deskripsikan elemen visual "
                        "hanya dalam bahasa Indonesia. WAJIB menggunakan format Markdown murni. "
                        "DILARANG keras menggunakan tag HTML seperti <table>. "
                        "Gunakan format tabel Markdown (| Header |) untuk semua tabel."
                    )
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text", 
                            "text": (
                                "Ekstrak semua informasi dari gambar ini. Tulis ulang teks yang ada, "
                                "dan jika ada gambar/diagram, jelaskan isinya dalam bahasa Indonesia yang formal. "
                                "Berikan output dalam Markdown yang rapi."
                            )
                        },
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            "max_tokens": 4096,
            "temperature": 0.1, # Rendah agar tidak halusinasi atau keluar dari instruksi
            "top_p": 0.9
        }
        
        try:
            response = requests.post(SERVER_URL, json=payload)
            response.raise_for_status()
            text_output = response.json()['choices'][0]['message']['content']
            
            full_markdown += f"\n\n\n" + text_output
            
        except Exception as e:
            print(f"[!] Error pada halaman {i+1}: {e}")
        
        # Hapus file temporary gambar
        os.remove(temp_image)

    # Simpan hasil akhir
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(full_markdown)
    print(f"\n[+] Selesai! Hasil OCR disimpan di: {OUTPUT_FILE}")

if __name__ == "__main__":
    process_pdf_to_ocr(PDF_PATH)