# ADR-006 — Docker et Kubernetes

**Statut** : accepté · 2026-11-15 (demande de Frederik : infrastructure solide avec Docker et Kubernetes)

## Décision
- **Images** : une image Python (`services/Dockerfile`, uv, utilisateur non-root) pour l'API, les workers, les migrations et
  les CronJobs; une image Next.js `standalone` (`apps/web/Dockerfile`). Publiées sur GHCR par la CI.
- **Local** : Docker Compose (`make dev`) avec Postgres+pgvector, Redis, MinIO, Mailpit.
- **Kubernetes** (Kustomize, `infra/k8s`) :
  - Deployments `api`, `web`, `worker-default`, `worker-analysis` (files Celery séparées : les analyses longues ne bloquent pas
    les alertes), HPA, PodDisruptionBudgets, sondes, ressources, conteneurs en lecture seule et sans privilèges.
  - Job de migration (hook PreSync) avant chaque déploiement.
  - **CronJobs** plutôt que Celery beat en production : ingestion SEAO, rafraîchissement du lakehouse, courriel hebdomadaire,
    purge Loi 25. Un échec est visible dans Kubernetes (statut, reprises, historique).
  - NetworkPolicies : refus par défaut; seul l'ingress parle au web, seul le web parle à l'API.
  - Le web relaie `/api/*` vers l'API (même origine : cookie HttpOnly sans CORS; URL interne lue à l'exécution).
  - Overlays : `local` (kind/k3d, bases dans la grappe) et `prod` (services gérés en région canadienne, External Secrets).
- Validation en CI : `kustomize build | kubeconform -strict`.

## Conséquences
- Les secrets ne sont jamais versionnés (`radarao-secrets` créé par External Secrets en production).
- Le plan d'hébergement exact (fournisseur, grappe gérée) reste à choisir; contrainte : région canadienne (Loi 25).
