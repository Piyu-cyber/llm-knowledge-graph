import hashlib
import os
import re
from typing import Dict, List, Optional

import numpy as np


class JinaMultimodalService:
    """Lightweight multimodal embedding service with Jina-compatible 2048-d output."""

    EMBEDDING_DIM = 2048

    def __init__(self, embedding_dim: int = EMBEDDING_DIM):
        self.embedding_dim = embedding_dim
        self._token_cache: Dict[str, np.ndarray] = {}

    def _tokenize(self, text: str) -> List[str]:
        return [t for t in re.split(r"[^a-zA-Z0-9]+", text.lower()) if t]

    def _token_vector(self, token: str) -> np.ndarray:
        if token in self._token_cache:
            return self._token_cache[token]

        seed_hex = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        seed = int(seed_hex, 16)
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(self.embedding_dim).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        self._token_cache[token] = vec
        return vec

    def _embed_tokens(self, tokens: List[str]) -> List[float]:
        if not tokens:
            return [0.0] * self.embedding_dim

        vectors = [self._token_vector(t) for t in tokens]
        combined = np.mean(np.stack(vectors), axis=0)
        norm = np.linalg.norm(combined)
        if norm > 0:
            combined = combined / norm
        return combined.astype(np.float32).tolist()

    def embed_text(self, text: str) -> List[float]:
        return self._embed_tokens(self._tokenize(text))

    def embed_image(self, image_path: str, hint_text: Optional[str] = None) -> List[float]:
        file_name = os.path.splitext(os.path.basename(image_path))[0]
        tokens = self._tokenize(file_name)

        if hint_text:
            tokens.extend(self._tokenize(hint_text))

        if os.path.exists(image_path):
            with open(image_path, "rb") as f:
                digest = hashlib.sha256(f.read(1024)).hexdigest()[:16]
            tokens.append(f"img_{digest}")

        return self._embed_tokens(tokens)

    def embed_diagram(self, image_path: str, description: str = "") -> List[float]:
        return self.embed_image(image_path=image_path, hint_text=description)

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        av = np.array(a, dtype=np.float32)
        bv = np.array(b, dtype=np.float32)
        an = np.linalg.norm(av)
        bn = np.linalg.norm(bv)
        if an == 0 or bn == 0:
            return 0.0
        return float(np.dot(av, bv) / (an * bn))

    def retrieve(self, query: str, candidates: List[Dict], top_k: int = 3) -> List[Dict]:
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
