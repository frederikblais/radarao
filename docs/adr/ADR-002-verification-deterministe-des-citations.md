# ADR-002 — Extraction en sorties structurées, vérification des citations par du code

**Statut** : accepté · 2026-11-15

## Contexte
Les citations natives et les sorties structurées sont incompatibles dans une même requête (erreur 400).
Un LLM ne peut pas « s'auto-vérifier ».

## Décision
- Les travailleurs E2 rendent `citation` + `page` dans leur schéma JSON.
- Le vérificateur E4 (`worker/analysis/verifier.py`, sans LLM) cherche la citation normalisée sur la page (ratio ≥ 0,90), puis sur ±1 page.
  Introuvable : `quote_not_found` et confiance forcée à « faible ».
- Les PDF envoyés à Claude portent un tampon « [[D1 · p. 12]] » sur chaque page : le modèle lit le vrai numéro de page même
  quand il ne reçoit qu'une plage (sous-PDF). Le texte de référence d'E4 est extrait avant le tampon.
- L'assistant utilise les citations natives (une page = un bloc `document` titré « D1 · p. 12 »).

## Conséquences
- 100 % des champs affichés ont une page; tout champ non vérifié est signalé « À vérifier ».
- Les alias D1, D2… évitent d'exposer les identifiants internes au modèle et limitent les erreurs de recopie.
