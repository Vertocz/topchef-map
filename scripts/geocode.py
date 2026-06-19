#!/usr/bin/env python3
"""
geocode.py — Script de géocodage automatique pour Top Chef Map
=============================================================
Transforme topchef.json (brut) → topchef_enriched.json (avec lat/lon)
en utilisant l'API gratuite Nominatim (OpenStreetMap).

Usage :
    python3 geocode.py
    python3 geocode.py --input data/topchef.json --output data/topchef_enriched.json
    python3 geocode.py --force   # Recalcule même les coords déjà connues

Dépendances : requests (pip install requests)
"""

import json
import time
import argparse
import sys
from pathlib import Path
try:
    import requests
except ImportError:
    print("❌ Module 'requests' manquant. Lancez : pip install requests")
    sys.exit(1)

# ── Configuration ──────────────────────────────────────────────────────────
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT    = "TopChefMap/1.0 (projet éducatif, contact: votre@email.com)"
DELAY_SEC     = 1.2   # Respecte la limite Nominatim : max 1 req/s

# Table d'alias : ville dans le JSON → requête Nominatim optimisée
# Ajoutez ici toute nouvelle ville dont le résultat est imprécis.
ALIASES = {
    "Belgique":      "Belgique",
    "Lisbonne":      "Lisbon, Portugal",
    "Pékin":         "Beijing, China",
    "Copenhague":    "Copenhagen, Denmark",
    "Munich":        "Munich, Germany",
    "Luxembourg":    "Luxembourg City, Luxembourg",
    "Tokyo":         "Tokyo, Japan",
    "Marbehan":      "Marbehan, Belgium",
    "Xhendremael":   "Xhendremael, Belgium",
    "Namur":         "Namur, Belgium",
    "Mons":          "Mons, Belgium",
    "Bruxelles":     "Brussels, Belgium",
    "Auvergne":      "Auvergne, France",
    "Bourecq":       "Bourecq, France",
}

# ── Géocodage ──────────────────────────────────────────────────────────────
def geocode_city(city: str, session: requests.Session) -> tuple[float, float] | tuple[None, None]:
    """Retourne (lat, lon) ou (None, None) si introuvable."""
    query = ALIASES.get(city, f"{city}, France")
    try:
        resp = session.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print(f"  ⚠️  Erreur pour '{city}': {e}")
    return None, None


def enrich(input_path: str, output_path: str, force: bool = False) -> None:
    # Charger les données brutes
    with open(input_path, encoding="utf-8") as f:
        chefs = json.load(f)

    # Charger le cache existant si disponible (évite de re-géocoder)
    cache: dict[str, dict] = {}
    out_file = Path(output_path)
    if out_file.exists() and not force:
        with open(out_file, encoding="utf-8") as f:
            existing = json.load(f)
        for c in existing:
            if c.get("lat") and c.get("ville"):
                cache[c["ville"]] = {"lat": c["lat"], "lon": c["lon"]}
        print(f"📦 Cache chargé : {len(cache)} ville(s) connue(s)")

    # Identifier les villes à géocoder
    all_cities  = list({c["ville"] for c in chefs if c.get("ville")})
    todo_cities = [v for v in all_cities if v not in cache or force]
    print(f"🌍 {len(all_cities)} villes uniques | {len(todo_cities)} à géocoder")

    if todo_cities:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

        for city in todo_cities:
            lat, lon = geocode_city(city, session)
            cache[city] = {"lat": lat, "lon": lon}
            status = f"✓ {lat:.4f}, {lon:.4f}" if lat else "✗ Introuvable"
            print(f"  {city}: {status}")
            time.sleep(DELAY_SEC)

    # Enrichir les chefs
    enriched = []
    missing  = []
    for chef in chefs:
        c = dict(chef)
        coords = cache.get(chef.get("ville", ""), {})
        c["lat"] = coords.get("lat")
        c["lon"] = coords.get("lon")
        if not c["lat"]:
            missing.append(chef["ville"])
        enriched.append(c)

    # Sauvegarder
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Fichier enrichi sauvegardé : {output_path}")
    print(f"   {len(enriched)} chefs | {len(missing)} sans coordonnées")
    if missing:
        print(f"   Villes manquantes : {set(missing)}")
        print("   👉 Ajoutez-les dans la table ALIASES du script ou corrigez le JSON source.")


# ── CLI ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Géocode topchef.json via Nominatim (OSM).")
    parser.add_argument("--input",  default="topchef.json",          help="JSON source (brut)")
    parser.add_argument("--output", default="topchef_enriched.json", help="JSON de sortie (enrichi)")
    parser.add_argument("--force",  action="store_true",             help="Recalcule toutes les coords")
    args = parser.parse_args()

    enrich(args.input, args.output, args.force)
