from langchain_core.prompts import PromptTemplate
from .schemas import QueryType

# --- TEMPLATES ---

TEMPLATE_SINGLE = """Jawab pertanyaan berikut menggunakan Bahasa Indonesia yang profesional.

KONTEKS DOKUMEN:
{context}

PERTANYAAN: {question}

INSTRUKSI:
1. Jawab HANYA berdasarkan konteks di atas.
2. Jika informasi tidak ada, katakan "Maaf, informasi tidak ditemukan dalam dokumen."
3. Jangan berhalusinasi.

JAWABAN:"""

TEMPLATE_MK = """Anda adalah asisten akademik. Jawab pertanyaan spesifik tentang Mata Kuliah {mk_code}.

KONTEKS SILABUS/ATURAN:
{context}

PERTANYAAN: {question}
JAWABAN RINCI:"""

TEMPLATE_COMPARATIVE = """Lakukan perbandingan mendalam antara: {items_to_compare}.

KONTEKS:
{context}

PERTANYAAN: {question}

INSTRUKSI:
1. Buat perbandingan poin per poin atau tabel jika memungkinkan.
2. Soroti perbedaan dan persamaan utama.
JAWABAN PERBANDINGAN:"""

TEMPLATE_MIXED = """Jawab pertanyaan kompleks ini dengan komprehensif.
Fitur Pertanyaan: {query_features}

KONTEKS:
{context}

PERTANYAAN: {question}
JAWABAN:"""

# --- MAPPING ---

PROMPT_MAP = {
    QueryType.SINGLE: PromptTemplate(input_variables=["context", "question"], template=TEMPLATE_SINGLE),
    QueryType.ABBREVIATION: PromptTemplate(input_variables=["context", "question"], template=TEMPLATE_SINGLE),
    QueryType.MULTIHOP: PromptTemplate(input_variables=["context", "question"], template=TEMPLATE_SINGLE),
    
    QueryType.MK_CODE: PromptTemplate(input_variables=["context", "question", "mk_code"], template=TEMPLATE_MK),
    QueryType.COMPARATIVE: PromptTemplate(input_variables=["context", "question", "items_to_compare"], template=TEMPLATE_COMPARATIVE),
    QueryType.MIXED: PromptTemplate(input_variables=["context", "question", "query_features"], template=TEMPLATE_MIXED),
}

# --- SPECIAL PROMPTS ---

DECOMPOSE_PROMPT = PromptTemplate(
    input_variables=["question"],
    template="""Analisis pertanyaan ini dan pecah menjadi sub-pertanyaan independen (Maksimal 3) untuk pencarian informasi bertahap.
    
    PERTANYAAN ASLI: {question}
    
    Keluarkann HANYA format JSON valid:
    {{
        "sub_questions": ["Pertanyaan 1", "Pertanyaan 2"]
    }}
    """
)

SYNTHESIS_PROMPT = PromptTemplate(
    input_variables=["question", "sub_answers"],
    template="""Sintesis jawaban akhir berdasarkan temuan-temuan berikut.

    PERTANYAAN ASLI: {question}

    TEMUAN SUB-JAWABAN:
    {sub_answers}

    Gabungkan menjadi satu narasi jawaban yang koheren dan lengkap.
    JAWABAN FINAL:"""
)