#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, time, argparse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"

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
        raise RuntimeError(f"API error {r.status_code} for {url} params={params} body={r.text[:300]}")
    raise RuntimeError("Retries exhausted")

def extract_float(d: Dict[str, Any], path: List[str]) -> Optional[float]:
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    try:
        return float(cur) if cur is not None else None
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser(description="Créer un fichier de stats équipes pour une saison (sans merge).")
    ap.add_argument("--team_ids", required=True, help="Chemin du team_ids.json (liste ligues+équipes)")
    ap.add_argument("--out", required=True, help="Fichier de sortie JSONL (ex: donnees/stats_equipes_2024.jsonl)")
    ap.add_argument("--season", required=True, help="Saison (ex: 2024)")
    args = ap.parse_args()

    key = os.getenv("RAPIDAPI_KEY")
    host = os.getenv("RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com")
    if not key:
        print("Erreur: RAPIDAPI_KEY manquant", file=sys.stderr); sys.exit(1)

    # charge les équipes
    with open(args.team_ids, "r", encoding="utf-8") as f:
        team_ids = json.load(f)
    leagues = team_ids.get("leagues", [])

    # prépare le fichier (création/écrasement)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as out:
        total = 0
        for lig in leagues:
            league_id = lig.get("league_id")
            league_name = lig.get("league_name") or f"Ligue {league_id}"
            teams = lig.get("teams") or []
            if not league_id or not teams:
                continue
            print(f"[INFO] Ligue {league_name} (ID {league_id}) - {len(teams)} équipes → Saison {args.season}")

            for t in teams:
                team_id = t.get("team_id") or t.get("id")
                team_name = t.get("name") or ""
                if not team_id: 
                    continue

                data = api_get("/teams/statistics",
                               params={"league": league_id, "season": args.season, "team": team_id},
                               key=key, host=host)
                resp = data.get("response") or {}

                gf_avg = extract_float(resp, ["goals","for","average","total"])
                ga_avg = extract_float(resp, ["goals","against","average","total"])
                sot_avg = extract_float(resp, ["shots","on","average"])
                possession = extract_float(resp, ["ball","possession"])

                wins_total = None
                played_total = None
                try:
                    fixtures = resp.get("fixtures", {})
                    wins_total   = fixtures.get("wins",   {}).get("total")
                    played_total = fixtures.get("played", {}).get("total")
                except Exception:
                    pass

                row = {
                    "league_id": int(league_id),
                    "season": str(args.season),
                    "team_id": int(team_id),
                    "team_name": team_name,
                    "stats": {
                        "gf_avg": gf_avg,
                        "ga_avg": ga_avg,
                        "sot_avg": sot_avg,
                        "possession": possession,
                        "wins_total": wins_total,
                        "played_total": played_total
                    },
                    "source_timestamp": datetime.now(timezone.utc).astimezone().isoformat()
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                total += 1
                time.sleep(0.2)  # douceur rate limit

    print(f"[OK] Créé: {args.out} (lignes: {total})")

if __name__ == "__main__":
    main()
