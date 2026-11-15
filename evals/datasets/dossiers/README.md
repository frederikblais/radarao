# Dossiers réels annotés (section 11.1)

Déposer ici 15 à 20 dossiers réels, un répertoire par dossier :

```
<nom>/
  D1-<fichier>.pdf        # alias D1, D2… dans l'ordre (addenda en dernier)
  D2-addenda-1.pdf
  expected.json
```

Format de `expected.json` :

```json
{
  "champs": {
    "date_limite_depot": {"valeur": "2026-11-20T11:00:00-05:00", "document": "D2", "page": 1},
    "garantie_soumission": {"valeur": "10 %", "document": "D1", "page": 12}
  },
  "documents": ["bordereau de prix", "déclaration lobbyisme"]
}
```

Les PDF achetés sur le SEAO ne doivent pas être publiés si les conditions d'utilisation l'interdisent :
ce répertoire peut rester privé (voir `.gitignore`).
