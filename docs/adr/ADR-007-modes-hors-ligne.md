# ADR-007 — Fonctionnement sans clés d'IA

**Statut** : accepté · 2026-11-15

## Décision
- `AI_MODE=offline` : aucun appel à Claude; embeddings et reranking lexicaux déterministes (`worker/embeddings.py`);
  juge de pertinence heuristique; synthèse go / no-go par règles. L'analyse de dossier exige une clé (elle échoue proprement).
- Les tests utilisent un faux backend Claude (`worker/tests/fakes.py`) et de vrais PDF générés.
- `make seed` crée un dossier « [DÉMO] … réponses simulées » pour montrer l'interface sans clé : il est étiqueté comme tel.
- `/health/ready` indique le mode réel (llm, embeddings, lakehouse).

## Conséquences
Les mesures d'extraction (section 11.2) ne sont valables qu'en mode `--live`; le rapport hors ligne les marque « non mesuré ».
