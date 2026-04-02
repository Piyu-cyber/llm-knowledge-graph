from pypdf import PdfReader


class IngestionService:
    def __init__(self, llm_service, rag_service, graph_service):
        self.llm_service = llm_service
        self.rag_service = rag_service
        self.graph_service = graph_service

    # 🔹 Step 1: Extract text safely
    def extract_text(self, file_path):
        try:
            reader = PdfReader(file_path)
            text_chunks = []

            for i, page in enumerate(reader.pages):
                try:
                    extracted = page.extract_text()
                    if extracted:
                        text_chunks.append(extracted)
                except Exception as e:
                    print(f"⚠️ Skipping page {i}: {str(e)}")

            full_text = "\n".join(text_chunks)
            return full_text.strip()

        except Exception as e:
            raise Exception(f"PDF extraction failed: {str(e)}")

    # 🔹 Utility: Clean LLM text
    def _clean_text(self, value):
        if not value:
            return ""

        value = value.strip()

        # Remove "name:" prefix if exists
        if value.lower().startswith("name:"):
            value = value.split(":", 1)[1].strip()

        return value

    # 🔹 Main ingestion pipeline
    def ingest(self, file_path):
        try:
            # ✅ Step 1: Extract text
            text = self.extract_text(file_path)

            if not text:
                raise ValueError("No text extracted from document.")

            # ⚠️ Optional: limit text for LLM (avoid token overflow)
            MAX_CHARS = 15000
            llm_input = text[:MAX_CHARS]

            # ✅ Step 2: Extract concepts using LLM
            data = self.llm_service.extract_concepts(llm_input)

            if not isinstance(data, dict):
                raise ValueError("Invalid LLM response format.")

            concepts_added = 0
            relationships_added = 0

            # ✅ Step 3: Store concepts
            seen_concepts = set()

            for concept in data.get("concepts", []):
                name = self._clean_text(concept.get("name"))
                description = self._clean_text(concept.get("description"))

                # ❌ Skip garbage
                if not name or len(name) < 2:
                    continue

                if name.lower() in ["concept", "thing", "item"]:
                    continue

                # Avoid duplicates
                if name.lower() in seen_concepts:
                    continue

                try:
                    self.graph_service.create_concept(name, description)
                    seen_concepts.add(name.lower())
                    concepts_added += 1
                except Exception as e:
                    print(f"⚠️ Concept insert failed ({name}): {str(e)}")

            # ✅ Step 4: Store relationships
            for rel in data.get("relationships", []):
                from_node = self._clean_text(rel.get("from"))
                to_node = self._clean_text(rel.get("to"))
                rel_type = rel.get("type", "RELATED").strip()

                if not from_node or not to_node:
                    continue

                try:
                    self.graph_service.create_relationship(
                        from_node,
                        to_node,
                        rel_type
                    )
                    relationships_added += 1
                except Exception as e:
                    print(f"⚠️ Relationship insert failed ({from_node}->{to_node}): {str(e)}")

            # ✅ Step 5: Store in RAG (FULL TEXT, not truncated)
            try:
                self.rag_service.ingest_documents(text)
            except Exception as e:
                print(f"⚠️ RAG ingestion failed: {str(e)}")

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