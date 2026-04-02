import os
import json
import re
from dotenv import load_dotenv
from groq import Groq

# Load environment variables
load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class LLMService:

    # 🔥 Utility: Safe LLM call
    def _call_llm(self, prompt, temperature=0):
        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature
            )
            return response.choices[0].message.content.strip()

        except Exception as e:
            print("❌ LLM CALL ERROR:", e)
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

    # 🔥 0. QUERY DISAMBIGUATION (NEW 🔥)
    def disambiguate_query(self, query):
        prompt = f"""
The query may have multiple meanings.

Query: {query}

Identify the most likely meaning in 2–4 words.

Examples:
- "fog" → "weather fog" or "fiber optic gyroscope"
- "tree" → "data structure tree"

Respond ONLY with the clarified query.
"""

        content = self._call_llm(prompt, temperature=0)

        if not content:
            return query

        return content.strip()

    # 🔥 1. CONCEPT EXTRACTION
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
{text[:2000]}
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

    # 🔥 2. RELEVANCE CHECKER (STRONGER)
    def evaluate_relevance(self, query, context):
        prompt = f"""
Query: {query}

Context:
{context[:1500]}

Is the context directly relevant to the SAME meaning of the query?

If meanings differ or context is unrelated → BAD
If clearly useful → GOOD

Respond ONLY with:
GOOD or BAD
"""

        content = self._call_llm(prompt, temperature=0)

        if not content:
            return "BAD"

        decision = content.strip().upper()

        return "GOOD" if "GOOD" in decision else "BAD"

    # 🔥 3. ANSWER GENERATION (ANTI-HALLUCINATION 🔥)
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