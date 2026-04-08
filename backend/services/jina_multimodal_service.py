import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class JinaMultimodalService:
    """Lightweight multimodal embedding service with real semantic embeddings."""

    def __init__(self, embedding_dim: int = 2048):
        """Initialize with real embedding model or fallback."""
        self.model = None
        self.embedding_dim = embedding_dim
        self.model_name = None
        
        # Try to load Jina embeddings v3 (2048-dim)
        try:
            from sentence_transformers import SentenceTransformer
            
            logger.info("Attempting to load jinaai/jina-embeddings-v3 model...")
            self.model = SentenceTransformer("jinaai/jina-embeddings-v3", trust_remote_code=True)
            self.model_name = "jinaai/jina-embeddings-v3"
            logger.info(f"Loaded {self.model_name} ({self.embedding_dim}-dim embeddings)")
            
        except Exception as e:
            logger.warning(f"Failed to load Jina model: {str(e)}. Attempting cache repair...")

            if self._repair_jina_cache() and self._retry_load_jina_model():
                return

            logger.warning("Jina model still unavailable after cache repair. Attempting fallback...")
            
            # Fall back to all-MiniLM-L6-v2 (384-dim)
            try:
                from sentence_transformers import SentenceTransformer
                
                logger.info("Loading fallback model: all-MiniLM-L6-v2...")
                self.model = SentenceTransformer("all-MiniLM-L6-v2")
                self.model_name = "all-MiniLM-L6-v2"
                logger.warning(
                    "Jina model unavailable, using fallback embeddings (384-dim). "
                    "Semantic quality degraded."
                )
                
            except Exception as fallback_error:
                logger.error(
                    f"Failed to load fallback model: {str(fallback_error)}. "
                    "Embeddings will be unavailable."
                )
                self.model = None
                self.model_name = "none"

    def _repair_jina_cache(self) -> bool:
        """Best-effort cleanup for corrupted remote-code cache modules."""
        try:
            cache_root = Path.home() / ".cache" / "huggingface" / "modules" / "transformers_modules" / "jinaai"
            if not cache_root.exists():
                return False
            shutil.rmtree(cache_root, ignore_errors=True)
            logger.info("Removed stale Hugging Face Jina transformers module cache")
            return True
        except Exception as e:
            logger.warning(f"Cache repair failed: {str(e)}")
            return False

    def _retry_load_jina_model(self) -> bool:
        """Retry Jina model load after cache cleanup."""
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer("jinaai/jina-embeddings-v3", trust_remote_code=True)
            self.model_name = "jinaai/jina-embeddings-v3"
            logger.info(f"Loaded {self.model_name} after cache repair")
            return True
        except Exception as e:
            logger.warning(f"Retry load failed: {str(e)}")
            return False

    def embed_text(self, text: str) -> List[float]:
        """Embed text using loaded model or return zero vector."""
        if not self.model:
            logger.warning("No embedding model available, returning zero vector")
            return [0.0] * self.embedding_dim
        
        try:
            # Clean and validate input
            text = (text or "").strip()
            if not text:
                return [0.0] * self.embedding_dim
            
            # Generate embedding
            embedding = self.model.encode(text, convert_to_numpy=True)
            
            # Normalize to unit vector
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            # Keep output shape stable for downstream stores/tests.
            if embedding.shape[0] > self.embedding_dim:
                embedding = embedding[: self.embedding_dim]
            elif embedding.shape[0] < self.embedding_dim:
                embedding = np.pad(
                    embedding,
                    (0, self.embedding_dim - embedding.shape[0]),
                    mode="constant",
                )
            
            return embedding.astype(np.float32).tolist()
            
        except Exception as e:
            logger.error(f"Error embedding text: {str(e)}")
            return [0.0] * self.embedding_dim

    def embed_image(self, image_path: str, hint_text: Optional[str] = None) -> List[float]:
        """
        Embed image using hint text or image metadata.
        
        Since the embedding model is text-based, we use the image filename
        and hint text as a fallback. For multimodal images, pass hint_text
        with a description of the image content.
        
        Args:
            image_path: Path to image file
            hint_text: Optional description of image content
        
        Returns:
            Embedding vector
        """
        if not self.model:
            logger.warning("No embedding model available, returning zero vector")
            return [0.0] * self.embedding_dim
        
        try:
            # Use image filename and hint text
            file_name = os.path.splitext(os.path.basename(image_path))[0]
            text_parts = [file_name]
            
            if hint_text:
                text_parts.append(hint_text)
            
            # Combine text and embed
            combined_text = " ".join(text_parts)
            return self.embed_text(combined_text)
            
        except Exception as e:
            logger.error(f"Error embedding image: {str(e)}")
            return [0.0] * self.embedding_dim

    def embed_diagram(self, image_path: str, description: str = "") -> List[float]:
        """Embed diagram using description."""
        return self.embed_image(image_path=image_path, hint_text=description)

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two embedding vectors."""
        av = np.array(a, dtype=np.float32)
        bv = np.array(b, dtype=np.float32)
        an = np.linalg.norm(av)
        bn = np.linalg.norm(bv)
        if an == 0 or bn == 0:
            return 0.0
        return float(np.dot(av, bv) / (an * bn))

    def retrieve(self, query: str, candidates: List[Dict], top_k: int = 3) -> List[Dict]:
        """Retrieve top-k candidates most similar to query."""
        query_vec = self.embed_text(query)
        scored = []
        for item in candidates:
            emb = item.get("embedding")
            if emb is None:
                continue
            score = self.cosine_similarity(query_vec, emb)
            scored.append({**item, "score": score})

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]
