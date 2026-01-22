# DéFi RAG Agent: Academic Retrieval-Augmented Generation System

DéFi RAG Agent is an academic assistant system based on _Retrieval-Augmented Generation_ (RAG), designed to handle the complexity of university documents such as curricula, course syllabi, and academic regulations.

This system does not use a conventional (naive) RAG approach, but instead implements an **Agentic RAG** architecture. It is capable of query pre-processing (typo correction, acronym expansion), intent classification (_intent routing_), complex question decomposition (_multihop reasoning_), and intelligent table reconstruction from PDF documents.

This project was developed as part of an internship program at UPATIK, Universitas Pendidikan Ganesha.

## System Architecture

The system is built using Python and integrates several State-of-the-Art (SOTA) models for _embedding_ and _reasoning_.

### 1. Hybrid Retrieval Engine

To maximize _recall_ and search accuracy, the system uses a hybrid retrieval method stored in **Qdrant Vector Database**:

- **Dense Retrieval:** Uses the `Qwen/Qwen3-Embedding-4B` model (4-bit quantized) to capture deep semantic meaning.
- **Sparse Retrieval:** Uses `naver/splade-v3` for precise keyword-based (_lexical_) search, addressing embedding weaknesses on specific terms such as course codes.

### 2. Intelligent Document Parsing & Table Reconstruction

One of the main challenges in academic documents is table formats that are often split across pages. This system implements a custom _ingestion_ pipeline:

- **Multi-Modal Parsing:** Supports `Qwen-VL` (Vision Language Model) and `Docling` for content extraction.
- **Table Continuity Analysis:** A dedicated algorithm using LLMs to analyze whether a table in the current _chunk_ is a continuation of the previous one. If detected, the system automatically merges the data before embedding.
- **Metadata Enrichment:** Each table _chunk_ is enriched with LLM-generated semantic descriptions to improve retrievability.

### 3. Agentic Query Processing

Before querying the database, user questions go through several stages:

- **Acronym Expansion:** Uses a dynamic dictionary stored in Firebase Firestore to translate academic abbreviations (e.g., "WR 1" becomes "Vice Rector for Academic Affairs").
- **Standalone Query Reformulation:** Resolves reference ambiguities (coreference) based on previous conversation history.
- **Intent Classification & Routing:** Uses an LLM Router to classify queries into: _Single Fact_, _Comparative_, _Multihop_, or _Specific Course Code_.

## Project Structure

```text
defi-rag-agent/
├── data/                       # Raw PDF storage and processed outputs
├── qdrant_custom_db_qwen/      # Local persistent Vector Database
├── src/
│   ├── core/                   # Core logic (LLM wrapper, Qdrant client)
│   ├── config/                 # Firebase and environment configuration
│   ├── routes/                 # API routes (FastAPI)
│   ├── utils/                  # PDF parsing utilities (Docling/Qwen-VL)
│   ├── agentic_rag.py          # Main Agentic workflow
│   ├── query_processor.py      # Query preprocessing and routing
│   ├── qdrant_client.py        # Custom embedder and indexing logic
│   └── schemas.py              # Data type definitions (Pydantic models)
├── main.py                     # Application entry point (Server & CLI)
├── requirements.txt            # Dependency list
└── serviceAccountKey.json      # Firebase credentials (excluded from repo)
```

## System Requirements

- **Python**: Version 3.10 or newer.
- **GPU (Optional but Recommended)**: NVIDIA GPU with at least 8GB VRAM for running Qwen-VL parsing and Qwen-Embedding locally. If using CPU, Docling parsing mode is recommended.

**Database:**

- **Qdrant** (Embedded mode, no separate server installation required)
- **Firebase Firestore** (For acronym dictionary)

## Installation

### Clone Repository

```text
git clone https://github.com/username/defi-rag-agent.git
cd defi-rag-agent
```

### Setup Virtual Environment & Install Dependencies

```text
conda env create -f env.yml
conda activate defi
```

### Set Environment Variables

```text
OPENAI_API_KEY=sk-...   # or other LLM provider
```

### Firebase Configuration

Place the `serviceAccountKey.json` file from Firebase Console into the project root directory to enable acronym expansion.

## Usage

The application provides both a Command Line Interface (CLI) for data management and an API server for inference.

Run the main entry point:

```text
python main.py
```

You will be presented with an interactive menu.

### 1. Data Preparation (Indexing)

Choose option [2] in the main menu. You can select the parsing method:

- **Docling**: Fast, CPU-efficient.
- **Gemma3**: Slower, requires GPU, but highly accurate for complex visual/table documents.

This process reads PDFs from `data/input_pdfs`, performs chunking, embedding (Dense + Sparse), and stores them in Qdrant.

### 2. Running the API Server

Choose option [1] to run the FastAPI server (Uvicorn).

Access Swagger UI:

```
http://localhost:8000/docs
```

Main endpoint:

- `/chat` (POST)

## Technical Stack

**Framework**: FastAPI, LangChain

**Vector Database**: Qdrant (Local)

**LLM Integration**: Groq / OpenAI / Local LLM (via LangChain wrapper)

**Embedding Models:**

- **Dense**: Qwen/Qwen3-Embedding-4B
- **Sparse**: naver/splade-v3

**Parsing Tools**: Docling, Qwen-VL, PyMuPDF

## License

This project is distributed under the MIT License. Data and model usage are subject to the respective providers' policies (Qwen, Naver Labs, etc.).
