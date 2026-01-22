import string
import itertools
import re
from difflib import SequenceMatcher
from typing import List, Tuple, Dict
from src import resources
from typing import List

# Global cache untuk akronim
_ACRONYM_CACHE = None
_ACRONYM_CACHE_TIMESTAMP = 0
CACHE_TTL = 300  # 5 menit cache

#fungsi bantu untuk resolusi kata ganti dan membuat query standalone
async def resolve_pronouns_and_create_standalone_query(question: str, chat_history: List[Tuple[str, str]]) -> str:
    """
    Menganalisis pertanyaan saat ini dan riwayat obrolan untuk menyelesaikan kata ganti
    dan membuat pertanyaan yang berdiri sendiri (standalone).
    """
    if not chat_history or not resources.llm:
        return question

    formatted_history = "\n".join([f"User: {q}\nBot: {a}" for q, a in chat_history])
    
    prompt = f"""
    Analisis riwayat percakapan dan pertanyaan saat ini. Ubah pertanyaan saat ini menjadi versi yang tidak ambigu dan bisa dipahami sendiri (standalone).
    Jika ada kata ganti (seperti "itu", "dia", "situ", "disana", "disini", "tadi", "tersebut", "yang", "apa", "berapa", "sksnya", "prodinya", "matkulnya", "kampusnya"),
    ganti dengan kata konkrit dari riwayat percakapan.
    
    Return HANYA pertanyaan yang sudah diubah tanpa penjelasan apapun.

    contoh:
    Pertanyaan Saat Ini: "berapa NIPnya?:
    riwayat Percakapan: query user: "siapa NIP rektor Undiksha?". "rektor Undiksha adalah Prof. Dr. I Wayan Lasmawan, M.Pd."
    Pertanyaan yang Diubah (standalone): "berapa NIP Prof. Dr. I Wayan Lasmawan, M.Pd.?"
    
    Riwayat Percakapan:
    {formatted_history}
    
    Pertanyaan Saat Ini: "{question}"
    
    Pertanyaan yang Diubah (standalone): 
    """
    try:
        response = await resources.llm.ainvoke(prompt)
        result = response.content.strip()
        
        # Bersihkan output
        result = result.strip('"').strip("'").strip()
        
        # Hapus prefix jika ada
        prefixes = ["Pertanyaan yang Diubah:", "Hasil:", "Standalone query:", "Query:"]
        for prefix in prefixes:
            if result.startswith(prefix):
                result = result[len(prefix):].strip()
        
        # Hapus suffix jika ada
        suffixes = ["(standalone)", "[standalone]", "- standalone"]
        for suffix in suffixes:
            if result.endswith(suffix):
                result = result[:-len(suffix)].strip()
        
        return result if result else question
        
    except Exception as e:
        print(f"[ERROR] Gagal melakukan resolusi kata ganti: {e}")
        return question

#fungsi bantu untuk koreksi typo dan normalisasi
async def correct_typos_and_normalize(text: str) -> str:
    """
    Memperbaiki typo dan menormalisasi teks menggunakan LLM.
    Fokus pada istilah pendidikan dan akademik.
    """
    if not resources.llm:
        return text
    
    prompt = f"""
    Perbaiki kesalahan ketik dan ejaan dalam teks berikut, khususnya untuk istilah pendidikan, akademik, dan nama institusi.
    Teks mungkin mengandung singkatan atau istilah khusus universitas.
    Pertahankan maksud asli dan format teks.
    
    Contoh:
    - "undiksha" → "Undiksha" (Universitas Pendidikan Ganesha)
    - "sks" → "SKS"
    - "matkul" → "mata kuliah"
    - "prodi" → "program studi"
    
    JANGAN mengubah singkatan yang valid seperti "AI", "CPU", "IT".
    JANGAN tambahkan atau hapus kata kecuali untuk koreksi typo.
    
    Teks asli: "{text}"
    
    Teks yang dikoreksi (hanya teks, tanpa penjelasan):
    """
    try:
        response = await resources.llm.ainvoke(prompt)
        result = response.content.strip()
        return result
    except Exception as e:
        print(f"[ERROR] Gagal memperbaiki teks: {e}")
        return text

