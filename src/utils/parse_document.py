import os
import shutil
import re
import time
import torch
from pathlib import Path
import pymupdf 
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info
from io import BytesIO
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import DocumentStream
from llama_parse import LlamaParse

# Inisialisasi converter di luar loop agar lebih efisien (load model cuma sekali)
converter = DocumentConverter()

data_dir = Path("./data")
RAW_FOLDER = data_dir / "input_pdfs"
PROCESSED_FOLDER = data_dir / "processed_pdfs"
OUTPUT_MD_FOLDER = data_dir / "output_markdowns"
TEMP_IMG_FOLDER = data_dir / "temp_images_processing"
PROCESSED_MD_FOLDER = data_dir / "processed_markdowns"
pdf_files = [f for f in os.listdir(RAW_FOLDER) if f.lower().endswith('.pdf')]


for folder in [RAW_FOLDER, PROCESSED_FOLDER, OUTPUT_MD_FOLDER, PROCESSED_MD_FOLDER]:
    os.makedirs(folder, exist_ok=True)



# Fungsi ini bertugas untuk merubah pdf menjadi gambar, proses ini diperlukan karna Qwen hanya mengerti format gambar dan text. Fungsi ini akan memindahkan file pdf yang ada pada path data/input_pdfs ke data/processed_pdfs
def extract_pdf_to_images(pdf_path, temp_output_dir):
    image_paths = []
    if not os.path.exists(pdf_path):
        return image_paths

    try:
        doc = pymupdf.open(pdf_path)
        pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
        
        specific_temp_dir = os.path.join(temp_output_dir, pdf_name)
        os.makedirs(specific_temp_dir, exist_ok=True)

        zoom = 2 
        matriks = pymupdf.Matrix(zoom, zoom)

        print(f"--> Mengekstrak {len(doc)} halaman dari {os.path.basename(pdf_path)}...")
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=matriks)
            
            output_image_path = os.path.join(specific_temp_dir, f"{pdf_name}_hal_{page_num:03d}.png")
            pix.save(output_image_path)
            image_paths.append(output_image_path)
        
        doc.close()
        return sorted(image_paths)

    except Exception as e:
        print(f"Error saat ekstraksi PDF {pdf_path}: {e}")
        return []


# Fungsi pipeline dari merubah pdf menjadi markdown menggunakan Qwen
def parsing_with_Qwen():

    if not pdf_files:
        print("Tidak ada file PDF baru di folder input.")
        return

    print(f"Ditemukan {len(pdf_files)} file PDF untuk diproses.")

    MODEL_ID = "Qwen/Qwen2.5-VL-7B-Instruct"

    print("Memuat model AI... (ini mungkin memakan waktu)")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True
    )

    try:
        model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            MODEL_ID,
            quantization_config=bnb_config,
            device_map="auto"
        )
        processor = AutoProcessor.from_pretrained(MODEL_ID)
        print("Model berhasil dimuat!")
    except Exception as e:
        print(f"Gagal memuat model: {e}")
        exit()

    for pdf_file in pdf_files:
        start_time = time.time()
        pdf_path = os.path.join(RAW_FOLDER, pdf_file)
        base_name = os.path.splitext(pdf_file)[0]
        
        print(f"\n=== Memulai proses: {pdf_file} ===")

        image_paths = extract_pdf_to_images(pdf_path, TEMP_IMG_FOLDER)

        if not image_paths:
            print(f"Gagal mengekstrak gambar dari {pdf_file}, melewati file ini.")
            continue

        full_markdown = ""
        regex_pattern = r'(?s)system\s*You are a helpful assistant\.\s*user.*?\s*assistant'

        print(f"--> Memulai proses AI untuk {len(image_paths)} gambar...")
        
        for i, img_path in enumerate(image_paths):
            print(f"    Memproses halaman {i+1}/{len(image_paths)}...")
            try:
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image", "image": img_path},
                            {"type": "text", "text": "Ekstraklah apa yang anda lihat dari gambar (bisa berupa tabel ataupun gambar) tanpa menambah atau mengurasi informasi sedikitpun!. Berikan output dalam format markdown yang mana pasti menggunakan simbol # pada setiap judulnya!!!."},
                        ],
                    }
                ]

                text_prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                image_inputs, video_inputs = process_vision_info(messages)
                inputs = processor(
                    text=[text_prompt],
                    images=image_inputs,
                    videos=video_inputs,
                    padding=True,
                    return_tensors="pt"
                ).to(model.device)

                generated_ids = model.generate(**inputs, max_new_tokens=10000)
                
                generated_ids_trimmed = [
                    out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
                ]
                
                output_text = processor.batch_decode(
                    generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
                )[0]

                cleaned_response = re.sub(regex_pattern, '', output_text, flags=re.DOTALL).strip()

                full_markdown += f"\n\n--- Halaman {i+1} ---\n\n" + cleaned_response

            except Exception as e:
                print(f"    Error memproses halaman {i+1}: {e}")
                full_markdown += f"\n\n--- Halaman {i+1} (ERROR) ---\n\n[Gagal memproses halaman ini]"

        output_md_path = os.path.join(OUTPUT_MD_FOLDER, f"{base_name}.md")
        with open(output_md_path, "w", encoding="utf-8") as f:
            f.write(full_markdown)
        print(f"--> Markdown tersimpan di: {output_md_path}")

        shutil.move(pdf_path, os.path.join(PROCESSED_FOLDER, pdf_file))
        print(f"--> File asli dipindahkan ke: {PROCESSED_FOLDER}")

        temp_pdf_dir = os.path.dirname(image_paths[0])
        if os.path.exists(temp_pdf_dir):
            shutil.rmtree(temp_pdf_dir)
        print("--> File sementara dibersihkan.")
        
        elapsed_time = time.time() - start_time
        print(f"=== Selesai memproses {pdf_file} dalam {elapsed_time:.2f} detik ===")



