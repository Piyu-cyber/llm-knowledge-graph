import os
import json
import re
from dotenv import load_dotenv
from groq import Groq

# Load environment variables
load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class LLMService:

    # 🔥 1. CONCEPT EXTRACTION (HARDENED)
    def extract_concepts(self, text):
        prompt = f"""
You are an information extraction system.

Extract key concepts and relationships from the text below.

STRICT RULES:
- Output ONLY valid JSON
- No explanation, no markdown
- Every concept MUST have name + description

FORMAT:
{{
  "concepts": [
    {{"name": "string", "description": "string", "type": "Concept"}}
  ],
  "relationships": [
    {{"from": "string", "to": "string", "type": "RELATED"}}
  ]
}}

TEXT:
{text[:2000]}
"""

        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )

            content = response.choices[0].message.content.strip()
            print("\n🔍 RAW LLM RESPONSE:\n", content)

            # 🔥 Extract JSON safely
            match = re.search(r"\{.*\}", content, re.DOTALL)

            if not match:
                print("❌ No JSON found")
                return {"concepts": [], "relationships": []}

            json_str = match.group(0)

            # 🔥 Try parsing
            try:
                data = json.loads(json_str)
                print("✅ Parsed Concepts:", len(data.get("concepts", [])))
                return data

            except json.JSONDecodeError:
                print("⚠️ Fixing JSON...")

                # Cleanup
                json_str = json_str.replace("\n", " ")
                json_str = json_str.replace("\t", " ")
                json_str = re.sub(r",\s*}", "}", json_str)
                json_str = re.sub(r",\s*]", "]", json_str)

                try:
                    return json.loads(json_str)
                except Exception as e:
                    print("❌ JSON still broken:", e)
                    return {"concepts": [], "relationships": []}

        except Exception as e:
            print("❌ LLM ERROR (extract):", e)
            return {"concepts": [], "relationships": []}

    # 🔥 2. RELEVANCE CHECKER (STRICT)
    def evaluate_relevance(self, query, context):
        prompt = f"""
Query: {query}

Context:
{context}

Are these relevant to answering the query?

Respond ONLY with:
GOOD or BAD
"""

        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )

            decision = response.choices[0].message.content.strip().upper()

            return "GOOD" if "GOOD" in decision else "BAD"

        except Exception as e:
            print("❌ LLM ERROR (relevance):", e)
            return "BAD"

    # 🔥 3. ANSWER GENERATION (FINAL VERSION)
    def generate_answer(self, query, context):
        prompt = f"""
You are an AI assistant.

Answer the question using the provided context.

STRUCTURE:
- Start with a strong definition
- Then explain key features in 2–3 sentences

Question:
{query}

Context:
{context}

RULES:
- Max 3–4 sentences
- Write confidently and clearly
- No fluff
- Prefer graph facts first

Answer:
"""

        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )

            answer = response.choices[0].message.content.strip()

            # 🔥 Optional cleanup (remove weird formatting)
            answer = re.sub(r"\n{2,}", "\n", answer)

            return answer

        except Exception as e:
            print("❌ LLM ERROR (answer):", e)
            return "Error generating answer"