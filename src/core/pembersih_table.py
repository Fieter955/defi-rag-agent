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