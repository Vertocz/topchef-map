#!/usr/bin/env python3
"""
enrich_etablissements.py
========================
Enrichit automatiquement les établissements dans topchef_enriched.json
en utilisant Gemini Flash (gratuit) + DuckDuckGo (gratuit, sans clé).

Workflow pour chaque chef :
  1. DuckDuckGo cherche "[Nom] chef restaurant 2026" → extrait les snippets
  2. Gemini Flash analyse les résultats et retourne un JSON structuré
  3. Le JSON enrichi est sauvegardé incrémentalement

Chaque entrée enrichie reçoit :
  - etablissement_actuel   : nom de l'établissement aujourd'hui
  - ville_actuelle         : ville actuelle (peut différer de la ville Top Chef)
  - _enrichissement_date   : date ISO de la dernière mise à jour
  - _enrichissement_conf   : haute | moyenne | basse
  - _enrichissement_source : URL de la source trouvée

Usage :
    pip install google-generativeai duckduckgo-search
    export GEMINI_API_KEY=...
    python3 enrich_etablissements.py
    python3 enrich_etablissements.py --limit 10       # Tester sur 10 chefs
    python3 enrich_etablissements.py --saison 14      # Une saison uniquement
    python3 enrich_etablissements.py --force          # Ré-enrichir même les déjà traités
    python3 enrich_etablissements.py --dry-run        # Aperçu sans appel API
    python3 enrich_etablissements.py --refresh-days 90

Dépendances : google-generativeai>=0.8, duckduckgo-search>=6
"""

import json
import time
import argparse
import sys
import re
import os
from datetime import datetime, timezone, timedelta

# ── Vérification des dépendances ───────────────────────────────────────────
try:
    import google.generativeai as genai
except ImportError:
    print("❌ Module manquant. Lancez : pip install google-generativeai")
    sys.exit(1)

try:
    from duckduckgo_search import DDGS
except ImportError:
    print("❌ Module manquant. Lancez : pip install duckduckgo-search")
    sys.exit(1)

# ── Configuration ──────────────────────────────────────────────────────────

INPUT_FILE  = "topchef_enriched.json"
OUTPUT_FILE = "topchef_enriched.json"
LOG_FILE    = "enrich_log.jsonl"

GEMINI_MODEL   = "gemini-1.5-flash"   # Gratuit : 1 500 req/jour, 1M tokens/min
DDG_MAX_RESULTS = 5                   # Snippets DuckDuckGo par chef
DELAY_SEC       = 2.0                 # Pause entre chefs (DDG est sensible au rate limiting)
DDG_DELAY_SEC   = 1.0                 # Pause entre les requêtes DDG

# Valeurs considérées comme "vagues" : simples fonctions, pas des établissements
FONCTIONS_VAGUES = {
    "Chef", "Sous-chef", "Second de cuisine", "Chef de partie",
    "Chef de cuisine", "Chef propriétaire", "Chef privé", "Chef à domicile",
    "Chef exécutif", "Chef exécutive", "Chef pâtissière", "Chef 1 étoile",
    "Amateur", "Apprenti", "Apprentie", "Commis", "Indépendant",
    "Étudiant", "Coach culinaire", "Restaurant gastronomique",
    "Restaurant bistronomique", "Restaurant 2 étoiles", "Abandon",
}

# Traduction des mois en français (indépendant de la locale système)
MOIS_FR = {
    1:"janvier",  2:"février",   3:"mars",      4:"avril",
    5:"mai",      6:"juin",      7:"juillet",   8:"août",
    9:"septembre",10:"octobre", 11:"novembre", 12:"décembre",
}

def month_label(dt: datetime) -> str:
    return f"{MOIS_FR[dt.month]} {dt.year}"

# ── Recherche DuckDuckGo ───────────────────────────────────────────────────

def search_web(chef: dict) -> list[dict]:
    """
    Lance 2 requêtes DDG et retourne une liste de résultats fusionnés.
    Chaque résultat : {"title": ..., "body": ..., "href": ...}
    """
    now  = datetime.now(timezone.utc)
    year = now.year
    nom  = chef["nom"]

    queries = [
        f"{nom} chef restaurant {year}",
        f"{nom} Top Chef restaurant actuel",
    ]

    all_results = []
    seen_urls   = set()

    with DDGS() as ddgs:
        for query in queries:
            try:
                results = list(ddgs.text(query, max_results=DDG_MAX_RESULTS))
                for r in results:
                    url = r.get("href", "")
                    if url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(r)
                time.sleep(DDG_DELAY_SEC)
            except Exception as e:
                print(f"    ⚠️  DDG erreur sur '{query}': {e}")

    return all_results[:DDG_MAX_RESULTS * 2]   # Max 10 résultats au total

