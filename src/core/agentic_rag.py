import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from langchain_core.documents import Document

# Imports dari modul internal kita
from .schemas import QueryType, ProcessedQuery, AgenticResponse
from .prompts import PROMPT_MAP, SYNTHESIS_PROMPT
from .query_processor import QueryProcessor

class AgenticRAGSystem:
    def __init__(self, db, llm, qdrant_client):
        self.db = db
        self.llm = llm
        self.qdrant_client = qdrant_client
        self.query_processor = QueryProcessor(db, llm)
        
        # Cache Sederhana (In-Memory)
        self.response_cache: Dict[str, AgenticResponse] = {}
        
        # --- HANDLER MAPPING (Strategy Pattern) ---
        # Menghindari if-else panjang. O(1) Access.
        self.handlers = {
            QueryType.SINGLE: self._handle_single_query,
            QueryType.ABBREVIATION: self._handle_single_query, # Re-use handler
            QueryType.MK_CODE: self._handle_mk_query,
            QueryType.COMPARATIVE: self._handle_comparative_query,
            QueryType.MULTIHOP: self._handle_multihop_query,
            QueryType.MIXED: self._handle_mixed_query,
            QueryType.UNKNOWN: self._handle_single_query
        }

    async def process_query(self, query: str, thinking: bool = False) -> AgenticResponse:
        """Main Entry Point"""
        start_time = datetime.now(timezone.utc)
        
        # 1. Cek Cache
        cache_key = f"{query}_{thinking}"
        if cache_key in self.response_cache:
            return self.response_cache[cache_key]

        try:
            # 2. Preprocessing & Routing
            processed = await self.query_processor.process(query)
            print(f"[AGENT] Intent: {processed.query_type.value} | MK: {processed.mk_codes}")

            # 3. Pilih Handler yang sesuai
            handler = self.handlers.get(processed.query_type, self._handle_single_query)
            
            # 4. Eksekusi Handler
            result = await handler(processed, thinking)
            
            # 5. Construct Response
            response = AgenticResponse(
                answer=result["answer"],
                source_documents=result["source_documents"],
                query_type=processed.query_type.value,
                processing_time=(datetime.now(timezone.utc) - start_time).total_seconds(),
                sub_answers=result.get("sub_answers"),
                metadata={"mk_codes": processed.mk_codes}
            )
            
            # 6. Simpan Cache (Simple LRU logic bisa ditambahkan nanti)
            self.response_cache[cache_key] = response
            return response

        except Exception as e:
            print(f"[SYSTEM ERROR] {e}")
            import traceback
            traceback.print_exc()
            return AgenticResponse(
                answer="Maaf, terjadi kesalahan internal sistem saat memproses pertanyaan Anda.",
                source_documents=[],
                query_type="error",
                processing_time=0.0
            )

    # --- RETRIEVAL WRAPPER ---
    async def _retrieve(self, query: str, k: int, thinking: bool, all_mk_codes: bool = False) -> List[Document]:
        """
        Wrapper ke fungsi retrieval Qdrant.
        Pastikan Anda memiliki fungsi 'retrieve_from_qdrant' di project Anda.
        """
        # Contoh pemanggilan dummy/placeholder. Ganti dengan import yang benar.
        # from .retrieval import retrieve_from_qdrant
        # return await retrieve_from_qdrant(query, self.db, k=k, thinking=thinking, all_mk_codes=all_mk_codes)
        
        # --- MOCK IMPLEMENTATION (Hapus ini jika sudah integrasi Qdrant) ---
        print(f"[Retrieval] Query: '{query}' | k={k} | MK_Mode={all_mk_codes}")
        # Simulasi return dokumen kosong agar kode jalan
        return [] 
        # ------------------------------------------------------------------

    def _format_docs(self, docs: List[Document]) -> str:
        """Format dokumen menjadi string untuk prompt"""
        if not docs:
            return "Tidak ada dokumen relevan ditemukan."
        return "\n\n".join([f"[Doc {i+1}]: {d.page_content}" for i, d in enumerate(docs)])

    # --- SPECIFIC HANDLERS ---

    async def _handle_single_query(self, processed: ProcessedQuery, thinking: bool) -> Dict:
        # Retrieve
        docs = await self._retrieve(processed.expanded, k=5 if thinking else 3, thinking=thinking)
        
        # Generate
        chain = (
            {"context": lambda x: self._format_docs(docs), "question": RunnablePassthrough()}
            | PROMPT_MAP[QueryType.SINGLE]
            | self.llm
            | StrOutputParser()
        )
        answer = await chain.ainvoke(processed.expanded)
        return {"answer": answer, "source_documents": docs}

    async def _handle_mk_query(self, processed: ProcessedQuery, thinking: bool) -> Dict:
        mk_code = processed.mk_codes[0] if processed.mk_codes else "MK Terkait"
        
        # Retrieve dengan mode MK (mungkin ambil syllabus lengkap)
        docs = await self._retrieve(processed.expanded, k=5, thinking=thinking, all_mk_codes=True)
        
        chain = (
            {
                "context": lambda x: self._format_docs(docs),
                "question": RunnablePassthrough(),
                "mk_code": lambda x: mk_code
            }
            | PROMPT_MAP[QueryType.MK_CODE]
            | self.llm
            | StrOutputParser()
        )
        answer = await chain.ainvoke(processed.expanded)
        return {"answer": answer, "source_documents": docs}

    async def _handle_comparative_query(self, processed: ProcessedQuery, thinking: bool) -> Dict:
        items = ", ".join(processed.comparison_items) if processed.comparison_items else "item terkait"
        
        docs = await self._retrieve(processed.expanded, k=6, thinking=thinking)
        
        chain = (
            {
                "context": lambda x: self._format_docs(docs),
                "question": RunnablePassthrough(),
                "items_to_compare": lambda x: items
            }
            | PROMPT_MAP[QueryType.COMPARATIVE]
            | self.llm
            | StrOutputParser()
        )
        answer = await chain.ainvoke(processed.expanded)
        return {"answer": answer, "source_documents": docs}

    async def _handle_multihop_query(self, processed: ProcessedQuery, thinking: bool) -> Dict:
        # 1. Decompose
        sub_queries = await self.query_processor.decompose_query(processed.expanded)
        print(f"[Multihop] Steps: {sub_queries}")
        
        sub_answers = []
        all_docs = []
        
        # 2. Sequential Processing
        for q in sub_queries:
            # Retrieve sedikit saja per sub-query
            docs = await self._retrieve(q, k=2, thinking=thinking)
            
            # Jawab sementara
            chain = (
                {"context": lambda x: self._format_docs(docs), "question": RunnablePassthrough()}
                | PROMPT_MAP[QueryType.SINGLE]
                | self.llm
                | StrOutputParser()
            )
            ans = await chain.ainvoke(q)
            
            sub_answers.append(f"Tanya: {q}\nJawab: {ans}")
            all_docs.extend(docs)
        
        # 3. Synthesis Final
        final_chain = (
            {"question": lambda x: processed.expanded, "sub_answers": lambda x: "\n\n".join(sub_answers)}
            | SYNTHESIS_PROMPT
            | self.llm
            | StrOutputParser()
        )
        final_answer = await final_chain.ainvoke(processed.expanded)
        
        # Dedup docs
        unique_docs = list({d.page_content: d for d in all_docs}.values())
        
        return {
            "answer": final_answer, 
            "source_documents": unique_docs[:5],
            "sub_answers": sub_answers
        }

    async def _handle_mixed_query(self, processed: ProcessedQuery, thinking: bool) -> Dict:
        # Strategi: Retrieve lebih banyak + Prompt Instruksi Kuat
        docs = await self._retrieve(processed.expanded, k=8, thinking=thinking)
        
        features_desc = f"Kompleksitas Level {processed.detected_features.get('complexity', 3)}"
        if processed.mk_codes:
            features_desc += f", Terkait MK: {processed.mk_codes}"
        
        chain = (
            {
                "context": lambda x: self._format_docs(docs),
                "question": RunnablePassthrough(),
                "query_features": lambda x: features_desc
            }
            | PROMPT_MAP[QueryType.MIXED]
            | self.llm
            | StrOutputParser()
        )
        answer = await chain.ainvoke(processed.expanded)
        return {"answer": answer, "source_documents": docs}