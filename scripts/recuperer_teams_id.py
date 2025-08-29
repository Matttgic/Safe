#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, json, yaml, argparse
from typing import Dict, Any, List, Tuple
import requests
from datetime import datetime, timezone

BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"

def lire_ligues_yaml(chemin_yaml: str) -> List[Dict[str, Any]]:
    with open(chemin_yaml, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "ligues" not in data or not isinstance(data["ligues"], list):
        raise ValueError("Fichier ligues.yaml invalide: clé 'ligues' manquante ou non-liste.")
    # On accepte les objets avec au moins 'league_id' (et idéalement 'nom')
    for lig in data["ligues"]:
        if "league_id" not in lig:
            raise ValueError("Une entrée de 'ligues' ne contient pas 'league_id'.")
    return data["ligues"]

def requete_api(path: str, params: Dict[str, Any], key: str, host: str, max_retry: int = 3, pause: float = 1.5) -> Dict[str, Any]:
    headers = {
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": host or "api-football-v1.p.rapidapi.com",
        "Accept": "application/json",
    }
    url = f"{BASE_URL}{path}"
    for tentative in range(1, max_retry + 1):
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            try:
                return resp.json()
            except Exception as e:
                raise RuntimeError(f"JSON invalide pour {url}: {e}")
        # 429/5xx -> retry
        if resp.status_code in (429, 500, 502, 503, 504) and tentative < max_retry:
            time.sleep(pause * tentative)
            continue
        # sinon: erreur
        raise RuntimeError(f"Appel API échoué ({resp.status_code}) pour {url} params={params} body={resp.text[:500]}")
    raise RuntimeError("Épuisement des retries API.")

def lister_equipes_ligue(league_id: int, saison: str, key: str, host: str) -> List[Dict[str, Any]]:
    """GET /teams?league={id}&season={saison} avec pagination si nécessaire."""
    equipes: List[Dict[str, Any]] = []
    page = 1
    while True:
        data = requete_api(
            "/teams",
            {"league": league_id, "season": saison, "page": page},
            key=key,
            host=host,
        )
        # Structure API-Football typique: { "response": [...], "results": N, "paging": {"current":1,"total":1}}
        resp = data.get("response", [])
        for item in resp:
            team = item.get("team", {}) or {}
            t_id = team.get("id")
            t_name = team.get("name")
            if t_id is not None and t_name:
                equipes.append({"team_id": t_id, "name": t_name})
        paging = data.get("paging", {})
        cur, total = paging.get("current", 1), paging.get("total", 1)
        if cur >= total:
            break
        page += 1
        time.sleep(0.4)  # douceur pour le rate limit
    return equipes

def main():
    parser = argparse.ArgumentParser(description="Récupère les Team IDs pour chaque ligue définie dans ligues.yaml.")
    parser.add_argument("--entree", required=True, help="Chemin du fichier ligues.yaml")
    parser.add_argument("--sortie", required=True, help="Chemin du fichier JSON de sortie (ex: donnees/team_ids.json)")
    parser.add_argument("--saison", required=True, help="Saison (ex: 2025)")
    args = parser.parse_args()

    rapid_key = os.getenv("RAPIDAPI_KEY")
    rapid_host = os.getenv("RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com")
    if not rapid_key:
        print("Erreur: variable d'environnement RAPIDAPI_KEY absente.", file=sys.stderr)
        sys.exit(1)

    ligues = lire_ligues_yaml(args.entree)

    resultat = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "season": args.saison,
        "leagues": []
    }

    for lig in ligues:
        league_id = int(lig["league_id"])
        nom = lig.get("nom") or lig.get("name") or f"Ligue {league_id}"
        print(f"[INFO] Ligue {nom} (ID {league_id}) - récupération des équipes…")
        equipes = lister_equipes_ligue(league_id, args.saison, key=rapid_key, host=rapid_host)
        resultat["leagues"].append({
            "league_id": league_id,
            "league_name": nom,
            "season": args.saison,
            "teams": equipes
        })
        print(f"[INFO] → {len(equipes)} équipes")

    # écrire la sortie
    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False, indent=2)
    print(f"[OK] Écrit: {args.sortie}")

if __name__ == "__main__":
    main()
