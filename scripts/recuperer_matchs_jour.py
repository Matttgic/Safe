#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, argparse, time
from datetime import datetime, timezone
from typing import Any, Dict, List
import requests
import yaml

BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"
TZ_PARIS = "Europe/Paris"

def api_get(path: str, params: Dict[str, Any], key: str, host: str, max_retry: int = 3, pause: float = 1.5) -> Dict[str, Any]:
    headers = {
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": host or "api-football-v1.p.rapidapi.com",
        "Accept": "application/json",
    }
    url = f"{BASE_URL}{path}"
    for attempt in range(1, max_retry + 1):
        r = requests.get(url, headers=headers, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504) and attempt < max_retry:
            time.sleep(pause * attempt)
            continue
        raise RuntimeError(f"API error {r.status_code} for {url} params={params} body={r.text[:400]}")
    raise RuntimeError("Retries exhausted")

def load_leagues(yaml_path: str) -> List[Dict[str, Any]]:
    """
    Lit ton ligues.yaml EXACT tel que fourni (clé racine 'ligues' et items { nom, league_id })
    et renvoie une liste [{league_id, league_name}].
    """
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    out: List[Dict[str, Any]] = []
    items = data.get("ligues") if isinstance(data, dict) else None
    if not items or not isinstance(items, list):
        return out

    for entry in items:
        if not isinstance(entry, dict):
            continue
        lid = entry.get("league_id")
        nom = entry.get("nom") or entry.get("league_name") or f"Ligue {lid}"
        try:
            lid = int(lid)
        except Exception:
            continue
        out.append({"league_id": lid, "league_name": str(nom)})
    return out

def normalize_fixture(fx: Dict[str, Any], league_id: int, league_name: str, season: str, date_str: str) -> Dict[str, Any]:
    """Simplifie une fixture pour ne garder que l'essentiel."""
    fi = fx.get("fixture", {}) or {}
    te = fx.get("teams", {}) or {}
    return {
        "fixture_id": fi.get("id"),
        "league_id": league_id,
        "league_name": league_name,
        "season": season,
        "date": date_str,
        "kickoff": fi.get("date"),  # ISO datetime
        "status": (fi.get("status") or {}).get("short"),
        "home_team": {
            "id": (te.get("home") or {}).get("id"),
            "name": (te.get("home") or {}).get("name"),
        },
        "away_team": {
            "id": (te.get("away") or {}).get("id"),
            "name": (te.get("away") or {}).get("name"),
        },
    }

def main():
    ap = argparse.ArgumentParser(description="Récupère les fixtures du jour pour les ligues listées dans ligues.yaml")
    ap.add_argument("--ligues", required=False, default="ligues.yaml", help="Chemin du fichier des ligues (YAML)")
    ap.add_argument("--season", required=True, help="Saison (ex: 2025)")
    ap.add_argument("--date", required=True, help="Date au format YYYY-MM-DD")
    ap.add_argument("--out", required=False, default="donnees/matchs_du_jour.json",
                    help="Fichier de sortie unique (écrasé à chaque run)")
    args = ap.parse_args()

    key = os.getenv("RAPIDAPI_KEY")
    host = os.getenv("RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com")
    if not key:
        print("Erreur: RAPIDAPI_KEY manquant", file=sys.stderr)
        sys.exit(1)

    leagues = load_leagues(args.ligues)
    if not leagues:
        print("Aucune ligue trouvée dans ligues.yaml (clé 'ligues')", file=sys.stderr)
        sys.exit(1)

    date_str = args.date.strip()
    season = str(args.season).strip()

    out_path = args.out.strip()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    all_fixtures: List[Dict[str, Any]] = []

    for lig in leagues:
        league_id = lig["league_id"]
        league_name = lig["league_name"]
        params = {
            # ordre conforme à ta préférence/doc : date -> league -> season -> timezone
            "date": date_str,
            "league": league_id,
            "season": season,
            "timezone": "Europe/Paris",
        }
        data = api_get("/fixtures", params=params, key=key, host=host)
        fixtures = data.get("response", []) or []
        print(f"[INFO] {league_name} (ID {league_id}) — {len(fixtures)} match(s) le {date_str}")
        for fx in fixtures:
            all_fixtures.append(normalize_fixture(fx, league_id, league_name, season, date_str))
        time.sleep(0.2)  # douceur rate-limit

    result = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "timezone": "Europe/Paris",
        "season": season,
        "date": date_str,
        "count": len(all_fixtures),
        "fixtures": all_fixtures,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[OK] Écrit: {out_path} | Total fixtures: {len(all_fixtures)}")

if __name__ == "__main__":
    main()
