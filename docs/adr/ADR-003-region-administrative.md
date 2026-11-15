# ADR-003 — Région administrative déduite du code postal

**Statut** : accepté · 2026-11-15

## Contexte
Dans les fichiers réels, `parties[].address.region` vaut « QC » (la province), pas la région administrative.

## Décision
Déduire la région administrative (01 à 17) de la RTA (3 premiers caractères du code postal) de l'organisme acheteur
(`worker/ingestion/regions.py`), avec des exceptions par RTA et un repli sur 2 caractères. La même table est copiée
dans le lakehouse (`ref_fsa_region`).

## Conséquences
- Correspondance approximative pour certaines RTA rurales : l'interface l'indique (« Région déduite… approximative »).
- Les avis sans code postal québécois ont une région inconnue et passent le filtre régional (plan, section 10.3).