def format_search_results(results: list[dict]) -> str:
    """Formate les résultats DDG en texte lisible pour Gemini."""
    if not results:
        return "Aucun résultat trouvé."
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r.get('title', '')}")
        lines.append(f"    {r.get('body', '')}")
        lines.append(f"    URL : {r.get('href', '')}")
    return "\n".join(lines)

# ── Prompt Gemini ──────────────────────────────────────────────────────────

def build_system_prompt() -> str:
    now   = datetime.now(timezone.utc)
    month = month_label(now)
    year  = now.year
    y1    = year - 1
    return f"""Tu es un assistant spécialisé dans la gastronomie française et l'émission Top Chef (M6).
Nous sommes en {month}.

Ta mission : à partir de résultats de recherche web fournis, identifier l'établissement
où travaille ACTUELLEMENT le chef demandé (en {year} ou {y1}), pas celui de l'époque de Top Chef.

RÈGLES :
- Base-toi UNIQUEMENT sur les résultats de recherche fournis, ne devine rien.
- Privilégie les sources récentes ({year}, {y1}).
- Si le chef a ouvert son propre restaurant, c'est la réponse prioritaire.
- Retourne UNIQUEMENT un objet JSON valide, sans texte autour, sans balises markdown.
- Si aucune info fiable n'est trouvée dans les résultats, retourne null.

FORMAT DE RÉPONSE (JSON pur, rien d'autre) :
{{
  "etablissement_actuel": "Nom du restaurant ou null",
  "ville_actuelle": "Ville ou null",
  "confidence": "haute|moyenne|basse",
  "source": "URL de la source utilisée ou null",
  "note": "Info complémentaire utile ou null"
}}"""

def build_user_prompt(chef: dict, search_results: str) -> str:
    now         = datetime.now(timezone.utc)
    year        = now.year
    saison_year = 2009 + chef["saison"]
    ancien_etab = chef.get("_etablissement_original") or chef.get("etablissement", "inconnu")

    return f"""Chef à identifier : {chef['nom']}
Saison Top Chef  : {chef['saison']} (~{saison_year})
Ville Top Chef   : {chef.get('ville', 'inconnue')}
Établissement à l'époque : {ancien_etab}

Résultats de recherche web (juin {year}) :
{search_results}

Retourne le JSON indiquant où travaille {chef['nom']} AUJOURD'HUI ({year})."""

# ── Appel Gemini ───────────────────────────────────────────────────────────

