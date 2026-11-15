# RadarAO

**Analyseur d'appels d'offres publics pour les PME québécoises.** RadarAO trouve les appels d'offres faits pour votre
entreprise, résume chaque dossier avec les pages sources, et prépare la liste de tout ce que vous devez fournir.

> Projet personnel de Frederik Blais. Spécification : [PLAN-RadarAO.md](PLAN-RadarAO.md) · Décisions : [docs/adr/](docs/adr/)

| Pilier | Ce que fait l'application | Technique |
|---|---|---|
| **Trouver** | Ingestion hebdomadaire des avis du SEAO (données ouvertes OCDS), tri selon le profil, score expliqué | pgvector, embeddings Voyage, reranking, LLM juge en sortie structurée |
| **Comprendre** | Lecture des PDF (devis, formulaires, addenda), fiche d'analyse où chaque champ renvoie à sa page | Orchestrateur-travailleurs, vérification **déterministe** des citations, évaluateur-optimiseur |
| **Soumissionner** | Liste de vérification, go / no-go, assistant qui répond en citant le dossier | Agent avec outils en lecture seule, citations natives |
| **Anticiper** | Repères de prix et **prévisions de renouvellement** de contrats | Lakehouse Databricks (bronze / argent / or) en tandem avec PostgreSQL |

## Architecture

```
Navigateur ──▶ web (Next.js) ──/api──▶ api (FastAPI) ──▶ PostgreSQL 16 + pgvector   (opérationnel)
                                         │                 Redis (files Celery)
                                         ▼                 S3 / MinIO (PDF)
                         worker-default / worker-analysis (Celery)
                           ├─ API Claude (Messages, Files, Batches) — via worker/llm/client.py seulement
                           ├─ Voyage AI (embeddings, rerank)
                           └─ Databricks (SQL serverless + Volumes) ──▶ couche or ──▶ cache PostgreSQL
CronJobs : ingestion SEAO · rafraîchissement du lakehouse · courriel hebdomadaire · purge Loi 25
```

- **P-ANALYSE** (cœur) : E0 prétraitement (PyMuPDF, détection des addenda, pages numérisées, tampon « [[D1 · p. 12]] ») →
  E1 planificateur (Opus) → E2 six travailleurs en parallèle (Sonnet, cache du document) → E3 fusion des addenda (code) →
  E4 vérificateur des citations (code) → E5 évaluateur (Opus, ≤ 2 boucles) → E6 liste de vérification et go / no-go.
  Chaque étape est reprenable; un échec partiel affiche ce qui a fonctionné.
- **Modèles** : `claude-haiku-5-5` (volume), `claude-sonnet-5-5` (travailleurs, juge, assistant), `claude-opus-5-5`
  (planification, évaluation) — tous dans `services/worker/llm/config.py`.

## Démarrer

```bash
cp .env.example .env      # clés facultatives : ANTHROPIC_API_KEY, VOYAGE_API_KEY, DATABRICKS_*
make dev                  # Docker Compose : web http://localhost:3000, API :8000, courriels http://localhost:8025
make seed                 # données de démonstration
```

Sans Docker (PostgreSQL 16 + pgvector et Redis locaux) :

```bash
cd services && uv sync && uv run alembic upgrade head && uv run python scripts/seed_demo.py
uv run uvicorn api.app.main:app --reload            # API
cd ../apps/web && npm ci && npm run dev             # web
```

Connexion : `julie@example.com`; le lien magique s'affiche dans la console de l'API (ou dans Mailpit).

## Qualité

| Commande | Contenu |
|---|---|
| `make test` | 40 tests : ingestion idempotente (fichier SEAO réel), vérificateur E4, addenda, pipeline complet, assistant, lakehouse, API et **isolation entre entreprises** |
| `make lint` | ruff, mypy strict, eslint, tsc |
| `make eval` / `make eval-live` | Mesures de la section 11.2 → `evals/reports/` |
| `make k8s-validate` | kustomize + kubeconform |

Dernier rapport hors ligne : [evals/reports/latest-hors-ligne.md](evals/reports/latest-hors-ligne.md). Les mesures d'extraction
exigent `make eval-live` (clé Claude).

## Déploiement
Kubernetes (Kustomize) : voir [infra/k8s/README.md](infra/k8s/README.md) et [ADR-006](docs/adr/ADR-006-docker-kubernetes.md).

## Données et licence
Données : Système électronique d'appel d'offres (SEAO), Secrétariat du Conseil du trésor, licence CC-BY 4.0.
RadarAO aide à lire les dossiers; il ne remplace ni la lecture complète du dossier, ni un conseiller juridique, et ne soumet
jamais rien au nom de l'utilisateur.
