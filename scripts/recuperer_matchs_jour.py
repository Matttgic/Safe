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
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    leagues = []
    if isinstance(data, dict):
        for name, lid in data.items():
            leagues.append({"league_id": int(lid), "league_name": str(name)})
    elif isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                lid = it.get("league_id") or it.get("id")
                name = it.get("league_name") or it.get("name")
                if lid:
                    leagues.append({"league_id": int(lid), "league_name": name or f"Ligue {lid}"})
    return leagues

def main():
    ap = argparse.ArgumentParser(description="Récupère les fixtures du jour pour les ligues listées dans ligues.yaml")
    ap.add_argument("--ligues", required=False, default="ligues.yaml", help="Chemin du fichier des ligues (YAML)")
    ap.add_argument("--season", required=True, help="Saison (ex: 2025)")
    ap.add_argument("--date", required=True, help="Date au format YYYY-MM-DD")
    args = ap.parse_args()

    key = os.getenv("RAPIDAPI_KEY")
    host = os.getenv("RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com")
    if not key:
        print("Erreur: RAPIDAPI_KEY manquant", file=sys.stderr)
        sys.exit(1)

    leagues = load_leagues(args.ligues)
    if not leagues:
        print("Aucune ligue trouvée dans ligues.yaml", file=sys.stderr)
        sys.exit(1)

    date_str = args.date.strip()
    season = str(args.season).strip()

    out_path = f"donnees/matchs_jour_{date_str}.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    all_fixtures: List[Dict[str, Any]] = []

    for lig in leagues:
        league_id = lig["league_id"]
        league_name = lig["league_name"]
        params = {
            "date": date_str,
            "league": league_id,
            "season": season,
            "timezone": TZ_PARIS
        }
        data = api_get("/fixtures", params=params, key=key, host=host)
        fixtures = data.get("response", []) or []
        print(f"[INFO] {league_name} (ID {league_id}) — {len(fixtures)} match(s) le {date_str}")
        all_fixtures.extend(fixtures)
        time.sleep(0.2)

    result = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "timezone": TZ_PARIS,
        "season": season,
        "date": date_str,
        "count": len(all_fixtures),
        "fixtures": all_fixtures
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[OK] Écrit: {out_path} | Total fixtures: {len(all_fixtures)}")

if __name__ == "__main__":
    main()
