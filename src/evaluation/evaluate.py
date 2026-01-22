import os
import time
from pathlib import Path
from dotenv import load_dotenv
from datasets import Dataset
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import FlashrankRerank
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Qdrant
from langchain_community.document_loaders import UnstructuredPDFLoader
from langchain_community.embeddings.fastembed import FastEmbedEmbeddings
from langchain_groq import ChatGroq
from llama_parse import LlamaParse
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_recall,
    context_precision,
)
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


load_dotenv()


eval_questions = [
    "Apa judul dari penelitian ini?",
    "Apa tujuan utama dari penelitian ini?",
    "Apa tantangan utama dalam pengumpulan data tanaman pertanian?",
    "Model apa yang digunakan untuk menghasilkan data sintetik?",
    "Apa saja parameter yang diuji dalam penelitian ini?",
]


eval_answers = [
    "Judul penelitian ini adalah 'Generating Synthetic Data on Agricultural Crops with DCGAN'.",
    "Tujuan utama penelitian ini adalah mengembangkan metode augmentasi data menggunakan DCGAN untuk menghasilkan citra tanaman jagung yang realistis.",
    "Tantangan utama adalah terbatasnya ketersediaan data tanaman pertanian untuk melatih model machine learning.",
    "Penelitian ini menggunakan model Deep Convolutional Generative Adversarial Network (DCGAN).",
    "Parameter yang diuji dalam penelitian ini meliputi variasi dimensi laten dan ukuran batch.",
]


#fungsi ini dipakai untuk mengevaluasi kemampuan RAG menggunakan RAGAs
def initialize_and_run_rag(questions):
    print("Menginisialisasi komponen RAG...")
    LLAMA_PARSE_API_KEY = os.getenv("LLAMA_PARSE_API_KEY")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")

    if not all([LLAMA_PARSE_API_KEY, GROQ_API_KEY]):
        raise ValueError("API key tidak ditemukan di file .env")

    llm = ChatGroq(temperature=0, model_name="llama3-70b-8192", api_key=GROQ_API_KEY)
    parser = LlamaParse(api_key=LLAMA_PARSE_API_KEY, result_type="markdown", max_timeout=5000)
    embeddings = FastEmbedEmbeddings(model_name="BAAI/bge-large-en-v1.5")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=2048, chunk_overlap=128)
    compressor = FlashrankRerank(model="ms-marco-MiniLM-L-12-v2")

    prompt_template_str = """
    Gunakan konteks berikut untuk menjawab pertanyaan. Jika tidak tahu, jawab 'Saya tidak tahu'.

    Konteks: {context}
    Pertanyaan: {question}
    Jawaban:
    """
    prompt = PromptTemplate(template=prompt_template_str, input_variables=["context", "question"])

    print("Memproses dokumen thesis.pdf...")
    file_path = Path("./data/thesis.pdf")
    if not file_path.exists():
        raise FileNotFoundError(f"File tidak ditemukan di {file_path}")

    parsed_md_path = Path("./data/parsed_eval.md")
    if not parsed_md_path.exists():
        print("Melakukan parsing dokumen dengan LlamaParse...")
        parsed_docs = parser.load_data(str(file_path))
        parsed_md_path.parent.mkdir(parents=True, exist_ok=True)
        with parsed_md_path.open("w", encoding="utf-8") as f:
            f.write(parsed_docs[0].text)
    else:
        print("Menggunakan hasil parsing dari cache...")

    loader = UnstructuredPDFLoader(str(file_path))
    docs = text_splitter.split_documents(loader.load())

    print("Membuat database vektor Qdrant...")
    qdrant = Qdrant.from_documents(docs, embeddings, path="./db_eval", collection_name="eval_embeddings", force_recreate=True)

    retriever = qdrant.as_retriever(search_kwargs={"k": 5})
    compression_retriever = ContextualCompressionRetriever(base_compressor=compressor, base_retriever=retriever)

    qa_chain = RetrievalQA.from_chain_type(
        llm=llm,
        chain_type="stuff",
        retriever=compression_retriever,
        return_source_documents=True,
        chain_type_kwargs={"prompt": prompt}
    )

    print("Menjalankan RAG pipeline untuk setiap pertanyaan evaluasi...")
    results = []
    for question in questions:
        print(f"  > Menjawab pertanyaan: '{question}'")
        response = qa_chain.invoke(question)
        results.append({
            "question": question,
            "answer": response['result'],
            "contexts": [doc.page_content for doc in response['source_documents']],
        })
        time.sleep(2)
    return results

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=10, max=60),
    retry=retry_if_exception_type(Exception),
)
def evaluate_rag_with_ragas(rag_outputs):
    print("\nMempersiapkan data untuk evaluasi RAGAs...")
    data_for_eval = {
        "question": eval_questions,
        "answer": [output['answer'] for output in rag_outputs],
        "contexts": [output['contexts'] for output in rag_outputs],
        "ground_truth": eval_answers,
    }
    dataset = Dataset.from_dict(data_for_eval)

    print("Memulai evaluasi dengan RAGAs...")
    result = evaluate(
        dataset=dataset,
        metrics=[
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
        ],
        llm=ChatGroq(model="llama3-70b-8192", api_key=os.getenv("GROQ_API_KEY")),
        embeddings=FastEmbedEmbeddings(model_name="BAAI/bge-large-en-v1.5"),
    )

    print("Evaluasi selesai!")
    return result

if __name__ == "__main__":
    rag_results = initialize_and_run_rag(eval_questions)
    evaluation_scores = evaluate_rag_with_ragas(rag_results)

    df = evaluation_scores.to_pandas()
    print("\n--- HASIL EVALUASI RAGAs ---")
    print(df)
