import os
import json
import re
from typing import Dict
from dotenv import load_dotenv
from groq import Groq

# Load environment variables
load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class LLMService:

    # 🔥 Utility: Safe LLM call (IMPROVED)
    def _call_llm(self, prompt, temperature=0, retries=2):
        for attempt in range(retries):
            try:
                response = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature
                )
                return response.choices[0].message.content.strip()

            except Exception as e:
                print(f"❌ LLM CALL ERROR (attempt {attempt+1}):", e)

        return None

    # 🔥 Utility: Extract JSON safely
    def _extract_json(self, text):
        if not text:
            return None

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None

        json_str = match.group(0)

        # Cleanup
        json_str = json_str.replace("\n", " ").replace("\t", " ")
        json_str = re.sub(r",\s*}", "}", json_str)
        json_str = re.sub(r",\s*]", "]", json_str)

        try:
            return json.loads(json_str)
        except Exception:
            return None

    # 🔥 0. QUERY DISAMBIGUATION (FIXED)
    def disambiguate_query(self, query):
        prompt = f"""
Clarify the meaning of this query in 2–4 words.

Query: {query}

Respond ONLY with the clarified query.
"""

        content = self._call_llm(prompt, temperature=0)

        if not content:
            return query

        # 🔥 Clean output (important)
        cleaned = content.strip()
        cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", cleaned)

        # fallback if garbage
        if len(cleaned.split()) > 6 or len(cleaned) < 2:
            return query

        return cleaned

    # 🔥 1. CONCEPT EXTRACTION (FIXED — NO TRUNCATION BUG)
    def extract_concepts(self, text):
        prompt = f"""
You are an information extraction system.

Extract key concepts and relationships from the text.

STRICT RULES:
- Output ONLY valid JSON
- No explanation
- Each concept must have name and description

FORMAT:
{{
  "concepts": [
    {{"name": "string", "description": "string"}}
  ],
  "relationships": [
    {{"from": "string", "to": "string", "type": "RELATED"}}
  ]
}}

TEXT:
{text}
"""

        content = self._call_llm(prompt, temperature=0)

        if not content:
            return {"concepts": [], "relationships": []}

        print("\n🔍 RAW LLM RESPONSE:\n", content)

        data = self._extract_json(content)

        if not data:
            print("❌ JSON parsing failed")
            return {"concepts": [], "relationships": []}

        print("✅ Parsed Concepts:", len(data.get("concepts", [])))
        return data
    
    # 🔥 1b. HIERARCHICAL CONCEPT EXTRACTION (NEW - PHASE 4)
    def extract_concepts_hierarchical(self, text: str) -> Dict:
        """
        Extract concepts with hierarchical levels and relationships.
        
        Returns structure with:
        - Module/Topic/Concept/Fact hierarchy
        - Prerequisites, extends, contrasts relationships
        
        Returns:
            {"nodes": [...], "edges": [...]}
        """
        prompt = f"""
You are an expert knowledge extraction system.

From the provided text, extract a hierarchical educational structure:
- MODULES: Major subject areas
- TOPICS: Subtopics within modules
- CONCEPTS: Key ideas within topics
- FACTS: Specific details/examples
- RELATIONSHIPS: Prerequisites (REQUIRES), extensions (EXTENDS), conflicts (CONTRASTS)

STRICT RULES:
- Output ONLY valid JSON
- No explanation or markdown
- Each node must have: name, level (MODULE/TOPIC/CONCEPT/FACT), description
- Each edge must have: source, target, type (REQUIRES/EXTENDS/CONTRASTS/RELATED)
- Prerequisites = what must be learned first
- Extends = how one concept builds on another
- Contrasts = conflicting or opposite concepts

FORMAT:
{{
  "nodes": [
    {{"name": "string", "level": "MODULE|TOPIC|CONCEPT|FACT", "description": "string"}}
  ],
  "edges": [
    {{"source": "string", "target": "string", "type": "REQUIRES|EXTENDS|CONTRASTS|RELATED"}}
  ]
}}

TEXT:
{text}
"""
        
        content = self._call_llm(prompt, temperature=0)
        
        if not content:
            return {"nodes": [], "edges": []}
        
        print("\n🔍 RAW HIERARCHICAL RESPONSE:\n", content[:500])
        
        data = self._extract_json(content)
        
        if not data:
            print("❌ JSON parsing failed for hierarchical extraction")
            return {"nodes": [], "edges": []}
        
        # Validate structure
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        
        # Filter invalid nodes
        valid_levels = {"MODULE", "TOPIC", "CONCEPT", "FACT"}
        nodes = [n for n in nodes if n.get("level", "").upper() in valid_levels]
        
        # Filter invalid edges
        valid_types = {"REQUIRES", "EXTENDS", "CONTRASTS", "RELATED"}
        edges = [e for e in edges if e.get("type", "").upper() in valid_types]
        
        print(f"✅ Parsed: {len(nodes)} nodes, {len(edges)} relationships")
        return {"nodes": nodes, "edges": edges}

    def evaluate_relevance(self, query, context):
        """
        Evaluate relevance of context to query.
        
        Returns scalar score 0.0-1.0 instead of GOOD/BAD.
        
        Args:
            query: User's question
            context: Candidate context to evaluate
        
        Returns:
            Relevance score 0.0-1.0 where:
            - 1.0 = directly relevant
            - 0.7 = somewhat relevant
            - 0.5 = marginally relevant
            - 0.0 = completely irrelevant
        """
        prompt = f"""
Query: {query}

Context:
{context[:1500]}

Rate how directly relevant this context is to answering the query.

Consider:
1. Does it address the query's main topic?
2. Is it from course material?
3. Does it contain factual information?

Respond with ONLY a JSON object:
{{"score": <float between 0.0 and 1.0>}}

Scoring:
- 0.9-1.0: Directly addresses the query with course material
- 0.7-0.9: Highly relevant, some supporting material
- 0.5-0.7: Somewhat relevant, tangentially related
- 0.3-0.5: Marginally relevant, mostly off-topic
- 0.0-0.3: Completely irrelevant
"""

        content = self._call_llm(prompt, temperature=0)

        try:
            import json, re
            match = re.search(r'\{.*\}', content or "", re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                score = float(data.get("score", 0.5))
                return max(0.0, min(1.0, score))
        except Exception as e:
            import logging
            logging.debug(f"Relevance score parsing error: {e}")
        
        # Fallback: check for keywords if parsing failed
        if content and any(w in content.upper() for w in ["RELEVANT", "EXCELLENT", "GOOD", "HIGH"]):
            return 0.8
        elif content and any(w in content.upper() for w in ["SOMEWHAT", "PARTIAL", "MEDIUM"]):
            return 0.6
        else:
            return 0.3

    # 🔥 3. ANSWER GENERATION (ANTI-HALLUCINATION)
    def generate_answer(self, query, context):
        prompt = f"""
You are an expert AI assistant.

Answer ONLY using the provided context.

STRICT RULES:
- If context is unrelated → say: "Context not relevant to query."
- DO NOT use outside knowledge
- DO NOT guess

STRUCTURE:
1. Simple definition (1 sentence)
2. Key explanation (2–3 sentences)

Question:
{query}

Context:
{context[:2000]}

Answer:
"""

        content = self._call_llm(prompt, temperature=0.2)

        if not content:
            return "Error generating answer"

        answer = re.sub(r"\n{2,}", "\n", content).strip()

        return answer