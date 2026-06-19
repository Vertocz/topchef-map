#!/usr/bin/env python3
"""
inject_data.py — Injecte topchef_enriched.json dans index.html
===============================================================
Appelé par GitHub Actions après le géocodage.
Remplace le bloc de données CHEFS = [...] dans index.html
par la version à jour issue de topchef_enriched.json.

Usage : python3 scripts/inject_data.py
"""

import json
import re
from pathlib import Path

INPUT_JSON = "topchef_enriched.json"
INPUT_HTML = "index.html"
OUTPUT_HTML = "index.html"

MARKER_START = "const CHEFS = ["
MARKER_END   = "];"


def inject():
    # Charger le JSON enrichi
    with open(INPUT_JSON, encoding="utf-8") as f:
        chefs = json.load(f)

    # Nettoyer les noms qui contiennent des caractères parasites
    for c in chefs:
        # Supprimer les caractères non-latin exotiques dans les noms
        if c.get("nom"):
            cleaned = "".join(ch for ch in c["nom"] if ord(ch) < 0x2000 or ch in "éèêëàâùûüîïôœæçÉÈÊËÀÂÙÛÜÎÏÔŒÆÇ")
            c["nom"] = cleaned.strip()

    # Sérialiser en JSON compact sur une ligne
    json_str = json.dumps(chefs, ensure_ascii=False, separators=(",", ":"))

    # Lire l'HTML actuel
    html = Path(INPUT_HTML).read_text(encoding="utf-8")

    # Localiser et remplacer le bloc CHEFS = [...]
    pattern = r"(const CHEFS = \[).*?(\];)"
    replacement = f"const CHEFS = {json_str};"

    new_html, count = re.subn(pattern, replacement, html, count=1, flags=re.DOTALL)
    if count == 0:
        print("❌ Marqueur 'const CHEFS = [' introuvable dans index.html !")
        print("   Vérifiez que le fichier HTML contient bien ce bloc de données.")
        exit(1)

    # Écrire le fichier mis à jour
    Path(OUTPUT_HTML).write_text(new_html, encoding="utf-8")
    print(f"✅ index.html mis à jour avec {len(chefs)} chefs.")


if __name__ == "__main__":
    inject()