def call_gemini(model, chef: dict, search_results: list[dict]) -> dict:
    """Envoie le contexte de recherche à Gemini et retourne le JSON parsé."""
    formatted = format_search_results(search_results)
    prompt    = build_user_prompt(chef, formatted)

    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",   # Force la sortie JSON
                temperature=0.1,                          # Réponses stables et factuelles
            ),
        )
        raw = response.text.strip()

        # Nettoyer les éventuelles balises markdown résiduelles
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$",          "", raw, flags=re.MULTILINE)
        raw = raw.strip()

        return json.loads(raw)

    except json.JSONDecodeError:
        # Tentative d'extraction du premier objet JSON trouvé
        match = re.search(r'\{.*?\}', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return _empty_result(f"JSON non parsable : {raw[:150]}")

    except Exception as e:
        return _empty_result(str(e))

def _empty_result(note: str) -> dict:
    return {
        "etablissement_actuel": None,
        "ville_actuelle":       None,
        "confidence":           "basse",
        "source":               None,
        "note":                 note,
    }

# ── Journal JSONL ──────────────────────────────────────────────────────────

def log_result(chef: dict, result: dict, nb_sources: int) -> None:
    entry = {
        "timestamp":              datetime.now(timezone.utc).isoformat(),
        "saison":                 chef["saison"],
        "nom":                    chef["nom"],
        "ville_top_chef":         chef.get("ville"),
        "etablissement_top_chef": chef.get("_etablissement_original") or chef.get("etablissement"),
        "nb_sources_ddg":         nb_sources,
        **result,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# ── Sélection des chefs à traiter ─────────────────────────────────────────

def needs_enrichment(chef: dict, force: bool, refresh_days: int | None) -> bool:
    etab            = chef.get("etablissement", "").strip()
    etab_actuel     = chef.get("etablissement_actuel")
    enrichment_date = chef.get("_enrichissement_date")

    if force:
        return True

    if not enrichment_date:
        return etab in FONCTIONS_VAGUES or not etab_actuel

    if refresh_days is not None:
        try:
            last = datetime.fromisoformat(enrichment_date)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - last > timedelta(days=refresh_days)
        except ValueError:
            return True

    return False

# ── Enrichissement principal ───────────────────────────────────────────────

def enrich(
    input_path:   str,
    output_path:  str,
    limit:        int | None  = None,
    force:        bool        = False,
    saison:       int | None  = None,
    dry_run:      bool        = False,
    refresh_days: int | None  = None,
) -> None:

    with open(input_path, encoding="utf-8") as f:
        chefs = json.load(f)

    to_enrich = [
        (i, chef) for i, chef in enumerate(chefs)
        if (saison is None or chef.get("saison") == saison)
        and needs_enrichment(chef, force, refresh_days)
    ]
    if limit:
        to_enrich = to_enrich[:limit]

    print(f"📋 {len(to_enrich)} chef(s) à enrichir")

    if dry_run:
        print("\n🔍 Mode dry-run — aucun appel API :")
        for _, c in to_enrich:
            last = c.get("_enrichissement_date", "jamais")
            print(f"  S{c['saison']} — {c['nom']} ({c['ville']}) "
                  f"| actuel : {c.get('etablissement_actuel','—')} | MAJ : {last}")
        return

    if not to_enrich:
        print("✅ Rien à enrichir.")
        return

    # Initialiser Gemini
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("❌ Variable d'environnement GEMINI_API_KEY manquante.")
        sys.exit(1)
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name=GEMINI_MODEL,
        system_instruction=build_system_prompt(),
    )

    enriched_count = 0
    failed_count   = 0
    now_iso        = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for rank, (idx, chef) in enumerate(to_enrich, 1):
        print(f"\n[{rank}/{len(to_enrich)}] {chef['nom']} — S{chef['saison']} ({chef['ville']})")
        ancien = chef.get("_etablissement_original") or chef.get("etablissement", "—")
        print(f"  À l'époque : {ancien}")

        # Étape 1 — Recherche DuckDuckGo
        print("  🔍 Recherche DuckDuckGo…", end=" ", flush=True)
        search_results = search_web(chef)
        print(f"{len(search_results)} résultat(s)")

        # Étape 2 — Analyse Gemini
        print("  🤖 Analyse Gemini…", end=" ", flush=True)
        result = call_gemini(model, chef, search_results)

        etab_actuel = result.get("etablissement_actuel")
        ville_act   = result.get("ville_actuelle")
        confidence  = result.get("confidence", "?")

        print(f"OK ({confidence})")

        # Mettre à jour le JSON
        if "_etablissement_original" not in chefs[idx]:
            chefs[idx]["_etablissement_original"] = chef.get("etablissement")

        chefs[idx]["etablissement_actuel"]   = etab_actuel
        chefs[idx]["ville_actuelle"]         = ville_act
        chefs[idx]["_enrichissement_date"]   = now_iso
        chefs[idx]["_enrichissement_conf"]   = confidence
        chefs[idx]["_enrichissement_source"] = result.get("source")

        if etab_actuel:
            enriched_count += 1
            print(f"  ✅ {etab_actuel}" + (f", {ville_act}" if ville_act else ""))
            if result.get("note"):
                print(f"     💬 {result['note']}")
        else:
            failed_count += 1
            print(f"  ⚠️  Non trouvé — {result.get('note', '—')}")

        log_result(chef, result, len(search_results))

        # Sauvegarde incrémentale après chaque chef
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(chefs, f, ensure_ascii=False, indent=2)

        if rank < len(to_enrich):
            time.sleep(DELAY_SEC)

    print(f"\n{'='*52}")
    print(f"✅ Enrichis avec succès : {enriched_count}")
    print(f"⚠️  Non trouvés          : {failed_count}")
    print(f"📅 Date de mise à jour  : {now_iso}")
    print(f"📄 Journal              : {LOG_FILE}")
    print(f"💾 Fichier mis à jour   : {output_path}")

# ── CLI ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Enrichit les établissements actuels via Gemini Flash + DuckDuckGo (100%% gratuit)."
    )
    parser.add_argument("--input",        default=INPUT_FILE,  help="JSON source")
    parser.add_argument("--output",       default=OUTPUT_FILE, help="JSON de sortie")
    parser.add_argument("--limit",        type=int,            help="Nombre max de chefs à traiter")
    parser.add_argument("--saison",       type=int,            help="Traiter uniquement cette saison")
    parser.add_argument("--force",        action="store_true", help="Ré-enrichir même les déjà traités")
    parser.add_argument("--dry-run",      action="store_true", help="Aperçu sans appel API")
    parser.add_argument("--refresh-days", type=int, dest="refresh_days",
                        help="Re-traiter si la MAJ dépasse N jours")
    args = parser.parse_args()

    enrich(
        input_path=args.input,
        output_path=args.output,
        limit=args.limit,
        force=args.force,
        saison=args.saison,
        dry_run=args.dry_run,
        refresh_days=args.refresh_days,
    )
