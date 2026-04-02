import os
import json
import re
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

    # 🔥 2. RELEVANCE CHECKER (STABLE)
    def evaluate_relevance(self, query, context):
        prompt = f"""
Query: {query}

Context:
{context[:1500]}

Is the context directly relevant to the SAME meaning of the query?

Respond ONLY with:
GOOD or BAD
"""

        content = self._call_llm(prompt, temperature=0)

        if not content:
            return "BAD"

        decision = content.strip().upper()

        return "GOOD" if "GOOD" in decision else "BAD"

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