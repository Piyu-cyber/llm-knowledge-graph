import json
import os
from typing import Dict, List, Optional

import faiss
import numpy as np


class LocalVectorStore:
    """FAISS-backed vector store with persistent id/metadata mapping."""

    def __init__(self, dim: int, data_dir: str = "data", index_name: str = "rag_index"):
        self.dim = int(dim)
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

        self.index_path = os.path.join(self.data_dir, f"{index_name}.faiss")
        self.meta_path = os.path.join(self.data_dir, f"{index_name}_meta.json")

        self.ids: List[str] = []
        self.metadata: Dict[str, Dict] = {}
        self.texts: Dict[str, str] = {}
        self._index = faiss.IndexFlatIP(self.dim)

        self._load()

    def _normalize(self, vec: List[float]) -> np.ndarray:
        arr = np.array(vec, dtype="float32").reshape(1, -1)
        if arr.shape[1] != self.dim:
            raise ValueError(f"Expected vector dim={self.dim}, got dim={arr.shape[1]}")
        faiss.normalize_L2(arr)
        return arr

    def _load(self) -> None:
        if os.path.exists(self.index_path):
            self._index = faiss.read_index(self.index_path)

        if os.path.exists(self.meta_path):
            with open(self.meta_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.ids = list(payload.get("ids", []))
            self.metadata = dict(payload.get("metadata", {}))
            self.texts = dict(payload.get("texts", {}))

    def _persist(self) -> None:
        faiss.write_index(self._index, self.index_path)
        payload = {
            "ids": self.ids,
            "metadata": self.metadata,
            "texts": self.texts,
        }
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def upsert(self, record_id: str, vector: List[float], metadata: Optional[Dict] = None, text: str = "") -> None:
        """Upsert by rebuilding index to preserve id stability for small/medium workloads."""
        rid = str(record_id)
        metadata = metadata or {}

        if rid in self.ids:
            idx = self.ids.index(rid)
            self.ids.pop(idx)
            self._rebuild_without_index(idx)

        self.ids.append(rid)
        self.metadata[rid] = metadata
        self.texts[rid] = text
        self._index.add(self._normalize(vector))
        self._persist()

    def _rebuild_without_index(self, removed_index: int) -> None:
        if self._index.ntotal == 0:
            self._index = faiss.IndexFlatIP(self.dim)
            return
        vectors = self._index.reconstruct_n(0, self._index.ntotal)
        kept = np.delete(vectors, removed_index, axis=0)
        self._index = faiss.IndexFlatIP(self.dim)
        if kept.size > 0:
            self._index.add(kept)

    def query(self, vector: List[float], top_k: int = 5) -> List[Dict]:
        if self._index.ntotal == 0:
            return []

        k = max(1, min(int(top_k), self._index.ntotal))
        scores, indices = self._index.search(self._normalize(vector), k)

        results: List[Dict] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self.ids):
                continue
            rid = self.ids[idx]
            results.append(
                {
                    "id": rid,
                    "score": float(score),
                    "metadata": self.metadata.get(rid, {}),
                    "text": self.texts.get(rid, ""),
                }
            )
        return results

    def count(self) -> int:
        return int(self._index.ntotal)
