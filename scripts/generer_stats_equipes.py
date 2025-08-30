#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, time, argparse
from datetime import datetime, timezone
from typing import Any, Dict, Optional
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

def get(d: Dict[str, Any], *ks, default=None):
    cur = d
    for k in ks:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def to_float(x) -> Optional[float]:
    if x is None: return None
    if isinstance(x, (int, float)): return float(x)
    if isinstance(x, str):
        x = x.replace("%", "").strip()
        try: return float(x)
        except: return None
    return None

def main():
    ap = argparse.ArgumentParser(description="Stats indispensables par équipe pour une saison.")
    ap.add_argument("--team_ids", required=True, help="donnees/team_ids.json")
    ap.add_argument("--out", required=True, help="fichier JSONL de sortie (ex: donnees/stats_equipes_2024.jsonl)")
    ap.add_argument("--season", required=True, help="saison (ex: 2024 ou 2025)")
    args = ap.parse_args()

    key = os.getenv("RAPIDAPI_KEY")
    host = os.getenv("RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com")
    if not key:
        print("Erreur: RAPIDAPI_KEY manquant", file=sys.stderr); sys.exit(1)

    with open(args.team_ids, "r", encoding="utf-8") as f:
        team_ids = json.load(f)

    leagues = team_ids.get("leagues", [])
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    total = 0

    with open(args.out, "w", encoding="utf-8") as out:
        for lig in leagues:
            league_id = lig.get("league_id")
            league_name = lig.get("league_name") or f"Ligue {league_id}"
            teams = lig.get("teams") or []
            if not league_id or not teams:
                continue
            print(f"[INFO] {league_name} ({league_id}) - {len(teams)} équipes → saison {args.season}")

            for t in teams:
                team_id = t.get("team_id") or t.get("id")
                team_name = t.get("name") or ""
                if not team_id:
                    continue

                data = api_get("/teams/statistics",
                               params={"league": league_id, "season": args.season, "team": team_id},
                               key=key, host=host)
                resp = data.get("response") or {}

                # indispensables
                played_total = get(resp, "fixtures","played","total")
                wins_total   = get(resp, "fixtures","wins","total")
                gf_avg = to_float(get(resp, "goals","for","average","total"))
                ga_avg = to_float(get(resp, "goals","against","average","total"))

                # calculs dérivés
                win_rate = (wins_total / played_total) if wins_total is not None and played_total else None
                goal_diff_avg = (gf_avg - ga_avg) if (gf_avg is not None and ga_avg is not None) else None

                # clean sheets / failed to score / over-under
                clean_sheets_total    = get(resp, "clean_sheet","total")
                failed_to_score_total = get(resp, "failed_to_score","total")
                ou_for_1_5_over       = get(resp, "goals","for","under_over","1.5","over")
                ou_against_1_5_over   = get(resp, "goals","against","under_over","1.5","over")

                row = {
                    "league_id": int(league_id),
                    "season": str(args.season),
                    "team_id": int(team_id),
                    "team_name": team_name,
                    "stats": {
                        "played_total": played_total,
                        "wins_total": wins_total,
                        "win_rate": win_rate,
                        "gf_avg": gf_avg,
                        "ga_avg": ga_avg,
                        "goal_diff_avg": goal_diff_avg,
                        "clean_sheets_total": clean_sheets_total,
                        "failed_to_score_total": failed_to_score_total,
                        "ou_for_1_5_over": ou_for_1_5_over,
                        "ou_against_1_5_over": ou_against_1_5_over
                    },
                    "source_timestamp": datetime.now(timezone.utc).astimezone().isoformat()
                }
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                total += 1
                time.sleep(0.2)

    print(f"[OK] Créé: {args.out} (lignes: {total})")

if __name__ == "__main__":
    main()
