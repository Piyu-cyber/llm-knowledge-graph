from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os
import pickle

INDEX_PATH = "rag_index.faiss"
CHUNKS_PATH = "rag_chunks.pkl"


class RAGService:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.index = None
        self.chunks = []
        self._load()  # 🔥 load persisted data
    def reset(self):
        self.index = None
        self.chunks = []
        print("♻️ RAG reset")
    # 🔥 Load index safely
    def _load(self):
        try:
            if os.path.exists(INDEX_PATH) and os.path.exists(CHUNKS_PATH):
                self.index = faiss.read_index(INDEX_PATH)

                with open(CHUNKS_PATH, "rb") as f:
                    self.chunks = pickle.load(f)

                print(f"✅ Loaded RAG index: {len(self.chunks)} chunks")

        except Exception as e:
            print("⚠️ Failed to load RAG index:", e)
            self.index = None
            self.chunks = []

    # 🔥 Save index safely
    def _save(self):
        try:
            if self.index:
                faiss.write_index(self.index, INDEX_PATH)

                with open(CHUNKS_PATH, "wb") as f:
                    pickle.dump(self.chunks, f)

                print("💾 RAG index saved")

        except Exception as e:
            print("⚠️ Failed to save RAG index:", e)

    # 🔥 Improved chunking (overlap for better context)
    def chunk_text(self, text, size=300, overlap=50):
        if not text or not text.strip():
            return []

        words = text.split()
        chunks = []

        for i in range(0, len(words), size - overlap):
            chunk = words[i:i + size]

            if len(chunk) > 30:
                chunks.append(" ".join(chunk))

        return chunks

    # 🔥 Ingest documents
    def ingest_documents(self, text):
        chunks = self.chunk_text(text)

        if not chunks:
            print("⚠️ No valid chunks created")
            return

        embeddings = self.model.encode(chunks, normalize_embeddings=True)

        # 🔥 Initialize FAISS if needed
        if self.index is None:
            dim = embeddings.shape[1]
            self.index = faiss.IndexFlatL2(dim)

        # 🔥 Add embeddings
        self.index.add(np.array(embeddings))
        self.chunks.extend(chunks)

        # 🔥 Persist
        self._save()

        print(f"✅ RAG ingested {len(chunks)} chunks")

    # 🔥 Retrieve relevant chunks
    def retrieve(self, query, k=3):
        if self.index is None or not self.chunks:
            return []

        query_lower = query.lower()

        # 🔥 Summary fallback (VERY IMPORTANT)
        if any(x in query_lower for x in ["pdf", "document", "summary", "proposal"]):
            return self.chunks[:k]

        try:
            q_embed = self.model.encode([query], normalize_embeddings=True)

            # 🔥 Safe k handling
            k = min(k, len(self.chunks))

            distances, indices = self.index.search(np.array(q_embed), k)

            results = []
            for i in indices[0]:
                if 0 <= i < len(self.chunks):
                    results.append(self.chunks[i])

            return results

        except Exception as e:
            print("❌ RAG RETRIEVE ERROR:", str(e))
            return []