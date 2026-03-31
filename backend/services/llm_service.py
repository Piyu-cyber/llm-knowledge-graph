import os
import json
import re
from dotenv import load_dotenv
from groq import Groq

# Load environment variables
load_dotenv()

# Initialize Groq client
client = Groq(api_key=os.getenv("GROQ_API_KEY"))


class LLMService:

    # 🔥 1. CONCEPT EXTRACTION
    def extract_concepts(self, text):
        prompt = f"""
Extract concepts and relationships from the following text.

Return ONLY valid JSON in this format:
{{
  "concepts": [
    {{"name": "", "description": "", "type": "Concept"}}
  ],
  "relationships": [
    {{"from": "", "to": "", "type": "PREREQUISITE"}}
  ]
}}

STRICT RULES:
- Each concept MUST have a description
- Output ONLY JSON

Text:
{text[:2000]}
"""

        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )

            content = response.choices[0].message.content

            match = re.search(r"\{.*\}", content, re.DOTALL)

            if not match:
                print("❌ No JSON found in response")
                return {"concepts": [], "relationships": []}

            json_str = match.group(0)

            try:
                return json.loads(json_str)

            except json.JSONDecodeError:
                print("⚠️ JSON broken, attempting cleanup...")

                json_str = json_str.replace("\n", " ")
                json_str = json_str.replace("\t", " ")
                json_str = re.sub(r",\s*}", "}", json_str)
                json_str = re.sub(r",\s*]", "]", json_str)
                json_str = re.sub(r'(\w+):', r'"\1":', json_str)

                try:
                    return json.loads(json_str)
                except Exception as e:
                    print("❌ Still invalid JSON:", e)
                    return {"concepts": [], "relationships": []}

        except Exception as e:
            print("❌ LLM ERROR:", e)
            return {"concepts": [], "relationships": []}

    # 🔥 2. RELEVANCE CHECKER (CRAG CORE)
    def evaluate_relevance(self, query, results):
        prompt = f"""
        Query: {query}

        Retrieved concepts:
        {results}

        Are these concepts relevant to the query?

        Respond ONLY with:
        GOOD or BAD
        """

        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )

            decision = response.choices[0].message.content.strip()

            if "GOOD" in decision.upper():
                return "GOOD"
            elif "BAD" in decision.upper():
                return "BAD"
            else:
                return "BAD"

        except Exception as e:
            print("❌ LLM ERROR (relevance):", e)
            return "BAD"

    # 🔥 3. ANSWER GENERATION (FINAL FIXED)
    def generate_answer(self, query, context):
        prompt = f"""
        You are an AI assistant.

        You MUST answer using the provided concepts.

        Question:
        {query}

        Concepts:
        {context}

        STRICT RULES:
        - You MUST use the concepts above
        - Do NOT say "no context provided"
        - Do NOT ignore the concepts
        - Explain using the given concepts
        - You MAY add general knowledge only if needed

        Answer:
        """

        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            print("❌ LLM ERROR (answer):", e)
            return "Error generating answer"