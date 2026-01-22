import re
from typing import List, Dict
from langchain_core.output_parsers import JsonOutputParser

from .schemas import ProcessedQuery, QueryType, QueryClassification
from .prompts import DECOMPOSE_PROMPT

class QueryProcessor:
    def __init__(self, db, llm):
        self.db = db
        self.llm = llm
        
        # Inisialisasi Router LLM dengan Structured Output (Pydantic)
        # Pastikan model LLM mendukung function calling (misal: gpt-3.5/4, atau ollama json mode)
        self.router_llm = llm.with_structured_output(QueryClassification)
        
        # Regex Pattern untuk Kode MK (Cepat & Akurat)
        # Menangkap format: IF123, IF 123, IF-123, KU1001
        self.mk_pattern = r'\b[A-Z]{2,4}[\s-]?\d{3,4}\b'

    async def _extract_mk_codes(self, text: str) -> List[str]:
        """Regex extraction untuk kode mata kuliah"""
        matches = re.findall(self.mk_pattern, text.upper())
        # Normalisasi: Hilangkan spasi/strip (IF 123 -> IF123)
        return [re.sub(r'[\s-]', '', m) for m in matches]

    async def _classify_with_llm(self, query: str) -> QueryClassification:
        """Menggunakan LLM untuk memahami niat user (Router)"""
        prompt = (
            f"Analisis pertanyaan akademik berikut: \"{query}\". "
            "Tentukan jenisnya: single (fakta), mk_code (detail matkul), multihop (logika bertingkat), "
            "comparative (membandingkan), atau mixed."
        )
        try:
            return await self.router_llm.ainvoke(prompt)
        except Exception as e:
            print(f"[Router Error] {e}. Fallback to SINGLE.")
            return QueryClassification(
                query_type="single", 
                complexity_score=1, 
                reasoning="Fallback error", 
                items_to_compare=[]
            )

    async def decompose_query(self, query: str) -> List[str]:
        """Memecah pertanyaan kompleks menjadi sub-pertanyaan"""
        try:
            chain = DECOMPOSE_PROMPT | self.llm | JsonOutputParser()
            result = await chain.ainvoke({"question": query})
            return result.get("sub_questions", [query])
        except Exception as e:
            print(f"[Decompose Error] {e}")
            return [query]

    async def process(self, query: str) -> ProcessedQuery:
        # 1. Ekstraksi Fitur Pasti (Regex)
        mk_codes = await self._extract_mk_codes(query)
        
        # 2. Klasifikasi Cerdas (LLM)
        classification = await self._classify_with_llm(query)
        
        # 3. Logika Penentuan Akhir (Hybrid Logic)
        final_type_str = classification.query_type
        
        # Override Rule: Jika Regex menemukan MK Code, prioritas tinggi ke MK_CODE
        # kecuali LLM mendeteksi perbandingan (comparative)
        if mk_codes and final_type_str != "comparative":
            final_type_str = "mk_code"
        elif mk_codes and final_type_str == "comparative":
            final_type_str = "mixed" # MK + Comparative

        # Convert string ke Enum
        try:
            final_type = QueryType(final_type_str)
        except ValueError:
            final_type = QueryType.UNKNOWN

        return ProcessedQuery(
            original=query,
            expanded=query, # Placeholder jika ingin tambah ekspansi singkatan
            query_type=final_type,
            mk_codes=mk_codes,
            entities=[], 
            comparison_items=classification.items_to_compare,
            detected_features={"complexity": classification.complexity_score}
        )