from fastapi import APIRouter, Form, Depends, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from langchain_core.prompts import PromptTemplate
from typing import Optional, List, Dict
import json
import asyncio
from datetime import datetime, timezone, timedelta
from google.cloud import firestore
from src.core.security import get_current_user
from src.core.preprocessing_query import (
    acronym_expansion_combinations, 
    resolve_pronouns_and_create_standalone_query, 
    correct_typos_and_normalize,
    select_diverse_queries
)
from src.core.retrieval import rrf_retriever_chain
import src.resources as resources

router = APIRouter(prefix="/api", tags=["Chat"])

@router.post("/ask")
async def ask_question(
    background_tasks: BackgroundTasks,
    question: str = Form(...),
    session_id: Optional[str] = Form(None),
    thinking: Optional[bool] = Form(False),
    user: dict = Depends(get_current_user)
):
    """
    Endpoint utama untuk chat dengan RAG system.
    Mendukung: typo correction, pronoun resolution, acronym expansion, parallel retrieval.
    """
    
    # 1. Validasi resources
    if not resources.db or not resources.llm or not resources.qdrant_client:
        raise HTTPException(
            status_code=503, 
            detail="Layanan backend belum siap sepenuhnya. Silakan coba beberapa saat lagi."
        )

    user_id = user['uid']
    user_name = 'Teman'  # Default name

    # 2. Ambil nama user dari Firestore
    try:
        user_doc = resources.db.collection('users').document(user_id).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            user_name = user_data.get('displayName', user_data.get('name', 'Teman'))
            print(f"[USER] User: {user_name} (ID: {user_id[:8]}...)")
    except Exception as e:
        print(f"[WARNING] Gagal ambil profil user: {e}")

    # 3. Ambil chat history untuk context
    chat_history = []
    if session_id:
        try:
            print(f"[HISTORY] Loading chat history for session: {session_id}")
            msgs_ref = resources.db.collection('chat_sessions').document(session_id)\
                .collection('messages')\
                .order_by('created_at', direction=firestore.Query.DESCENDING)\
                .limit(6)\
                .stream()
            
            temp_msgs = [m.to_dict() for m in msgs_ref]
            temp_msgs.reverse() 
            
            temp_q = None
            for msg in temp_msgs:
                if msg.get('role') == 'user': 
                    temp_q = msg.get('content')
                elif msg.get('role') == 'bot' and temp_q:
                    chat_history.append((temp_q, msg.get('content')))
                    temp_q = None
            
            print(f"[HISTORY] Loaded {len(chat_history)} conversation pairs")
            
        except Exception as e:
            print(f"[WARNING] Gagal ambil riwayat chat: {e}")

    # 4. Preprocessing Query Pipeline
    processed_question = question
    preprocessing_steps = []
    
    # Step 1: Typo Correction
    original_question = processed_question
    processed_question = await correct_typos_and_normalize(processed_question)
    if processed_question != original_question:
        preprocessing_steps.append(f"Typo correction: '{original_question}' → '{processed_question}'")
    
    # Step 2: Pronoun Resolution (jika ada chat history)
    if chat_history:
        original_question = processed_question
        processed_question = await resolve_pronouns_and_create_standalone_query(
            processed_question, 
            chat_history
        )
        if processed_question != original_question:
            preprocessing_steps.append(f"Pronoun resolution: '{original_question}' → '{processed_question}'")
    
    # Step 3: Acronym Expansion
    original_question = processed_question
    list_of_queries = await acronym_expansion_combinations(
        processed_question, 
        max_combinations=10
    )
    
    if len(list_of_queries) > 1:
        preprocessing_steps.append(f"Acronym expansion: generated {len(list_of_queries)} variations")
    
    # Step 4: Select diverse queries (jika terlalu banyak)
    if len(list_of_queries) > 8:
        list_of_queries = await select_diverse_queries(list_of_queries, max_queries=8)
        preprocessing_steps.append(f"Diverse selection: selected {len(list_of_queries)} most diverse queries")
    
    # Log preprocessing steps
    if preprocessing_steps:
        print(f"[PREPROCESSING] Steps applied:")
        for step in preprocessing_steps:
            print(f"  - {step}")
    
    print(f"[PREPROCESSING] Final query: '{processed_question}'")
    print(f"[PREPROCESSING] Query variations: {len(list_of_queries)}")
    for i, q in enumerate(list_of_queries[:3]):  # Show first 3
        print(f"  {i+1}. '{q}'")
    if len(list_of_queries) > 3:
        print(f"  ... and {len(list_of_queries)-3} more")

    # 5. Execute RAG Retrieval Chain
    print(f"[RAG] Starting retrieval with thinking={thinking}")
    start_time = datetime.now()
    
    try:
        result_rag = await rrf_retriever_chain(
            question=processed_question, 
            list_of_queries=list_of_queries, 
            thinking=thinking
        )
        
        retrieval_time = (datetime.now() - start_time).total_seconds()
        print(f"[RAG] Retrieval completed in {retrieval_time:.2f}s")
        
        retrieved_docs = result_rag.get("source_documents", [])
        unique_docs_found = result_rag.get("unique_docs_found", 0)
        total_raw_docs = result_rag.get("total_raw_docs", 0)
        
        print(f"[RAG] Retrieved {len(retrieved_docs)} documents for answer")
        print(f"[RAG] Unique docs: {unique_docs_found}, Raw docs: {total_raw_docs}")
        
    except Exception as e:
        print(f"[ERROR] RAG retrieval failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500, 
            detail="Gagal melakukan pencarian informasi. Silakan coba lagi."
        )

    # 6. Format context untuk final LLM call
    if retrieved_docs:
        final_context = "\n\n".join([
            f"Sumber: {doc.metadata.get('doc_title') or 'Tanpa Judul'}\n"
            f"Isi: {doc.page_content}"
            for doc in retrieved_docs
        ])
        print(f"[CONTEXT] Context length: {len(final_context)} chars")
    else:
        final_context = "Tidak ada konteks relevan ditemukan."
        print(f"[WARNING] No documents retrieved!")

    # 7. Prepare chat history untuk prompt
    history_text = "\n".join([f"User: {q}\nDéFi: {a}" for q, a in chat_history])
    if history_text:
        print(f"[HISTORY] History length: {len(history_text)} chars")

    # 8. Final Prompt untuk LLM dengan persona DéFi
    prompt_template = PromptTemplate(
        input_variables=["chat_history_text", "context", "user_name", "question"],
        template="""Anda adalah DéFi, asisten cerdas untuk Universitas Pendidikan Ganesha (Undiksha) ciptaan Fieter.
        Gunakan bahasa Indonesia yang profesional namun ramah. Jawab dengan jelas dan informatif.

        {PERSONA_GUIDELINES}

        {RESPONSE_FORMAT}

        {NO_CONTEXT_HANDLING}

        Riwayat Percakapan:
        {chat_history_text}

        Konteks dari Database:
        {context}

        Pertanyaan Pengguna ({user_name}):
        {question}

        Jawaban DéFi:"""
    )

        # Template parts
    persona_guidelines = """
        Pedoman Persona DéFi:
        1. Identitas: Anda adalah DéFi, asisten virtual Undiksha
        2. Tujuan: Membantu mahasiswa, dosen, dan staf Undiksha
        3. Sikap: Ramah, profesional, membantu
        4. Pengetahuan: Terbatas pada informasi yang diberikan dalam konteks
            """.strip()

    response_format = """
        Format Jawaban:
        1. Gunakan kalimat lengkap (Subjek + Predikat + Objek)
        2. Sertakan kata kunci pertanyaan dalam jawaban
        3. Jangan gunakan kata ganti ambigu
        4. Langsung jawab intinya tanpa pembukaan seperti "Berdasarkan konteks..."
        5. Jika ada informasi penting dari beberapa sumber, gabungkan dengan koheren
            """.strip()

    no_context_handling = """
        Jika Tidak Ada Konteks:
        - Jika konteks kosong atau tidak relevan, katakan: "Maaf, saya tidak menemukan informasi tentang itu dalam basis data Undiksha."
        - Jangan mengarang jawaban
        - Tawarkan bantuan lain jika memungkinkan
            """.strip()

    # Format final prompt
    final_prompt_str = prompt_template.format(
        chat_history_text=history_text if history_text else "Tidak ada riwayat percakapan.",
        context=final_context,
        user_name=user_name,
        question=processed_question,
        PERSONA_GUIDELINES=persona_guidelines,
        RESPONSE_FORMAT=response_format,
        NO_CONTEXT_HANDLING=no_context_handling
    )


    # Streaming response
    async def event_generator():
        full_answer = ""
        llm_chunks = []
            
        try:
            print(f"[LLM] Invoking LLM (streaming)...")
            llm_start_time = datetime.now()
                
            # Stream LLM response
            async for chunk in resources.llm.astream(final_prompt_str):
                content = chunk.content
                full_answer += content
                llm_chunks.append(content)
                    
                # Stream chunk to client
                yield f"data: {json.dumps({'type': 'text', 'content': content})}\n\n"
                await asyncio.sleep(0.01)
                
            llm_time = (datetime.now() - llm_start_time).total_seconds()
            print(f"[LLM] Stream completed in {llm_time:.2f}s")
            print(f"[LLM] Answer length: {len(full_answer)} chars")
            
        except Exception as e:
            print(f"[ERROR] LLM streaming failed: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': 'Terjadi kesalahan dalam memproses jawaban'})}\n\n"
            return
            
        # Save to database
        background_tasks.add_task(
                save_to_database, 
                question, full_answer, user_id, session_id
            )
            
        # Send session_id
        yield f"data: {json.dumps({'type': 'session_id', 'session_id': session_id})}\n\n"
            
        # Send sources
        sources_data = []
        print(f"Retrieved docs: {retrieved_docs}")
        for doc in retrieved_docs:
            sources_data.append({
                "content": doc.page_content,
                "title": doc.metadata.get("doc_title") or "Tanpa Judul",
                "source": doc.metadata.get("source_file", "Unknown"),
                "relevance_score": f"{doc.metadata.get('relevance_score', 0.0):.3f}"
            })
            
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources_data})}\n\n"
            
        # Send metadata
        metadata = {
            "processing_steps": preprocessing_steps,
            "query_variations_count": len(list_of_queries),
            "documents_found": len(retrieved_docs),
            "thinking_mode": thinking,
            "retrieval_time": f"{retrieval_time:.2f}s",
            "llm_time": f"{llm_time:.2f}s"
        }
        yield f"data: {json.dumps({'type': 'metadata', 'metadata': metadata})}\n\n"
            
        # Send done signal
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Type": "text/event-stream; charset=utf-8"
        }
    )

