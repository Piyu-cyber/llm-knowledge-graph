import faiss
import numpy as np
import os
import pickle
import logging
import threading
import re
from typing import List
from backend.services.jina_multimodal_service import JinaMultimodalService

logger = logging.getLogger(__name__)

INDEX_PATH = "rag_index.faiss"
CHUNKS_PATH = "rag_chunks.pkl"


class RAGService:
    _instances = {}
    _instances_lock = threading.Lock()

    def __new__(cls, index_path: str = INDEX_PATH, chunks_path: str = CHUNKS_PATH):
        key = (os.path.abspath(index_path), os.path.abspath(chunks_path))
        with cls._instances_lock:
            instance = cls._instances.get(key)
            if instance is None:
                instance = super().__new__(cls)
                instance._initialized = False
                cls._instances[key] = instance
            return instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self.embedding_service = JinaMultimodalService()
        self.index = None
        self.chunks = []
        self._load()  # 🔥 load persisted data
        self._initialized = True
    def reset(self):
        self.index = None
        self.chunks = []
        logger.info("RAG reset")
    # 🔥 Load index safely
    def _load(self):
        try:
            if os.path.exists(INDEX_PATH) and os.path.exists(CHUNKS_PATH):
                self.index = faiss.read_index(INDEX_PATH)

                with open(CHUNKS_PATH, "rb") as f:
                    self.chunks = pickle.load(f)

                logger.info("Loaded RAG index: %s chunks", len(self.chunks))

        except Exception as e:
            logger.warning("Failed to load RAG index: %s", e)
            self.index = None
            self.chunks = []

    # 🔥 Save index safely
    def _save(self):
        try:
            if self.index:
                faiss.write_index(self.index, INDEX_PATH)

                with open(CHUNKS_PATH, "wb") as f:
                    pickle.dump(self.chunks, f)

                logger.debug("RAG index saved")

        except Exception as e:
            logger.warning("Failed to save RAG index: %s", e)

    # 🔥 Improved chunking (overlap for better context)
    def _word_chunk_text(self, text: str, size: int = 300, overlap: int = 50) -> List[str]:
        if not text or not text.strip():
            return []

        words = text.split()
        chunks = []

        for i in range(0, len(words), size - overlap):
            chunk = words[i:i + size]

            if len(chunk) > 30:
                chunks.append(" ".join(chunk))

        return chunks

    def _split_sentences(self, text: str) -> List[str]:
        # Keep punctuation with sentence for better semantic continuity.
        parts = re.split(r"(?<=[.!?])\s+", text)
        out = []
        for p in parts:
            s = re.sub(r"\s+", " ", p).strip()
            if s:
                out.append(s)
        return out

    def _semantic_chunk_text(
        self,
        text: str,
        target_words: int = 220,
        max_words: int = 320,
        min_words: int = 45,
        overlap_sentences: int = 2,
    ) -> List[str]:
        if not text or not text.strip():
            return []

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks: List[str] = []
        current: List[str] = []
        current_words = 0

        def emit_chunk() -> None:
            nonlocal current, current_words
            if not current:
                return
            chunk = " ".join(current).strip()
            if chunk:
                chunks.append(chunk)
            if overlap_sentences > 0:
                current = current[-overlap_sentences:]
                current_words = sum(len(s.split()) for s in current)
            else:
                current = []
                current_words = 0

        for para in paragraphs:
            sentences = self._split_sentences(para)
            if not sentences:
                continue

            # Heading-like short lines are treated as semantic boundaries.
            is_heading = len(sentences) == 1 and len(sentences[0].split()) <= 8 and sentences[0].endswith(":")
            if is_heading and current_words >= min_words:
                emit_chunk()

            for sentence in sentences:
                sent_words = len(sentence.split())
                if sent_words == 0:
                    continue

                if current_words + sent_words > max_words and current_words >= min_words:
                    emit_chunk()

                current.append(sentence)
                current_words += sent_words

                # Prefer natural boundaries when chunk is sufficiently dense.
                if current_words >= target_words and sentence.endswith((".", "!", "?", ":")):
                    emit_chunk()

        if current:
            chunk = " ".join(current).strip()
            if chunk:
                chunks.append(chunk)

        # Merge tiny tail chunks to avoid embedding waste on very short segments.
        merged: List[str] = []
        for chunk in chunks:
            wc = len(chunk.split())
            if merged and wc < min_words:
                merged[-1] = f"{merged[-1]} {chunk}".strip()
            else:
                merged.append(chunk)
        return merged

    def chunk_text(self, text, size=300, overlap=50):
        strategy = (os.getenv("RAG_CHUNKING_STRATEGY", "semantic") or "semantic").strip().lower()
        if strategy == "word":
            return self._word_chunk_text(text, size=size, overlap=overlap)
        return self._semantic_chunk_text(text)

    # 🔥 Ingest documents
    def ingest_documents(self, text, guide_text: str = "", source_name: str = ""):
        chunks = self.chunk_text(text)

        if not chunks:
            logger.warning("No valid chunks created")
            return

        embedding_inputs = []
        for chunk in chunks:
            if guide_text:
                embedding_inputs.append(
                    f"COURSE SYLLABUS GUIDE:\n{guide_text[:4000]}\n\nSOURCE DOCUMENT: {source_name or 'unknown'}\n\nCHUNK:\n{chunk}"
                )
            else:
                embedding_inputs.append(chunk)

        embeddings = self.get_embeddings(embedding_inputs)
        if not embeddings:
            logger.warning("Failed to generate embeddings")
            return
        embeddings = np.array(embeddings, dtype=np.float32)

        # 🔥 Initialize FAISS if needed
        if self.index is None:
            dim = embeddings.shape[1]
            self.index = faiss.IndexFlatL2(dim)
        elif getattr(self.index, "d", embeddings.shape[1]) != embeddings.shape[1]:
            # Reset stale index when embedding dimensionality changes.
            self.index = faiss.IndexFlatL2(embeddings.shape[1])
            self.chunks = []

        # 🔥 Add embeddings
        self.index.add(embeddings)
        self.chunks.extend(chunks)

        # 🔥 Persist
        self._save()

        if guide_text:
            logger.info("RAG ingested %s syllabus-guided chunks from %s", len(chunks), source_name or "unknown")
        else:
            logger.info("RAG ingested %s chunks", len(chunks))

    # 🔥 Retrieve relevant chunks
    def retrieve(self, query, k=3):
        if self.index is None or not self.chunks:
            return []

        query_lower = query.lower()

        # 🔥 Summary fallback (VERY IMPORTANT)
        if any(x in query_lower for x in ["pdf", "document", "summary", "proposal"]):
            return self.chunks[:k]

        try:
            q_embed = self.get_embeddings([query])
            if not q_embed:
                return []
            q_embed = np.array(q_embed, dtype=np.float32)

            # 🔥 Safe k handling
            k = min(k, len(self.chunks))

            distances, indices = self.index.search(np.array(q_embed), k)

            results = []
            for i in indices[0]:
                if 0 <= i < len(self.chunks):
                    results.append(self.chunks[i])

            return results

        except Exception as e:
            logger.error("RAG retrieve error: %s", str(e))
            return []

    def get_embeddings(self, texts):
        if not texts:
            return []
        vectors = []
        for text in texts:
            vector = self.embedding_service.embed_text(text)
            if vector:
                vectors.append(vector)
        return vectors