# Fungsi pipeline dari merubah pdf menjadi markdown menggunakan Docling dimana file pdf yang ada pada path data/input_pdfs akan dipindah ke data/processed_pdfs
def parsing_with_Docling():
    if not pdf_files:
        print("Tidak ada file PDF baru di folder input.")
        return

    print(f"Ditemukan {len(pdf_files)} file PDF untuk diproses dengan Docling.")

    for pdf_file in pdf_files:
        start_time = time.time()

        pdf_path = os.path.join(RAW_FOLDER, pdf_file)
        base_name = os.path.splitext(pdf_file)[0]

        print(f"\n=== Memulai proses: {pdf_file} ===")
        try:
            with open(pdf_path, "rb") as f:
                file_bytes = f.read()

            buf = BytesIO(file_bytes)
            source = DocumentStream(name=pdf_file, stream=buf)
            result = converter.convert(source)
            full_markdown = result.document.export_to_markdown()
            output_md_path = os.path.join(OUTPUT_MD_FOLDER, f"{base_name}.md")
            
            with open(output_md_path, "w", encoding="utf-8") as f:
                f.write(full_markdown)
                
            print(f"--> Markdown tersimpan di: {output_md_path}")

            shutil.move(pdf_path, os.path.join(PROCESSED_FOLDER, pdf_file))
            print(f"--> File asli dipindahkan ke: {PROCESSED_FOLDER}")
            
        except Exception as e:
            print(f"!!! Gagal memproses {pdf_file}: {e}")

        elapsed_time = time.time() - start_time
        print(f"=== Selesai memproses {pdf_file} dalam {elapsed_time:.2f} detik ===")

os.environ["LLAMA_CLOUD_API_KEY"] = "llx-SsnqiYXt7b1taATXraO2PGnLeWqp7BbgZaGMqgO6bUVnAyO1"
def parsing_with_llamaparse():
    if not pdf_files:
        print("Tidak ada file PDF baru di folder input.")
        return

    print(f"Ditemukan {len(pdf_files)} file PDF untuk diproses dengan LlamaParse.")
    parser = LlamaParse(
        api_key="llx-SsnqiYXt7b1taATXraO2PGnLeWqp7BbgZaGMqgO6bUVnAyO1",
        result_type="markdown",
        premium_mode=True,
        language="id",
        use_vendor_multimodal_model=True,
        vendor_multimodal_model_name="openai-gpt4o", 
        preserve_layout_alignment_across_pages=True,
        verbose=True
    )

    for pdf_file in pdf_files:
        start_time = time.time()

        pdf_path = os.path.join(RAW_FOLDER, pdf_file)
        base_name = os.path.splitext(pdf_file)[0]

        print(f"\n=== Memulai proses: {pdf_file} ===")
        try:
            documents = parser.load_data(pdf_path)
            full_markdown = "\n\n".join([doc.text for doc in documents])
            output_md_path = os.path.join(OUTPUT_MD_FOLDER, f"{base_name}.md")            
            with open(output_md_path, "w", encoding="utf-8") as f:
                f.write(full_markdown)                
            print(f"--> Markdown tersimpan di: {output_md_path}")
            shutil.move(pdf_path, os.path.join(PROCESSED_FOLDER, pdf_file))
            print(f"--> File asli dipindahkan ke: {PROCESSED_FOLDER}")
        except Exception as e:
            print(f"!!! Gagal memproses {pdf_file}: {e}")
        elapsed_time = time.time() - start_time
        print(f"=== Selesai memproses {pdf_file} dalam {elapsed_time:.2f} detik ===")
