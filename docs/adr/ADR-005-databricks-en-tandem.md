# ADR-005 — Databricks en tandem avec PostgreSQL

**Statut** : accepté · 2026-11-15 (demande de Frederik : utiliser Databricks là où il ajoute de la valeur)

## Contexte
Frederik dispose d'un compte Databricks (édition gratuite). Remplacer PostgreSQL serait une erreur : l'application fait des
écritures transactionnelles fréquentes et à faible latence (sessions, listes de vérification, champs corrigés, files de tâches)
et a besoin de pgvector à côté des données relationnelles. Un entrepôt SQL serverless démarre à froid en quelques secondes.

## Décision
- **PostgreSQL** reste la base opérationnelle (OLTP) : comptes, profils, avis actifs, dossiers, fiches, vecteurs.
- **Databricks** devient le lakehouse analytique de l'historique des données ouvertes du SEAO, en architecture médaillon :
  - bronze `bronze_releases` : chaque publication OCDS brute (NDJSON déposé dans un Volume Unity Catalog, MERGE idempotent);
  - argent `silver_tenders`, `silver_awards` : dernière version de chaque processus, adjudications aplaties, région déduite;
  - or `gold_market_benchmarks` et `gold_renewal_forecasts`.
- Trois fonctionnalités en tirent leur valeur :
  1. **F9 à grande échelle** : statistiques sur tout l'historique, pas seulement sur les dernières semaines;
  2. **Repères de prix** dans le go / no-go : distribution des montants adjugés pour des contrats semblables (classe UNSPSC × région);
  3. **Prévisions de renouvellement** (nouveau) : un organisme qui rachète périodiquement le même type de contrat va probablement
     republier un avis; date prévue = dernière adjudication + intervalle médian, avec une confiance selon la régularité.
     La PME est prévenue *avant* la publication, ce qui compense en partie le décalage d'une semaine des données ouvertes.
- La couche or est recopiée dans PostgreSQL (`market_benchmarks`, `renewal_forecasts`) : l'application lit toujours PostgreSQL.
- Intégration par les API REST (Statement Execution API et Files API) avec `httpx` : aucune dépendance de plus, fonctionne avec
  un entrepôt SQL serverless de l'édition gratuite. Les transformations sont des fichiers SQL versionnés (`databricks/sql/`).
- **Repli** : sans Databricks configuré (ou en cas d'échec), `worker/lakehouse/local.py` calcule les mêmes tables à partir de
  `contract_awards` avec les mêmes règles. Le lakehouse ne bloque jamais l'ingestion opérationnelle.
- **Confidentialité** : aucune donnée de client (profil, documents, questions) n'est envoyée à Databricks.

## Conséquences
- Rattrapage historique : `python -m worker.lakehouse backfill 2021-03` (fichiers mensuels JSON). L'historique XML 2009–2021 est
  une étape ultérieure.
- CronJob quotidien `lakehouse-refresh` (argent + or + synchronisation).
- À surveiller : coût de l'entrepôt SQL hors édition gratuite; limites de l'édition gratuite (calcul serverless seulement).
