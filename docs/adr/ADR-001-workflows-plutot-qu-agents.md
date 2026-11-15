# ADR-001 — Des workflows d'abord, un agent seulement pour l'assistant

**Statut** : accepté · 2026-11-15

## Contexte
Le plan (section 10.1) distingue les workflows (chemins de code prévisibles) et les agents (le LLM choisit ses étapes).
Un service web multi-utilisateur doit maîtriser les coûts, les reprises, l'isolation et la journalisation.

## Décision
- Ingestion, tri, analyse de dossier, go / no-go : workflows orchestrés dans notre code (Celery), avec l'API Messages du SDK `anthropic`.
- Seul l'assistant de questions-réponses (P-ASSISTANT) est un agent (boucle d'outils en lecture seule, 8 tours au maximum).
- Pas de Claude Agent SDK : il est conçu pour des agents qui travaillent dans un système de fichiers.

## Conséquences
- Chaque étape de P-ANALYSE est reprenable (`jobs.completed_steps`, `jobs.state`).
- Un client unique (`worker/llm/client.py`) applique reprises, budgets et journalisation (`llm_calls`).
