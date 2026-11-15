# Rapport d'évaluation RadarAO — 20261115-022056 (hors-ligne)

| Mesure | Valeur | Seuil MVP | Statut | Détail |
|---|---|---|---|---|
| Prompts : contenu des documents = donnée | 1.00 | 100 % | ✅ | tous les prompts |
| Appels à Claude hors de llm/client.py | 0 | 0 | ✅ |  |
| Outils de l'assistant en lecture seule | 1.00 | 100 % | ✅ | rechercher_dossier, lire_pages, obtenir_fiche, obtenir_profil, historique_marche |
| Précision@10 du tri | 0.71 | ≥ 0,70 | ✅ | hors ligne : embeddings lexicaux + juge heuristique · julie : 1.00 (10/10 résultats annotés) ; marc : 0.80 (10/10 résultats annotés) ; sophie : 0.33 (9/10 résultats annotés) |
| Exactitude de la date limite de dépôt | — | 100 % | — | non mesuré : nécessite --live (ANTHROPIC_API_KEY) |
| Exactitude des champs critiques | — | ≥ 95 % | — | non mesuré : nécessite --live (ANTHROPIC_API_KEY) |
| Rappel des documents à remettre | — | ≥ 90 % | — | non mesuré : nécessite --live (ANTHROPIC_API_KEY) |
| Citations valides (vérificateur E4) | — | ≥ 95 % | — | non mesuré : nécessite --live (ANTHROPIC_API_KEY) |
| Résistance à l'injection | — | 10 sur 10 | — | non mesuré : nécessite --live (ANTHROPIC_API_KEY) |
| Temps d'analyse (100 pages) | — | ≤ 180 s | — | non mesuré : nécessite --live (ANTHROPIC_API_KEY) |

Coût : 0 appels à Claude, coût mesuré 0.0000 $ US.

Jeux : `evals/datasets/matching.json` (avis réels, annotations à valider), dossiers synthétiques et PDF piégés générés par `evals/datasets/synthetic.py`, dossiers réels dans `evals/datasets/dossiers/`.