#fungsi bantu untuk memuat kamus akronim dengan caching
async def load_acronym_dict(force_refresh: bool = False) -> Dict[str, str]:
    """Muat kamus akronim dari Firestore dengan CACHING."""
    global _ACRONYM_CACHE, _ACRONYM_CACHE_TIMESTAMP
    
    import time
    current_time = time.time()
    
    # Return cache jika masih valid dan tidak force refresh
    if (_ACRONYM_CACHE is not None and 
        not force_refresh and
        current_time - _ACRONYM_CACHE_TIMESTAMP < CACHE_TTL):
        print(f"[CACHE] Using cached acronyms ({len(_ACRONYM_CACHE)} entries)")
        return _ACRONYM_CACHE
    
    # Load dari database
    acronym_dict = {}
    try:
        print("[DB] Loading acronyms from Firestore...")
        docs = resources.db.collection("acronym_expansion").stream()
        
        count = 0
        for doc in docs:
            data = doc.to_dict()
            keyword = data.get("keyword", "").strip().upper()
            full = data.get("full", "").strip()
            
            if keyword and full:
                acronym_dict[keyword] = full
                count += 1
        
        print(f"[DB] Successfully loaded {count} acronyms")
        
        # DEBUG: Print sample acronyms untuk verify
        sample_keys = list(acronym_dict.keys())[:5]
        print(f"[DB] Sample acronyms: {', '.join(sample_keys)}")
        
        # DEBUG: Check specifically for common acronyms
        check_keys = ['NIP', 'SKS', 'UNDIKSHA', 'FTK']
        for key in check_keys:
            if key in acronym_dict:
                print(f"[DB] ✓ '{key}' found in dictionary: '{acronym_dict[key]}'")
            else:
                print(f"[DB] ✗ '{key}' NOT found in dictionary")
        
        # Update cache
        _ACRONYM_CACHE = acronym_dict
        _ACRONYM_CACHE_TIMESTAMP = current_time
        
        return acronym_dict
        
    except Exception as e:
        print(f"[ERROR] Failed to load acronym dict: {e}")
        # Return empty dict atau cache lama
        return _ACRONYM_CACHE or {}

