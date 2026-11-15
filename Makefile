# RadarAO — commandes du projet (voir CLAUDE.md)
SHELL := /bin/bash
COMPOSE := docker compose -f infra/docker-compose.yml
SVC := cd services &&
WEB := cd apps/web &&

.PHONY: help dev down test lint format eval eval-live migrate seed openapi build images k8s-validate k8s-local api web worker

help:  ## Liste des commandes
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-14s %s\n", $$1, $$2}'

dev:  ## Démarre tout (Postgres, Redis, MinIO, Mailpit, API, workers, web) avec Docker Compose
	$(COMPOSE) up --build

down:  ## Arrête l'environnement local
	$(COMPOSE) down

api:  ## API seule, sans Docker (Postgres et Redis locaux)
	$(SVC) uv run uvicorn api.app.main:app --reload --port 8000

worker:  ## Worker Celery seul, sans Docker
	$(SVC) uv run celery -A worker.celery_app worker -Q default,analysis --loglevel INFO

web:  ## Interface web seule (npm run dev)
	$(WEB) npm run dev

test:  ## Tests unitaires et d'intégration (Python + typage web)
	$(SVC) uv run pytest -q
	$(WEB) npm run typecheck

lint:  ## ruff + mypy (Python), eslint + tsc (web)
	$(SVC) uv run ruff check . && uv run ruff format --check . && uv run mypy api worker
	$(WEB) npx eslint src && npm run typecheck

format:  ## Formate le code Python
	$(SVC) uv run ruff format . && uv run ruff check --fix .

eval:  ## Évaluations IA hors ligne (déterministes + tri) -> evals/reports/
	$(SVC) uv run python ../evals/run_evals.py

eval-live:  ## Évaluations complètes avec Claude (ANTHROPIC_API_KEY requise; coûte des jetons)
	$(SVC) uv run python ../evals/run_evals.py --live

migrate:  ## Migrations Alembic
	$(SVC) uv run alembic upgrade head

seed:  ## Données de démonstration (SEAO_FILE=chemin pour un vrai fichier hebdomadaire)
	$(SVC) uv run python scripts/seed_demo.py $(SEAO_FILE)

openapi:  ## Régénère openapi.json et le client TypeScript
	$(SVC) ENV=test uv run python -c "import json; from api.app.main import app; json.dump(app.openapi(), open('../apps/web/openapi.json','w'), ensure_ascii=False, indent=1)"
	$(WEB) npm run openapi

build:  ## Build de production du web
	$(WEB) npm run build

images:  ## Construit les images Docker
	docker build -f services/Dockerfile -t radarao-services:dev .
	docker build -t radarao-web:dev apps/web

k8s-validate:  ## Valide les manifestes Kubernetes (kustomize + kubeconform)
	@for o in base overlays/local overlays/prod; do \
	  echo "== $$o"; kustomize build infra/k8s/$$o | kubeconform -strict -summary -ignore-missing-schemas -kubernetes-version 1.31.0 - || exit 1; \
	done

k8s-local: images  ## Déploie sur une grappe kind locale (kind create cluster --name radarao)
	kind load docker-image radarao-services:dev radarao-web:dev --name radarao
	kubectl apply -k infra/k8s/overlays/local
	kubectl -n radarao wait --for=condition=complete job/migrate --timeout=300s
