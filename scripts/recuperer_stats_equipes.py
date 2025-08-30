#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, time, argparse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import requests

BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"

def charge_team_ids(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # attendu: {"generated_at":..., "season":"2025", "leagues":[{league_id, league_name, season, teams:[{team_id,name,...}], ...}]}
    if "leagues" not in data or not isinstance(data["leagues"], list):
        raise ValueError("Fichier team_ids.json invalide: clé 'leagues' manquante ou non-liste.")
    return data

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
            try:
                return r.json()
            except Exception as e:
                raise RuntimeError(f"Réponse JSON invalide pour {url}: {e}")
        if r.status_code in (429, 500, 502, 503, 504) and attempt < max_retry:
            time.sleep(pause * attempt)
            continue
        raise RuntimeError(f"API error {r.status_code} for {url} params={params} body={r.text[:400]}")
    raise RuntimeError("Épuisement des retries API.")

def extract_stat_safe(d: Dict[str, Any], path: List[str], default: Optional[float] = None) -> Optional[float]:
    """Accède en profondeur sans lever d'erreur, renvoie default si absent."""
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    # Convertit en float si possible
    try:
        if cur is None:
            return default
        return float(cur)
    except Exception:
        return default

def main():
    p = argparse.ArgumentParser(description="Récupère les statistiques d'équipes à partir d'un team_ids.json")
    p.add_argument("--entree", required=True, help="Chemin du team_ids.json (ex: donnees/team_ids.json)")
    p.add_argument("--sortie", required=True, help="Chemin du JSONL de sortie (ex: donnees/stats_equipes.jsonl)")
    p.add_argument("--saison", required=False, default="", help="Saison (ex: 2024/2025). Si vide, lue depuis team_ids.json.")
    args = p.parse_args()

    rapid_key = os.getenv("RAPIDAPI_KEY")
    rapid_host = os.getenv("RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com")
    if not rapid_key:
        print("Erreur: RAPIDAPI_KEY manquant (secret GitHub).", file=sys.stderr)
        sys.exit(1)

    team_ids = charge_team_ids(args.entree)

    # Saison prioritaire : argument CLI, sinon prise depuis le fichier d'entrée
    season_cli = args.saison.strip()
    season_from_file = str(team_ids.get("season", "")).strip()
    season = season_cli or season_from_file
    if not season:
        print("Erreur: saison non fournie et absente de team_ids.json.", file=sys.stderr)
        sys.exit(1)

    # Ouvre la sortie JSONL
    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    out = open(args.sortie, "w", encoding="utf-8")

    total_leagues = 0
    total_teams = 0

    for lig in team_ids["leagues"]:
        league_id = lig.get("league_id")
        league_name = lig.get("league_name") or lig.get("league") or f"Ligue {league_id}"
        if not league_id:
            continue
        teams = lig.get("teams", []) or []
        total_leagues += 1
        print(f"[INFO] Ligue {league_name} (ID {league_id}) - {len(teams)} équipes")

        for t in teams:
            team_id = t.get("team_id") or t.get("id")
            team_name = t.get("name") or ""
            if not team_id:
                continue

            params = {"league": league_id, "season": season, "team": team_id}
            data = api_get("/teams/statistics", params=params, key=rapid_key, host=rapid_host)

            # La réponse API-Football pour /teams/statistics est un objet avec les stats dans "response" (souvent directement au premier niveau).
            resp = data.get("response") or {}
            # Champs essentiels (avec chemins prudents, certaines clés peuvent varier selon la ligue/saison)
            gf_avg = extract_stat_safe(resp, ["goals", "for", "average", "total"], None)
            ga_avg = extract_stat_safe(resp, ["goals", "against", "average", "total"], None)
            sot_avg = extract_stat_safe(resp, ["shots", "on", "average"], None)
            possession = extract_stat_safe(resp, ["ball", "possession"], None)  # certaines ligues n'ont pas ce champ

            wins_total = None
            played_total = None
            # Fallback sécurisé si la structure varie
            try:
                fixtures = resp.get("fixtures", {})
                wins_total = fixtures.get("wins", {}).get("total")
                played_total = fixtures.get("played", {}).get("total")
            except Exception:
                pass

            record = {
                "league_id": league_id,
                "season": season,
                "team_id": team_id,
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
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            total_teams += 1
            # petite pause pour rester soft sur le rate limit
            time.sleep(0.25)

    out.close()
    print(f"[OK] Écrit: {args.sortie} | Ligues: {total_leagues} | Équipes: {total_teams}")

if __name__ == "__main__":
    main()
