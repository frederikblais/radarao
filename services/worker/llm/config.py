"""SEUL endroit où figurent les identifiants de modèles et leurs prix (section 10.2)."""

from dataclasses import dataclass

HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"


@dataclass(frozen=True)
class Role:
    model: str
    effort: str
    max_tokens: int


# Rôle -> modèle. Changer un modèle ici change tout le pipeline.
ROLES: dict[str, Role] = {
    "enrichment": Role(HAIKU, "low", 2_000),
    "unspsc_suggest": Role(HAIKU, "low", 2_000),
    "match_judge": Role(SONNET, "low", 2_000),
    "planner": Role(OPUS, "high", 16_000),
    "worker": Role(SONNET, "medium", 16_000),
    "evaluator": Role(OPUS, "high", 16_000),
    "synthesis": Role(SONNET, "medium", 16_000),
    "assistant": Role(SONNET, "medium", 8_000),
    "market_summary": Role(HAIKU, "low", 1_500),
}

# Prix en USD par million de jetons (page « Models overview », relevés le 2026-11-03).
# (entrée, sortie, lecture de cache). L'écriture de cache (5 min) coûte 1,25 × l'entrée.
PRICES: dict[str, tuple[float, float, float]] = {
    HAIKU: (0.10, 0.50, 0.01),
    SONNET: (2.00, 10.00, 0.10),
    OPUS: (4.00, 20.00, 0.20),
}

# Repli côté serveur en cas de refus du classificateur (bêta), activé par défaut.
REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"
ENABLE_REFUSAL_FALLBACKS = True
FALLBACK_CAPABLE = {OPUS, SONNET}

MAX_ATTEMPTS = 5
BACKOFF_BASE_S = 1.0
BATCH_DISCOUNT = 0.5


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0,
             cache_creation: int = 0, batch: bool = False) -> float:
    p_in, p_out, p_cache = PRICES.get(model, PRICES[OPUS])
    cost = (input_tokens * p_in + output_tokens * p_out + cache_read * p_cache
            + cache_creation * p_in * 1.25) / 1_000_000
    return round(cost * (BATCH_DISCOUNT if batch else 1.0), 6)
