import logging
import os
import shutil
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import numpy as np

logger = logging.getLogger(__name__)


class JinaMultimodalService:
    """Lightweight multimodal embedding service with real semantic embeddings."""

    _MODEL_CACHE: Dict[str, Any] = {}
    _CACHE_LOCK = threading.Lock()

    def __init__(self, embedding_dim: int = 2048):
        """Initialize embedding service with lazy model loading."""
        self.model = None
        self.embedding_dim = embedding_dim
        self.model_name = None
        self._load_attempted = False

        self.provider = (os.getenv("OMNIPROF_EMBEDDING_PROVIDER", "auto") or "auto").strip().lower()
        self.jina_api_key = (os.getenv("JINA_API_KEY", "") or "").strip()
        self.jina_embedding_url = (os.getenv("JINA_EMBEDDING_URL", "https://api.jina.ai/v1/embeddings") or "").strip()
        self.jina_embedding_model = (os.getenv("JINA_EMBEDDING_MODEL", "jina-embeddings-v3") or "jina-embeddings-v3").strip()
        self.jina_embedding_task = (os.getenv("JINA_EMBEDDING_TASK", "text-matching") or "").strip()
        self.jina_embedding_normalized = (os.getenv("JINA_EMBEDDING_NORMALIZED", "true") or "true").strip().lower() == "true"
        self.jina_timeout_seconds = float(os.getenv("JINA_EMBEDDING_TIMEOUT_SECONDS", "20") or "20")
        self.api_strict = (os.getenv("OMNIPROF_EMBEDDING_API_STRICT", "false") or "false").strip().lower() == "true"

        if self.provider == "api":
            self.active_provider = "api" if self.jina_api_key else "local"
        elif self.provider == "local":
            self.active_provider = "local"
        else:
            self.active_provider = "api" if self.jina_api_key else "local"
        self._api_disabled_reason: Optional[str] = None

        self._text_cache_max_entries = max(0, int(os.getenv("EMBEDDING_TEXT_CACHE_MAX_ENTRIES", "256") or "256"))
        self._text_cache: OrderedDict[str, List[float]] = OrderedDict()

        self.primary_model = os.getenv("OMNIPROF_EMBEDDING_MODEL", "all-MiniLM-L6-v2").strip() or "all-MiniLM-L6-v2"
        self.fallback_model = "all-MiniLM-L6-v2" if self.primary_model != "all-MiniLM-L6-v2" else None

        if self.active_provider == "api":
            self.model_name = f"api:{self.jina_embedding_model}"
            logger.info("Embedding provider configured: api (%s)", self.jina_embedding_model)
            return

        # Reuse already loaded model when available to avoid repeated 1-2GB loads.
        with self._CACHE_LOCK:
            if self.primary_model in self._MODEL_CACHE:
                self.model = self._MODEL_CACHE[self.primary_model]
                self.model_name = self.primary_model
                logger.info("Reusing cached %s model", self.model_name)
                return
            if self.fallback_model and self.fallback_model in self._MODEL_CACHE:
                self.model = self._MODEL_CACHE[self.fallback_model]
                self.model_name = self.fallback_model
                logger.info("Reusing cached %s model", self.model_name)
                return

    def _ensure_model_loaded(self) -> None:
        """Load model only when embeddings are first requested."""
        if self.model is not None:
            return

        with self._CACHE_LOCK:
            if self.model is not None:
                return

            cached = self._MODEL_CACHE.get(self.primary_model)
            if cached is None and self.fallback_model:
                cached = self._MODEL_CACHE.get(self.fallback_model)
            if cached is not None:
                self.model = cached
                self.model_name = self.primary_model if self.primary_model in self._MODEL_CACHE else self.fallback_model
                logger.info("Reusing cached %s model", self.model_name)
                return

            if self._load_attempted:
                return
            self._load_attempted = True

            # Try configured primary model first.
            try:
                from sentence_transformers import SentenceTransformer

                logger.info("Attempting to load embedding model: %s", self.primary_model)
                if self.primary_model.startswith("jinaai/"):
                    self.model = SentenceTransformer(self.primary_model, trust_remote_code=True)
                else:
                    self.model = SentenceTransformer(self.primary_model)
                self.model_name = self.primary_model
                self._MODEL_CACHE[self.model_name] = self.model
                logger.info("Loaded %s (%s-dim embeddings)", self.model_name, self.embedding_dim)
                return

            except Exception as e:
                logger.warning("Failed to load primary model %s: %s", self.primary_model, str(e))

                if self.primary_model.startswith("jinaai/"):
                    logger.warning("Attempting Jina cache repair...")
                    if self._repair_jina_cache() and self._retry_load_jina_model():
                        if self.model_name:
                            self._MODEL_CACHE[self.model_name] = self.model
                        return

                if not self.fallback_model:
                    logger.error("No fallback embedding model configured.")
                    self.model = None
                    self.model_name = "none"
                    return

                logger.warning("Primary model unavailable. Attempting fallback: %s", self.fallback_model)

                # Fall back to all-MiniLM-L6-v2 (384-dim)
                try:
                    from sentence_transformers import SentenceTransformer

                    self.model = SentenceTransformer(self.fallback_model)
                    self.model_name = self.fallback_model
                    self._MODEL_CACHE[self.model_name] = self.model
                    logger.warning(
                        "Using fallback embeddings model (%s). Semantic quality may be reduced.",
                        self.fallback_model,
                    )

                except Exception as fallback_error:
                    logger.error(
                        "Failed to load fallback model: %s. Embeddings will be unavailable.",
                        str(fallback_error),
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
            with self._CACHE_LOCK:
                self._MODEL_CACHE[self.model_name] = self.model
            logger.info(f"Loaded {self.model_name} after cache repair")
            return True
        except Exception as e:
            logger.warning(f"Retry load failed: {str(e)}")
            return False

    def embed_text(self, text: str) -> List[float]:
        """Embed text using API or local model based on configuration."""
        text = (text or "").strip()
        if not text:
            return [0.0] * self.embedding_dim

        cached = self._cache_get(text)
        if cached is not None:
            return cached

        if self.active_provider == "api":
            vec = self._embed_text_via_api(text)
            if vec is not None:
                self._cache_put(text, vec)
                return vec

            if self.api_strict:
                logger.warning("API embedding failed in strict mode; returning zero vector")
                return [0.0] * self.embedding_dim

            logger.warning("API embedding failed; falling back to local model")

        self._ensure_model_loaded()
        if not self.model:
            logger.warning("No embedding model available, returning zero vector")
            return [0.0] * self.embedding_dim

        try:
            embedding = self.model.encode(text, convert_to_numpy=True)
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            out = self._normalize_embedding(np.array(embedding, dtype=np.float32).tolist())
            self._cache_put(text, out)
            return out
        except Exception as e:
            logger.error(f"Error embedding text: {str(e)}")
            return [0.0] * self.embedding_dim

    def _embed_text_via_api(self, text: str) -> Optional[List[float]]:
        if not self.jina_api_key or self.active_provider != "api":
            return None

        payload = {
            "model": self.jina_embedding_model,
            "input": [text],
        }
        if self.jina_embedding_task:
            payload["task"] = self.jina_embedding_task
        payload["normalized"] = self.jina_embedding_normalized

        headers = {
            "Authorization": f"Bearer {self.jina_api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=self.jina_timeout_seconds) as client:
                res = client.post(self.jina_embedding_url, headers=headers, json=payload)
                res.raise_for_status()
                data = res.json()
            rows = data.get("data") or []
            if not rows:
                return None
            emb = rows[0].get("embedding")
            if not emb:
                return None
            return self._normalize_embedding(emb)
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code if e.response is not None else None
            # 401/403 are persistent auth/config failures; stop retrying API for this process.
            if status_code in (401, 403):
                if self._api_disabled_reason is None:
                    self._api_disabled_reason = f"HTTP {status_code}"
                    logger.warning(
                        "Disabling Jina API embeddings after authentication failure (%s); "
                        "switching to local model fallback.",
                        self._api_disabled_reason,
                    )
                self.active_provider = "local"
            logger.warning("Jina API embedding request failed: %s", str(e))
            return None
        except Exception as e:
            logger.warning("Jina API embedding request failed: %s", str(e))
            return None

    def _normalize_embedding(self, emb: List[float]) -> List[float]:
        arr = np.array(emb, dtype=np.float32).flatten()
        if arr.shape[0] > self.embedding_dim:
            arr = arr[: self.embedding_dim]
        elif arr.shape[0] < self.embedding_dim:
            arr = np.pad(arr, (0, self.embedding_dim - arr.shape[0]), mode="constant")
        return arr.astype(np.float32).tolist()

    def _cache_get(self, text: str) -> Optional[List[float]]:
        if self._text_cache_max_entries <= 0:
            return None
        val = self._text_cache.get(text)
        if val is None:
            return None
        self._text_cache.move_to_end(text)
        return val

    def _cache_put(self, text: str, embedding: List[float]) -> None:
        if self._text_cache_max_entries <= 0:
            return
        self._text_cache[text] = embedding
        self._text_cache.move_to_end(text)
        while len(self._text_cache) > self._text_cache_max_entries:
            self._text_cache.popitem(last=False)

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
        self._ensure_model_loaded()
        
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