async def save_to_database(
    original_question: str,
    answer: str,
    user_id: str,
    session_id: Optional[str] = None
) -> str:
    """Save chat session and messages to Firestore."""
    try:
        current_time = datetime.now(timezone.utc)
        
        # Create new session if needed
        if not session_id:
            doc_ref = resources.db.collection('chat_sessions').document()
            session_id = doc_ref.id
            
            doc_ref.set({
                'userId': user_id,
                'title': original_question[:80] + ("..." if len(original_question) > 80 else ""),
                'created_at': current_time,
                'updated_at': current_time,
                'message_count': 0,
                'metadata': {
                    'original_question': original_question,
                }
            })
            print(f"[DB] Created new session: {session_id}")
        
        # Update session timestamp and count
        session_ref = resources.db.collection('chat_sessions').document(session_id)
        session_ref.update({
            'updated_at': current_time,
            'message_count': firestore.Increment(2)  # User + bot messages
        })
        
        # Save messages
        messages_col = session_ref.collection('messages')
        batch = resources.db.batch()
        
        # User message
        batch.set(messages_col.document(), {
            'role': 'user',
            'content': original_question,
            'created_at': current_time
        })
        
        # Bot message
        batch.set(messages_col.document(), {
            'role': 'bot',
            'content': answer,
            'created_at': current_time + timedelta(milliseconds=10)
        })

        batch.commit()
        print(f"[DB] Saved messages to session: {session_id}")
        
        return session_id
        
    except Exception as e:
        print(f"[ERROR] Failed to save to database: {e}")
        return session_id or ""

