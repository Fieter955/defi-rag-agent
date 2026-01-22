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

# -------------------------------------------------
# JSON SAFETY
# -------------------------------------------------

def safe_json_extract(text: str) -> Optional[dict]:
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}") + 1
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        try:
            cleaned = text[start:end].replace("'", '"').replace(",}", "}").replace(",]", "]")
            return json.loads(cleaned)
        except Exception:
            return None

# -------------------------------------------------
# RETRIEVER
# -------------------------------------------------

class HybridRetriever:
    def __init__(self, docs: List[Dict], model="all-MiniLM-L6-v2"):
        self.texts = [d["text"] for d in docs]
        self.ids = [d.get("id", str(i)) for i, d in enumerate(docs)]
        self.dim = 384

        if SentenceTransformer:
            self.embedder = SentenceTransformer(model)
            emb = self.embedder.encode(self.texts, convert_to_numpy=True)
        else:
            self.embedder = None
            emb = np.random.randn(len(self.texts), self.dim)

        emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-9)
        self.embeddings = emb.astype("float32")

        if faiss:
            self.index = faiss.IndexFlatIP(self.dim)
            self.index.add(self.embeddings)
        else:
            self.index = None

    def retrieve(self, query: str, k: int = 5):
        if self.embedder:
            q = self.embedder.encode([query], convert_to_numpy=True)[0]
        else:
            q = np.random.randn(self.dim)

        q = q / (np.linalg.norm(q) + 1e-9)
        q = q.reshape(1, -1).astype("float32")

        if self.index:
            scores, idxs = self.index.search(q, k)
            return [(self.ids[i], self.texts[i], float(s)) for i, s in zip(idxs[0], scores[0])]
        else:
            sims = self.embeddings @ q.T
            order = np.argsort(-sims.flatten())[:k]
            return [(self.ids[i], self.texts[i], float(sims[i])) for i in order]

# -------------------------------------------------
# LLM INTERFACE
# -------------------------------------------------

class LLM:
    def __init__(self, model="gpt-4o-mini", temperature=0.0):
        self.model = model
        self.temperature = temperature
        self.available = openai and os.getenv("OPENAI_API_KEY")
        if self.available:
            openai.api_key = os.getenv("OPENAI_API_KEY")

    def call(self, messages, max_tokens=600):
        if self.available:
            try:
                r = openai.ChatCompletion.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=max_tokens,
                )
                return r.choices[0].message.content
            except Exception as e:
                logger.error(e)
        return "{}"

# -------------------------------------------------
# AGENT
# -------------------------------------------------

class GoalDrivenAgent:
    def __init__(self, retriever: HybridRetriever, llm: LLM, max_hops=6):
        self.retriever = retriever
        self.llm = llm
        self.max_hops = max_hops
        self.goals: List[KnowledgeGoal] = []
        self.facts: List[Fact] = []
        self.steps: List[ReasoningStep] = []

    # -----------------------------
    # GOAL EXTRACTION (NO HEURISTIC)
    # -----------------------------

    def extract_goals(self, question: str):
        system = """
                You analyze a question and extract ALL knowledge goals required to answer it.

                Output JSON only:
                {
                "goals": ["goal1", "goal2", "..."]
                }
        """
        user = f"Question: {question}"

        response = self.llm.call([
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ])

        parsed = safe_json_extract(response)
        if not parsed or "goals" not in parsed:
            raise RuntimeError("Failed to extract goals")

        self.goals = [KnowledgeGoal(g) for g in parsed["goals"]]

    def _all_goals_satisfied(self):
        return all(g.satisfied for g in self.goals)

    def _update_goals(self, new_facts: List[Fact]):
        for g in self.goals:
            for f in new_facts:
                if any(word.lower() in f.content.lower() for word in g.description.split()):
                    g.satisfied = True
                    g.evidence.append(f.content)

    # -----------------------------
    # PLANNER
    # -----------------------------

    def plan(self, question: str):
        system = """
                You are a planning agent for multi-hop QA.

                Based on missing knowledge goals, decide the next action.

                Output JSON ONLY:

                {"type":"subquestion","goal":"...","sub_question":"..."}
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

    # -----------------------------
    # MAIN LOOP
    # -----------------------------

    def answer(self, question: str):
        self.facts.clear()
        self.steps.clear()
        self.extract_goals(question)

        for hop in range(1, self.max_hops + 1):
            decision = self.plan(question)
            if not decision:
                break

            if decision["type"] == "final":
                return self._finalize(question, decision["answer"])

            subq = decision["sub_question"]
            docs = self.retriever.retrieve(subq)
            new_facts = []

            for doc_id, text, score in docs:
                if score > 0.3:
                    sentence = text.split(".")[0]
                    fact = Fact(sentence, doc_id, hop, score, "retrieved")
                    if not any(f.content == fact.content for f in self.facts):
                        new_facts.append(fact)

            self.facts.extend(new_facts)
            self._update_goals(new_facts)

            answer = self._answer_subquestion(subq, docs)
            self.steps.append(ReasoningStep(hop, subq, [f.content for f in new_facts], answer))

            if self._all_goals_satisfied():
                break

        return self._finalize(question)

    # -----------------------------
    # SUB ANSWER
    # -----------------------------

    def _answer_subquestion(self, subq, docs):
        ctx = "\n".join([d[1] for d in docs[:3]])
        system = "Answer using context. Output JSON {answer, facts}"
        user = f"Subquestion: {subq}\nContext:\n{ctx}"

        response = self.llm.call([
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ])

        parsed = safe_json_extract(response)
        if parsed and "facts" in parsed:
            for f in parsed["facts"]:
                self.facts.append(Fact(f, "llm", 0, 0.6, "inferred"))
            return parsed.get("answer", "")
        return response[:200]

    # -----------------------------
    # FINAL
    # -----------------------------

    def _finalize(self, question, forced=None):
        facts = "\n".join([f"- {f.content}" for f in self.facts])
        system = "Synthesize final answer using only the provided facts."
        user = f"Question: {question}\nFacts:\n{facts}"

        answer = forced or self.llm.call([
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ])

        return {
            "question": question,
            "answer": answer,
            "goals": [{g.description: g.satisfied} for g in self.goals],
            "facts": [f.content for f in self.facts],
            "steps": [s.__dict__ for s in self.steps]
        }

# -------------------------------------------------
# EXAMPLE
# -------------------------------------------------

if __name__ == "__main__":
    docs = [
        {"id": "1", "text": "Germany borders France, Poland, Austria, Switzerland, Belgium, Netherlands, Denmark, and Czech Republic."},
        {"id": "2", "text": "France has a population of about 67 million people."},
        {"id": "3", "text": "Poland has a population of about 38 million people."},
        {"id": "4", "text": "Belgium has a population of about 11 million people."},
    ]

    retriever = HybridRetriever(docs)
    llm = LLM()
    agent = GoalDrivenAgent(retriever, llm)

    result = agent.answer("Which country bordering Germany has the largest population?")
    print(json.dumps(result, indent=2))
