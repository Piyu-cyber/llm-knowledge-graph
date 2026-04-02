from sentence_transformers import SentenceTransformer
import faiss
import numpy as np


class RAGService:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.index = None
        self.chunks = []

    # 🔥 Better chunking
    def chunk_text(self, text, size=200):
        if not text or not text.strip():
            return []

        words = text.split()

        return [
            " ".join(words[i:i + size])
            for i in range(0, len(words), size)
            if len(words[i:i + size]) > 20  # avoid tiny chunks
        ]

    # 🔥 Ingest documents (ROBUST)
    def ingest_documents(self, text):
        chunks = self.chunk_text(text)

        if not chunks:
            print("⚠️ No valid chunks created")
            return

        embeddings = self.model.encode(chunks, normalize_embeddings=True)

        # 🔥 Reset index if empty (optional behavior)
        if self.index is None:
            dim = embeddings.shape[1]
            self.index = faiss.IndexFlatL2(dim)

        self.index.add(np.array(embeddings))
        self.chunks.extend(chunks)

        print(f"✅ RAG ingested {len(chunks)} chunks")

    # 🔥 Retrieval (IMPROVED)
    def retrieve(self, query, k=3):
        if self.index is None or not self.chunks:
            return []

        # 🔥 Special handling for summary queries
        query_lower = query.lower()
        if any(x in query_lower for x in ["pdf", "document", "summary", "proposal"]):
            # Return first chunks (best for summary)
            return self.chunks[:k]

        try:
            q_embed = self.model.encode([query], normalize_embeddings=True)

            distances, indices = self.index.search(np.array(q_embed), k)

            results = []
            for i in indices[0]:
                if 0 <= i < len(self.chunks):
                    results.append(self.chunks[i])

            return results

        except Exception as e:
            print("❌ RAG RETRIEVE ERROR:", str(e))
            return []