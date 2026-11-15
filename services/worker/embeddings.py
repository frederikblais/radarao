"""Embeddings et reranking (Voyage AI). En mode hors ligne : repli lexical déterministe.

Le repli n'est PAS sémantique; il sert au développement local, aux tests et à la démo sans clé.
L'interface affiche le mode utilisé (voir /health).
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from api.app.config import get_settings
from api.app.models.base import EMBED_DIM

EMBED_MODEL = os.environ.get("VOYAGE_EMBED_MODEL", "voyage-4")
RERANK_MODEL = os.environ.get("VOYAGE_RERANK_MODEL", "rerank-3")

_STOP = set(
    "le la les de des du un une et en au aux pour par sur dans avec ou a l d est sont ce ces que qui "
    "nous vous leur leurs son sa ses the of and to in for on".split()
)


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]{2,}", normalize_text(s)) if t not in _STOP]


def _stem(t: str) -> str:
    for suf in ("ements", "ement", "ations", "ation", "ages", "age", "eurs", "eur", "es", "s", "e"):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[: -len(suf)]
    return t


def hashed_embedding(text: str) -> list[float]:
    vec = [0.0] * EMBED_DIM
    toks = [_stem(t) for t in tokens(text)]
    feats = toks + [a + "_" + b for a, b in zip(toks, toks[1:], strict=False)]
    for f in feats:
        h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
        vec[h % EMBED_DIM] += 1.0 if (h >> 32) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@dataclass
class RerankHit:
    index: int
    score: float


class Embedder:
    def __init__(self) -> None:
        s = get_settings()
        self.offline = s.ai_mode == "offline" or not s.voyage_api_key
        self._client: Any = None
        if not self.offline:
            import voyageai

            self._client = voyageai.Client(api_key=s.voyage_api_key)

    @property
    def mode(self) -> str:
        return "offline-lexical" if self.offline else f"voyage:{EMBED_MODEL}"

    def embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        """input_type : « query » pour le profil, « document » pour les avis et les pages."""
        if not texts:
            return []
        if self.offline:
            return [hashed_embedding(t) for t in texts]
        out: list[list[float]] = []
        for i in range(0, len(texts), 128):
            res = self._client.embed(texts[i:i + 128], model=EMBED_MODEL, input_type=input_type,
                                     output_dimension=EMBED_DIM)
            out.extend(res.embeddings)
        return out

    def rerank(self, query: str, documents: list[str], top_k: int) -> list[RerankHit]:
        if not documents:
            return []
        if self.offline:
            q = {_stem(t) for t in tokens(query)}
            hits = []
            for i, d in enumerate(documents):
                dt = [_stem(t) for t in tokens(d)]
                overlap = sum(1 for t in dt if t in q)
                hits.append(RerankHit(i, overlap / math.sqrt(len(dt) + 1)))
            return sorted(hits, key=lambda h: -h.score)[:top_k]
        res = self._client.rerank(query, documents, model=RERANK_MODEL, top_k=top_k)
        return [RerankHit(r.index, float(r.relevance_score)) for r in res.results]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
