#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, yaml, argparse
import requests
from datetime import datetime, timezone

def lire_ligues_yaml(chemin_yaml: str):
    with open(chemin_yaml, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["ligues"]

def get_teams_for_league(league_id: int, season: str, api_key: str) -> list:
    """Reproduction exacte de votre curl qui marche"""
    url = f"https://api-football-v1.p.rapidapi.com/v3/teams"
    
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }
    
    params = {
        "league": league_id,
        "season": season
    }
    
    print(f"[INFO] GET {url}?league={league_id}&season={season}")
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        print(f"[DEBUG] Status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"[ERROR] {response.status_code}: {response.text[:200]}")
            return []
        
        data = response.json()
        
        # Debug info
        results = data.get("results", 0)
        errors = data.get("errors", [])
        
        if errors:
            print(f"[WARN] API Errors: {errors}")
        
        print(f"[DEBUG] Results: {results}")
        
        # Extraire les équipes
        teams = []
        for item in data.get("response", []):
            team = item.get("team", {})
            if team.get("id") and team.get("name"):
                teams.append({
                    "team_id": team["id"],
                    "name": team["name"],
                    "code": team.get("code", ""),
                    "country": team.get("country", ""),
                    "founded": team.get("founded"),
                    "logo": team.get("logo", "")
                })
        
        return teams
        
    except Exception as e:
        print(f"[ERROR] Exception: {e}")
        return []

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--entree", required=True)
    parser.add_argument("--sortie", required=True)
    parser.add_argument("--saison", required=True)
    args = parser.parse_args()

    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        print("❌ RAPIDAPI_KEY manquante")
        sys.exit(1)

    print(f"🔑 API Key: {api_key[:10]}...")
    print(f"📅 Saison: {args.saison}")

    # Charger les ligues
    ligues = lire_ligues_yaml(args.entree)
    print(f"📋 {len(ligues)} ligues à traiter")

    # Résultat final
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": args.saison,
        "leagues": []
    }

    # Traiter chaque ligue
    total_teams = 0
    for i, ligue in enumerate(ligues, 1):
        league_id = ligue["league_id"]
        nom = ligue.get("nom", f"League {league_id}")
        
        print(f"\n[{i}/{len(ligues)}] 🏆 {nom} (ID: {league_id})")
        print("-" * 40)
        
        teams = get_teams_for_league(league_id, args.saison, api_key)
        
        result["leagues"].append({
            "league_id": league_id,
            "league_name": nom,
            "season": args.saison,
            "teams_count": len(teams),
            "teams": teams
        })
        
        total_teams += len(teams)
        print(f"✅ {len(teams)} équipes récupérées")
        
        # Exemples d'équipes
        if teams:
            for j, team in enumerate(teams[:3]):
                print(f"   {j+1}. {team['name']} (ID: {team['team_id']})")
            if len(teams) > 3:
                print(f"   ... et {len(teams) - 3} autres")

    print(f"\n📊 TOTAL: {total_teams} équipes dans {len(ligues)} ligues")

    # Sauvegarder
    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"💾 Sauvegardé: {args.sortie}")

if __name__ == "__main__":
    main()
