# 🍳 Top Chef — Carte Interactive Mondiale

Web App open-source affichant tous les candidats de Top Chef (Saisons 1–17) sur une carte interactive. **100 % gratuit, zéro carte de crédit requise.**

---

## ⚡ Mise en ligne en 6 étapes

### Étape 1 — Obtenir une clé Gemini (2 min)

1. Aller sur [aistudio.google.com](https://aistudio.google.com)
2. Se connecter avec un compte Google
3. Cliquer **Get API key → Create API key**
4. Copier la clé (format `AIza...`)

> Quota gratuit : **1 500 requêtes/jour**, largement suffisant pour ce projet.

---

### Étape 2 — Créer le dépôt GitHub (2 min)

```bash
# Dans le dossier du projet
git init
git add .
git commit -m "🍳 Initial commit — Top Chef Map"
```

Puis sur [github.com/new](https://github.com/new) :
- Nom : `topchef-map`
- Visibilité : **Public** (requis pour GitHub Pages gratuit)
- Ne pas initialiser avec README (vous en avez déjà un)

```bash
git remote add origin https://github.com/VOTRE-USER/topchef-map.git
git branch -M main
git push -u origin main
```

---

### Étape 3 — Configurer le secret API (1 min)

Dans votre dépôt GitHub :
**Settings → Secrets and variables → Actions → New repository secret**

| Nom | Valeur |
|-----|--------|
| `GEMINI_API_KEY` | `AIza...` (votre clé Gemini) |

---

### Étape 4 — Enrichissement initial (20-30 min)

Le premier enrichissement des 204 chefs se fait **en local** (plus rapide, économise les requêtes GitHub Actions) :

```bash
# Installer les dépendances
pip install requests google-generativeai duckduckgo-search

# Exporter la clé
export GEMINI_API_KEY=AIza...     # Mac/Linux
# ou sur Windows :
# set GEMINI_API_KEY=AIza...

# Tester sur 3 chefs d'abord
python3 scripts/enrich_etablissements.py --limit 3

# Si tout va bien, lancer l'enrichissement complet
python3 scripts/enrich_etablissements.py

# Injecter dans la carte
python3 scripts/inject_data.py

# Pousser le résultat
git add topchef_enriched.json index.html enrich_log.jsonl
git commit -m "✅ Enrichissement initial des établissements"
git push
```

> En cas d'interruption, relancez simplement la commande : les chefs déjà traités sont ignorés grâce au cache `_enrichissement_date`.

---

### Étape 5 — Activer GitHub Pages (1 min)

Dans votre dépôt GitHub :
**Settings → Pages**
- Source : `Deploy from a branch`
- Branch : `gh-pages` / `/ (root)`
- Cliquer **Save**

Après le premier déploiement (2-3 minutes), votre carte est accessible sur :
```
https://VOTRE-USER.github.io/topchef-map/
```

---

### Étape 6 — Vérifier que tout fonctionne

**Actions → "Mise à jour carte Top Chef"** — le workflow doit apparaître en vert.

Pour tester un déclenchement manuel :
**Actions → Run workflow → Run workflow**

---

## 📁 Structure du projet

```
topchef-map/
├── index.html                    # La carte (application complète, un seul fichier)
├── topchef.json                  # ✏️  Source de vérité — seul fichier à éditer
├── topchef_enriched.json         # Généré automatiquement (GPS + établissements)
├── enrich_log.jsonl              # Journal des enrichissements
├── scripts/
│   ├── geocode.py                # Géocodage GPS via Nominatim (OSM) — gratuit
│   ├── enrich_etablissements.py  # Enrichissement via Gemini Flash + DuckDuckGo — gratuit
│   └── inject_data.py            # Injection du JSON dans index.html
└── .github/
    └── workflows/
        └── update-map.yml        # Pipeline CI/CD automatique
```

---

## ➕ Ajouter un candidat

Éditer uniquement `topchef.json` :

```json
{
  "saison": 18,
  "nom": "Prénom Nom",
  "age": 27,
  "ville": "Bordeaux",
  "etablissement": "Chef",
  "resultat": "Éliminé",
  "date_elimination": "2027-03-15"
}
```

Puis pousser :

```bash
git add topchef.json
git commit -m "Ajout S18 — Prénom Nom"
git push
# → GitHub Actions géocode + enrichit + déploie automatiquement
```

---

## 🔄 Rafraîchissement automatique

Le workflow tourne automatiquement **tous les trimestres** (1er janvier, avril, juillet, octobre) pour mettre à jour les établissements actuels des chefs. Seules les entrées de plus de 90 jours sont retraitées.

Pour forcer un rafraîchissement manuel :
**Actions → Run workflow** → saisir un nombre de jours dans le champ `refresh_days`

---

## 🛠️ Stack technique (100 % gratuit)

| Composant | Technologie | Coût |
|-----------|-------------|------|
| Carte | Leaflet.js | Gratuit |
| Tuiles | CartoDB Positron | Gratuit |
| Clustering | Leaflet.markercluster | Gratuit |
| Géocodage GPS | Nominatim (OSM) | Gratuit |
| Recherche web | DuckDuckGo Search | Gratuit |
| IA d'analyse | Gemini 1.5 Flash | Gratuit (1 500 req/jour) |
| CI/CD | GitHub Actions | Gratuit (2 000 min/mois) |
| Hébergement | GitHub Pages | Gratuit |
