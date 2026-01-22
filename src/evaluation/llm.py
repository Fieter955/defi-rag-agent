import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_ollama import OllamaLLM

load_dotenv()
#fungsi ini untuk inisialisasi LLM yang dipakai menggunakan API GROQ. LLM akan dipakai untuk menjawab pertanyaan serta memproses pertanyaan typo, ambigu, dan tidak objek dalam pertanyaan




def init_llm_gemma(model_name: str = "gemma:7b"):
    llm = OllamaLLM(model=model_name)
    return llm

def init_llm_gemma3_12b(model_name: str = "gemma3:12b"):
    llm = OllamaLLM(model=model_name)
    return llm

def init_llm(model_name: str = "meta-llama/llama-4-scout-17b-16e-instruct"):
    api_key = os.getenv("OPENROUTER_API_KEY")

    print("Inisialisasi LLM dengan model:", model_name)

    llm = ChatOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        model=model_name,
        temperature=0.3,
        extra_body={
            "provider": {
                "order": ["Groq"],
                "allow_fallbacks": True
            }
        }
    )

    return llm


def evaluator_llm_fieter(model_name: str = "openai/gpt-4o-mini"):
    api_key = os.getenv("OPENROUTER_API_KEY")

    print("Inisialisasi Evaluator dengan model:", model_name)

    llm = ChatOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        model=model_name,
        temperature=0.0,
        extra_body={
            "provider": {
                "order": ["Groq"],
                "allow_fallbacks": True
            }
        }
    )

    return llm

from langchain_openai import ChatOpenAI
import os

def evaluator_llm(model_name: str = "gpt-4o-mini"): 
    #print("Menggunakan model evaluator UPATIK")
    api_key = os.getenv("UPATIK_GPT_API_KEY")

    print("Inisialisasi Evaluator dengan model:", model_name)

    llm = ChatOpenAI(
        api_key=api_key,
        model=model_name,
        temperature=0.0
    )

    return llm









