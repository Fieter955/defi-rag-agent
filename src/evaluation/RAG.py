from preprocessing_query import acronym_expansion
from langchain_core.prompts import PromptTemplate
import resources
from retrieval_qwen import retrieve_from_qdrant




async def rrf_retriever_chain(question: str):
    """Custom retriever chain that returns top 3 documents for the given query."""
    
    #query_expansion = await acronym_expansion(question)
    #print(f"[PROCESS 1] Query Expansion: {query_expansion}")

    retrieved_docs = await retrieve_from_qdrant(question, k=3, thinking=True)

    prompt_text = """
    jika jawaban tidak didukung konteks, bilang tidak tau

    jika konteks mendukung, Jawablah dengan kalimat lengkap (Subject + Predicate + Object) tanpa kata ganti sehingga kata kunci pertanyaan selalu ada di dalam jawaban.Jangan gunakan kalimat pembuka seperti "Berdasarkan konteks..." atau "Menurut dokumen...". Langsung jawab intinya.
    
    Contoh:
    Tanya: Siapa Rektor universitas x saat ini?
    Jawab: Rektor universitas x saat ini adalah Prof. Budi Santoso. (JANGAN JAWAB: Prof. Budi Santoso)

    Konteks dari Database:
    {context}

    Pertanyaan Pengguna:
    {question}

    
    Jawaban:
    """

    QA_PROMPT = PromptTemplate(
        input_variables=["context", "question"],
        template=prompt_text
    )

    final_prompt = QA_PROMPT.format(
        context=retrieved_docs,
        question=question
    )

    #response_llm = await resources.llm.ainvoke(final_prompt)
    response_llm = await resources.llm.ainvoke(final_prompt)

    
    return {"answer": response_llm.content.strip(), "source_documents": retrieved_docs}



async def rrf_retriever_chain_gemma(question: str):
    """Custom retriever chain that returns top 3 documents for the given query."""
    
    #query_expansion = await acronym_expansion(question)
    #print(f"[PROCESS 1] Query Expansion: {query_expansion}")

    retrieved_docs = await retrieve_from_qdrant(question, k=3, thinking=False)

    prompt_text = """
    jika jawaban tidak didukung konteks, bilang tidak tau

    jika konteks mendukung, Jawablah dengan kalimat lengkap (Subject + Predicate + Object) tanpa kata ganti sehingga kata kunci pertanyaan selalu ada di dalam jawaban.Jangan gunakan kalimat pembuka seperti "Berdasarkan konteks..." atau "Menurut dokumen...". Langsung jawab intinya.
    
    Contoh:
    Tanya: Siapa Rektor universitas x saat ini?
    Jawab: Rektor universitas x saat ini adalah Prof. Budi Santoso. (JANGAN JAWAB: Prof. Budi Santoso)

    Konteks dari Database:
    {context}

    Pertanyaan Pengguna:
    {question}

    
    Jawaban:
    """

    QA_PROMPT = PromptTemplate(
        input_variables=["context", "question"],
        template=prompt_text
    )

    final_prompt = QA_PROMPT.format(
        context=retrieved_docs,
        question=question
    )

    #response_llm = await resources.llm.ainvoke(final_prompt)
    response_llm = await resources.llm_gemma.ainvoke(final_prompt)

    
    return {"answer": response_llm, "source_documents": retrieved_docs}



async def rrf_retriever_chain_gemma3_12b(question: str):
    """Custom retriever chain that returns top 3 documents for the given query."""
    
    #query_expansion = await acronym_expansion(question)
    #print(f"[PROCESS 1] Query Expansion: {query_expansion}")

    retrieved_docs = await retrieve_from_qdrant(question, k=3, thinking=False)

    prompt_text = """
    jika jawaban tidak didukung konteks, bilang tidak tau

    jika konteks mendukung, Jawablah dengan kalimat lengkap (Subject + Predicate + Object) tanpa kata ganti sehingga kata kunci pertanyaan selalu ada di dalam jawaban.Jangan gunakan kalimat pembuka seperti "Berdasarkan konteks..." atau "Menurut dokumen...". Langsung jawab intinya.
    
    Contoh:
    Tanya: Siapa Rektor universitas x saat ini?
    Jawab: Rektor universitas x saat ini adalah Prof. Budi Santoso. (JANGAN JAWAB: Prof. Budi Santoso)

    Konteks dari Database:
    {context}

    Pertanyaan Pengguna:
    {question}

    
    Jawaban:
    """

    QA_PROMPT = PromptTemplate(
        input_variables=["context", "question"],
        template=prompt_text
    )

    final_prompt = QA_PROMPT.format(
        context=retrieved_docs,
        question=question
    )

    #response_llm = await resources.llm.ainvoke(final_prompt)
    response_llm = await resources.llm_gemma3_12b.ainvoke(final_prompt)

    
    return {"answer": response_llm, "source_documents": retrieved_docs}




