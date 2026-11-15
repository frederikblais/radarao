# Déploiement Kubernetes

```
infra/k8s/
  base/                 api, web, worker-default, worker-analysis, migrate (Job), cronjobs, ingress, networkpolicies
  overlays/local/       grappe kind/k3d : Postgres+pgvector, Redis, MinIO, Mailpit dans la grappe
  overlays/prod/        services gérés (région canadienne), External Secrets, étiquettes d'images figées
```

## Grappe locale (kind)

```bash
kind create cluster --name radarao
make k8s-local                    # construit les images, les charge dans kind, applique l'overlay local
kubectl -n radarao port-forward svc/web 8080:3000
```

## Production
1. PostgreSQL 16 géré avec l'extension `vector`, Redis géré, compartiment S3 chiffré — en région canadienne (Loi 25).
2. Opérateur External Secrets + `ClusterSecretStore` nommé `radarao-store`; secret `radarao/production` contenant :
   `DATABASE_URL, REDIS_URL, SECRET_KEY, S3_ACCESS_KEY, S3_SECRET_KEY, ANTHROPIC_API_KEY, VOYAGE_API_KEY,
   DATABRICKS_HOST, DATABRICKS_TOKEN, DATABRICKS_WAREHOUSE_ID, SMTP_USER, SMTP_PASSWORD, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET`.
3. ingress-nginx et cert-manager (`ClusterIssuer` nommé `letsencrypt`); remplacer `radarao.example.ca`.
4. `kubectl apply -k infra/k8s/overlays/prod` (ou Argo CD : le Job `migrate` est un hook PreSync).

## Tâches planifiées (heure de l'Est)
| CronJob | Horaire | Tâche |
|---|---|---|
| seao-ingest | lun. et mar. 7 h 17 | dernier fichier hebdomadaire → tri → alertes → lakehouse |
| lakehouse-refresh | tous les jours 3 h 41 | argent + or Databricks → cache PostgreSQL |
| weekly-digest | lun. 8 h 23 | courriel récapitulatif |
| purge-loi25 | tous les jours 2 h 07 | suppression des dossiers expirés (BD, S3, Files API) |

Exécution manuelle : `kubectl -n radarao create job --from=cronjob/seao-ingest ingest-manuel`.
