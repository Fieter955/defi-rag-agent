import resources
import string


#Ini adalah fungsi untuk merubah pertanyaan ambigu seperti "Berapa jumlah SKSnya?" menjadi "Berapa jumlah SKS Prodi Ilmu Komputer Semester 1?". Intinya agar pertanyaan itu independent dari history chat sehingga bisa retrieve chunk yang sesuai
async def resolve_pronouns_and_create_standalone_query(question: str, chat_history: list) -> str:
    """
    Menganalisis pertanyaan saat ini dan riwayat obrolan untuk menyelesaikan kata ganti
    dan membuat pertanyaan yang berdiri sendiri (standalone).
    """
    if not chat_history or not resources.llm:
        return question

    formatted_history = "\n".join([f"User: {q}\nBot: {a}" for q, a in chat_history])
    
    prompt = f"""
    Buatkan saya kalimat baru yang tidak ambigu jika dibaca dengan cara anda lihat riwayat percakapan lalu putuskan lah kalimat baru atau pertanyaan baru yang lebih sesuai. Return hanya sebuah string kalimat tersebut!!!
    
    ---
    
    Riwayat Percakapan:
    {formatted_history}
    
    Pertanyaan Saat Ini: "{question}"
    Pertanyaan yang Diubah: 
    """
    try:
        response = await resources.llm.ainvoke(prompt)
        return response.content.strip()
    except Exception as e:
        print(f"Gagal melakukan resolusi kata ganti: {e}")
        return question

    

#Fungsi untuk memperbaiki typo menggunakan LLM dari GROQ
async def correct_typos_and_normalize(text: str) -> str:
    """
    Memperbaiki typo dan menormalisasi teks menggunakan LLM.
    """
    if not resources.llm:
        return text
    prompt = f"""
    Anda adalah asisten AI ahli yang berspesialisasi dalam mengoreksi teks Bahasa Indonesia khususnya dalam bidang pendidikan di universitas, termasuk kesalahan ketik, ejaan, dan kesalahan tata bahasa minor, tanpa mengubah makna intinya. Tugas Anda adalah menganalisis teks pengguna dan memberikan versi yang telah diperbaiki. Keluarannya harus berupa kalimat yang telah diperbaiki saja, tanpa teks, narasi, atau format markdown lainnya.
    
    Teks asli: "{text}"
    Teks yang dikoreksi: 
    """
    try:
        response = await resources.llm.ainvoke(prompt)
        return response.content.strip()
    except Exception as e:
        print(f"Gagal memperbaiki teks: {e}")
        return text


#Fungsi untuk merubah singkatan seperti "BK" menjadi "Bimbingan Konseling". Contoh pertanyaan sebelum pakai fungsi : "Apa makna logo undiksha?" menjadi "Apa makna logo Universitaas Pendidikan Ganesha". Daftar singkatan ada didatabase dan bisa ditambah lagi dengan menjalankan lewat fungsi "upload_acronyms"
import string

async def acronym_expansion(query: str):
    texts = query.split()
    expanded = []
    ACRONYMS = await load_acronym_dict()
    
    for text in texts:
        clean_key = text.strip(string.punctuation)
        if clean_key.upper() in ACRONYMS:
            definition = ACRONYMS[clean_key.upper()]
            formatted_text = f"{clean_key} ({definition})"
            new_text = text.replace(clean_key, formatted_text)
            expanded.append(new_text)
        else:
            expanded.append(text)
    final_query = " ".join(expanded)
    return final_query

# Fungsi load dictionary
async def load_acronym_dict():
    acronym_dict  = {}
    docs = resources.db.collection("acronym_expansion").stream() 
    for d in docs:
        acronym_dict[d.get("keyword").upper()] = d.get("full")
    return acronym_dict