from fastapi.encoders import jsonable_encoder

@router.get("/chats")
async def get_chat_sessions(user: dict = Depends(get_current_user)):
    try:
        user_id = user['uid']
        print(f"\n[DEBUG] === FETCHING CHATS FOR USER: {user_id} ===")
        
        # 1. Ambil koleksi
        sessions_ref = resources.db.collection('chat_sessions')
        

        query = sessions_ref.where('userId', '==', user_id).limit(50)
        try:
            query = query.order_by('updated_at', direction=firestore.Query.DESCENDING)
            print("[DEBUG] Using strategy: userId + updated_at DESC")
        except:
            print("[DEBUG] Falling back to unordered query (Index issues?)")

        docs = query.stream()
        
        sessions_list = []
        for doc in docs:
            data = doc.to_dict()
            
            # Buat struktur yang sangat standar
            session_item = {
                'id': doc.id,
                'title': data.get('title', 'No Title'),
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at', data.get('created_at')),
                'message_count': data.get('message_count', 0)
            }
            sessions_list.append(session_item)
            
        print(f"[DEBUG] Total sessions found: {len(sessions_list)}")
        
        # 3. Kirim dengan jsonable_encoder agar Timestamp otomatis jadi String
        return JSONResponse(content=jsonable_encoder(sessions_list))
        
    except Exception as e:
        print(f"[ERROR] Gagal total di get_chat_sessions: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



from fastapi.encoders import jsonable_encoder

@router.get("/chats/{session_id}")
async def get_chat_messages(session_id: str, user: dict = Depends(get_current_user)):
    """
    Mengambil pesan dengan kompatibilitas penuh dan error handling yang lebih baik.
    """
    try:
        print(f"[DEBUG] Fetching messages for session: {session_id}")
        
        # 1. Validasi Sesi
        sess_ref = resources.db.collection('chat_sessions').document(session_id)
        sess = sess_ref.get()
        
        if not sess.exists:
            print("[DEBUG] Session not found")
            raise HTTPException(status_code=404, detail="Sesi tidak ditemukan")
        
        sess_data = sess.to_dict()
        if sess_data.get('userId') != user['uid']:
            raise HTTPException(status_code=403, detail="Akses ditolak")
             
        # 2. Ambil Pesan dengan strategi yang lebih aman
        messages = []
        try:
            # Coba dengan order_by jika index sudah tersedia
            msgs_stream = sess_ref.collection('messages').order_by('created_at').stream()
        except Exception as e:
            if "index" in str(e).lower() or "requires index" in str(e).lower():
                print(f"[WARNING] Index error, using unordered query: {e}")
                # Fallback ke query tanpa order
                msgs_stream = sess_ref.collection('messages').stream()
            else:
                raise
        
        # 3. Proses pesan dengan error handling per dokumen
        msg_count = 0
    # Di dalam loop yang memproses messages dari Firestore
        for msg in msgs_stream:
            try:
                m_data = msg.to_dict()
                msg_count += 1
                
                # Format sources dengan struktur yang konsisten
                formatted_sources = []
                if m_data.get('sources'):
                    for src in m_data.get('sources', []):
                        formatted_sources.append({
                            # Format yang diharapkan frontend
                            "metadata": src.get('title', 'Tanpa Judul'),
                            "page_content": src.get('source', 'Unknown'),
                            
                            # Tambahan info (opsional)
                            "title": src.get('title', 'Tanpa Judul'),
                            "relevance": src.get('relevance', 0.0)
                        })
                
                safe_msg = {
                    "id": msg.id,
                    "role": m_data.get('role', 'unknown'),
                    "content": m_data.get('content', ''),
                    "created_at": m_data.get('created_at'),
                    "createdAt": m_data.get('created_at'),
                    
                    # PERBAIKAN: Gunakan formatted_sources
                    "sources": formatted_sources
                }
                
                safe_msg = {k: v for k, v in safe_msg.items() if v is not None}
                messages.append(safe_msg)
                
            except Exception as e:
                print(f"[WARNING] Error processing message {msg.id}: {e}")
                continue
        
        # 4. Urutkan secara manual jika query tidak terurut
        if len(messages) > 1:
            try:
                # Coba urutkan berdasarkan created_at
                messages.sort(key=lambda x: x.get('created_at') or datetime.min)
            except:
                # Jika tidak bisa diurutkan, biarkan seperti aslinya
                pass
        
        # 5. Siapkan response dengan format yang konsisten
        response_data = {
            "success": True,
            "session_id": session_id,
            "sessionId": session_id,  # camelCase alias
            "title": sess_data.get('title', 'Percakapan'),
            
            # Timestamps session
            "created_at": sess_data.get('created_at'),
            "createdAt": sess_data.get('created_at'),
            "updated_at": sess_data.get('updated_at'),
            "updatedAt": sess_data.get('updated_at'),
            
            # Metadata
            "message_count": sess_data.get('message_count', 0),
            "messages": messages
        }
        
        # 6. Gunakan jsonable_encoder untuk serialization aman
        return JSONResponse(content=jsonable_encoder(response_data))
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Critical failure in get_chat_messages: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500, 
            detail=f"Gagal memuat percakapan: {str(e)[:100]}"
        )

@router.delete("/chats/{session_id}")
async def delete_chat_session(session_id: str, user: dict = Depends(get_current_user)):
    """Delete a chat session and all its messages."""
    try:
        # Verify session ownership
        sess_ref = resources.db.collection('chat_sessions').document(session_id)
        sess = sess_ref.get()
        
        if not sess.exists:
            raise HTTPException(status_code=404, detail="Sesi tidak ditemukan")
        
        sess_data = sess.to_dict()
        if sess_data.get('userId') != user['uid']:
            raise HTTPException(status_code=403, detail="Akses ditolak")
        
        # Delete all messages first
        batch = resources.db.batch()
        messages = sess_ref.collection('messages').stream()
        
        msg_count = 0
        for msg in messages:
            batch.delete(msg.reference)
            msg_count += 1
        
        # Delete session
        batch.delete(sess_ref)
        batch.commit()
        
        
        return {
            'success': True,
            'message': 'Sesi berhasil dihapus',
            'session_id': session_id,
            'messages_deleted': msg_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Failed to delete session: {e}")
        raise HTTPException(status_code=500, detail="Gagal menghapus sesi")

