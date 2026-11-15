# ADR-004 — Table `contract_awards` pour l'historique (F9)

**Statut** : accepté · 2026-11-15

## Contexte
F9 exige des calculs en SQL. Les adjudications sont imbriquées dans le JSON OCDS (`awards[].suppliers[]`, `contracts[]`).

## Décision
L'ingestion aplatit chaque adjudication × fournisseur dans `contract_awards` (montant, date, organisme, code UNSPSC principal,
région, nombre de soumissionnaires). Clé d'unicité (ocid, award_id, fournisseur). Le LLM ne fait que résumer des chiffres déjà calculés.

## Conséquences
- Statistiques immédiates sur les fichiers récents dans PostgreSQL.
- L'historique complet (depuis 2021 en JSON, 2009 en XML) vit dans le lakehouse (ADR-005).
