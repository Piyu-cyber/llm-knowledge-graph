from pypdf import PdfReader


class IngestionService:
    def __init__(self, llm_service, rag_service, graph_service):
        self.llm_service = llm_service
        self.rag_service = rag_service
        self.graph_service = graph_service

    def extract_text(self, file_path):
        reader = PdfReader(file_path)
        text = ""

        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"

        return text

    def ingest(self, file_path):
        try:
            # 🔹 Step 1: Extract text
            text = self.extract_text(file_path)

            if not text.strip():
                raise ValueError("No text extracted from document.")

            # 🔹 Step 2: Extract concepts using LLM
            data = self.llm_service.extract_concepts(text)

            concepts_added = 0
            relationships_added = 0

            # 🔥 Step 3: Clean + store concepts
            for concept in data.get("concepts", []):
                name = concept.get("name", "").strip()
                description = concept.get("description", "").strip()

                # 🔥 CLEAN BAD LLM OUTPUT
                if name.lower().startswith("name:"):
                    name = name.split(":", 1)[1].strip()

                # ❌ Skip garbage
                if not name or len(name) < 2:
                    continue

                # Optional: skip very generic junk
                if name.lower() in ["concept", "thing", "item"]:
                    continue

                self.graph_service.create_concept(name, description)
                concepts_added += 1

            # 🔥 Step 4: Clean + store relationships
            for rel in data.get("relationships", []):
                from_node = rel.get("from", "").strip()
                to_node = rel.get("to", "").strip()
                rel_type = rel.get("type", "RELATED")

                # Clean names
                if from_node.lower().startswith("name:"):
                    from_node = from_node.split(":", 1)[1].strip()

                if to_node.lower().startswith("name:"):
                    to_node = to_node.split(":", 1)[1].strip()

                if not from_node or not to_node:
                    continue

                self.graph_service.create_relationship(
                    from_node,
                    to_node,
                    rel_type
                )
                relationships_added += 1

            # 🔹 Step 5: Store in RAG
            self.rag_service.ingest_documents(text)

            return {
                "status": "success",
                "concepts_added": concepts_added,
                "relationships_added": relationships_added
            }

        except Exception as e:
            print("❌ INGEST ERROR:", str(e))
            return {
                "status": "error",
                "message": str(e)
            }