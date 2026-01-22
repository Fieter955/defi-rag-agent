from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from langchain_core.documents import Document
from langchain_core.pydantic_v1 import BaseModel, Field

# --- ENUMS ---
class QueryType(str, Enum):
    SINGLE = "single"              # Pertanyaan fakta langsung
    MK_CODE = "mk_code"            # Spesifik kode mata kuliah
    MULTIHOP = "multihop"          # Butuh penalaran bertahap
    COMPARATIVE = "comparative"    # Membandingkan dua hal
    ABBREVIATION = "abbreviation"  # Definisi singkatan
    MIXED = "mixed"                # Kombinasi kompleks
    UNKNOWN = "unknown"            # Fallback

# --- PYDANTIC MODELS (Untuk Output LLM Router) ---
class QueryClassification(BaseModel):
    """Struktur output yang dipaksa keluar dari LLM Router"""
    query_type: str = Field(..., description="Jenis pertanyaan: 'single', 'mk_code', 'multihop', 'comparative', 'mixed'")
    items_to_compare: List[str] = Field(default=[], description="Jika comparative, sebutkan item yang dibandingkan")
    complexity_score: int = Field(..., description="Skala 1-5 tingkat kesulitan")
    reasoning: str = Field(..., description="Alasan singkat pemilihan tipe")

# --- DATACLASSES (Internal App Data) ---
@dataclass
class ProcessedQuery:
    """Hasil olahan QueryProcessor"""
    original: str
    expanded: str
    query_type: QueryType
    mk_codes: List[str]
    entities: List[str]
    comparison_items: List[str]
    sub_queries: List[str] = None
    detected_features: Dict[str, bool] = field(default_factory=dict)

@dataclass
class AgenticResponse:
    """Output akhir ke User/Frontend"""
    answer: str
    source_documents: List[Document]
    query_type: str
    processing_time: float
    sub_answers: List[Dict] = None
    metadata: Dict = field(default_factory=dict)