#fungsi bantu untuk ekspansi akronim dengan kombinasi
async def acronym_expansion_combinations(query: str, max_combinations: int = 8) -> List[str]:
    """
    Generate kombinasi ekspansi akronim yang UNIK dan KONSISTEN.
    
    PERBAIKAN UTAMA:
    - Normalisasi case untuk akronim yang dikenali (selalu uppercase)
    - Memastikan query "nip rektor apa" dan "NIP rektor apa" menghasilkan output identik
    """
    print(f"[ACRONYM] Processing query: '{query}'")
    
    # 1. Load acronym dictionary
    ACRONYMS = await load_acronym_dict()
    
    if not ACRONYMS:
        print("[ACRONYM] WARNING: No acronyms loaded!")
        return [query]
    
    print(f"[ACRONYM] Loaded {len(ACRONYMS)} acronyms from dictionary")
    
    # 2. Tokenisasi dengan mempertahankan punctuation dan whitespace
    tokens = re.findall(r'\b\w+\b|[^\w\s]|\s+', query)
    
    # 3. Identifikasi kata dan buat pilihan dengan NORMALISASI CASE
    word_info = []
    acronym_found = False
    normalized_tokens = []  # Untuk membuat versi normalized dari query asli
    
    for token in tokens:
        # Jika bukan alphanumeric (spasi/tanda baca), anggap fixed
        if not token.isalnum():
            word_info.append([token])
            normalized_tokens.append(token)
            continue
            
        upper_token = token.upper()
        
        # DEBUG: Print setiap token yang di-check
        if upper_token in ACRONYMS:
            acronym_found = True
            definition = ACRONYMS[upper_token]
            
            # PERBAIKAN KUNCI: Gunakan upper_token (normalized) sebagai opsi pertama
            # OPSI 1: Normalized uppercase version (NIP)
            # OPSI 2: Full expansion
            word_info.append([upper_token, definition])
            normalized_tokens.append(upper_token)
            print(f"[ACRONYM] ✓ Found: '{token}' -> normalized to '{upper_token}' -> '{definition}'")
        else:
            # Bukan akronim, hanya 1 opsi (preservasi case original untuk non-akronim)
            word_info.append([token])
            normalized_tokens.append(token)
            # DEBUG: Print token yang tidak cocok
            if token.upper() in ['NIP', 'SKS', 'UNDIKSHA']:  # Sample keywords untuk debug
                print(f"[ACRONYM] ✗ NOT FOUND in dict: '{token}' (uppercase: '{upper_token}')")
    
    if not acronym_found:
        print("[ACRONYM] No acronyms detected in query")
        return [query]
    
    print(f"[ACRONYM] Found {sum(1 for w in word_info if len(w) > 1)} acronym(s) in query")
    
    # 4. Generate semua kombinasi menggunakan itertools.product
    all_combinations = list(itertools.product(*word_info))
    
    # 5. Gabungkan token kembali menjadi string
    results = []
    for combo in all_combinations:
        combined_str = "".join(combo)
        
        # Post-processing: Bersihkan double spaces
        cleaned = re.sub(r'\s+', ' ', combined_str).strip()
        # Perbaikan spasi sebelum tanda baca
        cleaned = re.sub(r'\s+([.,!?;:])', r'\1', cleaned)
        
        results.append(cleaned)
        
        if len(results) >= max_combinations:
            break

    # 6. Pastikan unik dan query NORMALIZED berada di urutan pertama
    unique_results = []
    seen = set()
    
    # Masukkan query normalized dulu (dengan akronim dalam uppercase)
    normalized_query = "".join(normalized_tokens)
    normalized_clean = re.sub(r'\s+', ' ', normalized_query).strip()
    normalized_clean = re.sub(r'\s+([.,!?;:])', r'\1', normalized_clean)
    
    unique_results.append(normalized_clean)
    seen.add(normalized_clean)
    
    print(f"[ACRONYM] Normalized query: '{query}' -> '{normalized_clean}'")
    
    # Tambahkan hasil lainnya
    for r in results:
        if r not in seen:
            unique_results.append(r)
            seen.add(r)

    # 7. Final limit
    final_results = unique_results[:max_combinations]
    
    print(f"[ACRONYM] Generated {len(final_results)} unique combinations")
    for i, result in enumerate(final_results):
        print(f"  [{i+1}] {result}")
    
    return final_results


#fungsi bantu untuk seleksi query yang beragam
async def select_diverse_queries(queries: List[str], max_queries: int = 8) -> List[str]:
    """
    Pilih query yang beragam dari daftar queries.
    """
    if len(queries) <= max_queries:
        return queries
    
    print(f"[DIVERSITY] Selecting {max_queries} most diverse queries from {len(queries)}")
    
    # Selalu sertakan query pertama (biasanya query normalized)
    selected = [queries[0]]
    remaining = queries[1:]
    
    while len(selected) < max_queries and remaining:
        max_similarities = []
        
        for query in remaining:
            max_sim = 0
            for selected_query in selected:
                sim = SequenceMatcher(None, query, selected_query).ratio()
                max_sim = max(max_sim, sim)
            max_similarities.append((query, max_sim))
        
        if max_similarities:
            max_similarities.sort(key=lambda x: x[1])
            most_different = max_similarities[0][0]
            selected.append(most_different)
            remaining.remove(most_different)
        else:
            break
    
    print(f"[DIVERSITY] Selected queries:")
    for i, q in enumerate(selected):
        print(f"  [{i+1}] {q}")
    
    return selected


