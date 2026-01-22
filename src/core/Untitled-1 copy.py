"""
Revised Goal-Driven Multi-Hop Agentic AI
=======================================

✔ NO string heuristic
✔ Goals extracted by LLM
✔ True agentic planning
✔ Multi-hop reasoning
✔ RAG + FAISS
✔ Deterministic JSON control

Dependencies:
pip install openai sentence-transformers faiss-cpu numpy
"""

import os
import json
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum
import numpy as np

# Optional deps
try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

try:
    import faiss
except ImportError:
    faiss = None

try:
    import openai
except ImportError:
    openai = None

# -------------------------------------------------
# LOGGING
# -------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# -------------------------------------------------
# CORE STRUCTURES
# -------------------------------------------------

class ReasoningState(Enum):
    PLANNING = "planning"
    RETRIEVING = "retrieving"
    ANSWERING = "answering"
    FINAL = "final"

@dataclass
class Fact:
    content: str
    source: str
    hop: int
    confidence: float
    source_type: str  # retrieved | inferred

@dataclass
class KnowledgeGoal:
    description: str
    satisfied: bool = False
    evidence: List[str] = field(default_factory=list)

@dataclass
class ReasoningStep:
    hop: int
    subquestion: str
    facts: List[str]
    answer: str










def query_classification(self, question: str) -> Dict:
        system = """
        You are an expert in classifying questions into types.
        Analyze the question and output a JSON with the following fields:
        - query_type: one of ['single', 'mk_code', 'multihop', 'comparative', 'abbreviation', 'mixed']
        Output JSON only.

        Output format:
        {"query_type": "..."}
        """
        user = f"Question: {question}"

        response = self.llm.call([
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ])

        try:
            classification = json.loads(response)
            return classification
        except json.JSONDecodeError as e:
            print(f"[JSON ERROR] Failed to parse classification response: {e}")
            print(f"Response was: {response}")
            raise

def answer_question(self, question: str) -> str:
        try:
            type_question = self.query_classification(question)
            if type_question["query_type"] == "single":
                return self._answer_single(question)
            elif type_question["query_type"] == "multihop":
                return self._answer_multihop(question)
            else:
                return self._answer_single(question)
        except Exception as e:
            logger.error(f"Error in query classification: {e}")
            return self._answer_single(question)
        
def plan(self, question: str):
        system = """
                You are a planning agent for independent multi-hop QA.

                Based on missing knowledge goals, decide the next action.

                Output JSON ONLY:

                {"type":"still_processing_subquestions","goal":"...","sub_question":"..."}
                OR
                {"type":"final","answer":"..."}
                """

        goals = "\n".join([f"- {g.description}: {'DONE' if g.satisfied else 'MISSING'}" for g in self.goals])
        facts = "\n".join([f"- {f.content}" for f in self.facts])

        user = f"""
                Question:
                {question}

                Knowledge Goals:
                {goals}

                Known Facts:
                {facts if facts else "(none)"}
        """

        response = self.llm.call([
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ])

        return safe_json_extract(response)

def _answer_multihop(self, question: str) -> str:
        try:    
            self.goals = self.extract_goals(question)
            self.facts = []
            self.reasoning_trace = []
            decision = self.plan(question)

            while decision["type"] == "still_processing_subquestions":
                retrieved_facts = self.retrieve_facts(decision["subquestion"])
                self.facts.extend(retrieved_facts)
                decision = self.plan(question)
        except Exception as e:
            logger.error(f"Error in multi-hop answering: {e}")
            return "Maaf, terjadi kesalahan saat memproses pertanyaan Anda."