from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

class RAGService:
    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        self.index = None
        self.chunks = []

    def chunk_text(self, text, size=200):
        words = text.split()
        return [
            " ".join(words[i:i+size])
            for i in range(0, len(words), size)
        ]

    def ingest_documents(self, text):
        chunks = self.chunk_text(text)
        embeddings = self.model.encode(chunks)

        self.chunks.extend(chunks)

        if self.index is None:
            dim = embeddings.shape[1]
            self.index = faiss.IndexFlatL2(dim)

        self.index.add(np.array(embeddings))

    def retrieve(self, query, k=3):
        if self.index is None:
            return []

        q_embed = self.model.encode([query])
        distances, indices = self.index.search(np.array(q_embed), k)

        return [self.chunks[i] for i in indices[0]]