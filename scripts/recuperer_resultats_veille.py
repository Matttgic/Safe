#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, argparse, time, csv
from datetime import datetime, timezone
from typing import Any, Dict, List
import requests
import yaml

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
        raise RuntimeError(f"API error {r.status_code} for {url} params={params}")
    raise RuntimeError("Retries exhausted")

def load_leagues(yaml_path: str) -> List[Dict[str, Any]]:
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    out = []
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

def update_historique_with_results(historique_path: str, results_data: Dict[str, Dict], date_str: str):
    """Met à jour le fichier historique avec les vrais résultats."""
    if not os.path.exists(historique_path):
        print(f"[WARN] Fichier historique non trouvé: {historique_path}")
        return
    
    # Lire historique existant
    rows = []
    with open(historique_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    
    # Ajouter colonnes résultats si manquantes
    if fieldnames and 'Resultat_Over15' not in fieldnames:
        fieldnames = list(fieldnames) + ['Resultat_Over15', 'Resultat_Result']
    
    updated_count = 0
    for row in rows:
        if row['Date'] == date_str:
            match_key = row['Match']
            
            # Chercher dans results_data avec différentes clés possibles
            match_result = None
            for key in results_data:
                if normalize_match_name(key) == normalize_match_name(match_key):
                    match_result = results_data[key]
                    break
            
            if match_result:
                # Résultat Over 1.5
                if row['Decision_Over15'] != 'Éviter' and not row.get('Resultat_Over15'):
                    row['Resultat_Over15'] = match_result['over15']
                    updated_count += 1
                
                # Résultat pari équipe
                if row['Decision_Result'] != 'Éviter' and not row.get('Resultat_Result'):
                    decision = row['Decision_Result']
                    if 'A ou Nul' in decision:
                        row['Resultat_Result'] = match_result['home_or_draw']
                    elif 'B ou Nul' in decision:
                        row['Resultat_Result'] = match_result['away_or_draw']
                    updated_count += 1
            else:
                # Initialiser colonnes vides si pas de résultat trouvé
                if 'Resultat_Over15' not in row:
                    row['Resultat_Over15'] = ''
                if 'Resultat_Result' not in row:
                    row['Resultat_Result'] = ''
    
    # Réécrire fichier
    if fieldnames:
        with open(historique_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f"[OK] Historique mis à jour: {updated_count} résultats ajoutés")

def normalize_match_name(match_name: str) -> str:
    """Normalise les noms d'équipes pour comparaison."""
    return match_name.lower().replace(" vs ", " v ").replace("-", " ").strip()

def main():
    ap = argparse.ArgumentParser(description="Récupère les résultats de la veille et met à jour l'historique")
    ap.add_argument("--ligues", required=False, default="ligues.yaml")
    ap.add_argument("--season", required=True)
    ap.add_argument("--date", required=True, help="Date des matchs (YYYY-MM-DD)")
    ap.add_argument("--historique", required=True, help="Fichier historique à mettre à jour")
    args = ap.parse_args()

    key = os.getenv("RAPIDAPI_KEY")
    host = os.getenv("RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com")
    if not key:
        print("Erreur: RAPIDAPI_KEY manquant", file=sys.stderr)
        sys.exit(1)

    leagues = load_leagues(args.ligues)
    if not leagues:
        print("Aucune ligue trouvée", file=sys.stderr)
        sys.exit(1)

    date_str = args.date.strip()
    season = str(args.season).strip()
    
    # Dictionnaire pour stocker tous les résultats
    results_data = {}

    print(f"[INFO] Récupération des résultats pour le {date_str}")
    
    for lig in leagues:
        league_id = lig["league_id"]
        league_name = lig["league_name"]
        
        # Récupérer matchs terminés de cette date/ligue
        params = {
            "date": date_str,
            "league": league_id,
            "season": season,
            "timezone": "Europe/Paris",
        }
        
        try:
            data = api_get("/fixtures", params=params, key=key, host=host)
            fixtures = data.get("response", []) or []
            
            finished_matches = 0
            for fx in fixtures:
                fixture_info = fx.get("fixture", {})
                status = (fixture_info.get("status") or {}).get("short")
                
                # Seuls les matchs terminés (FT = Full Time)
                if status == "FT":
                    teams = fx.get("teams", {})
                    goals = fx.get("goals", {})
                    
                    home_team = (teams.get("home") or {}).get("name", "")
                    away_team = (teams.get("away") or {}).get("name", "")
                    home_goals = goals.get("home") or 0
                    away_goals = goals.get("away") or 0
                    
                    if home_team and away_team:
                        match_key = f"{home_team} vs {away_team}"
                        total_goals = home_goals + away_goals
                        
                        results_data[match_key] = {
                            'over15': 'WIN' if total_goals > 1 else 'LOSS',
                            'home_or_draw': 'WIN' if home_goals >= away_goals else 'LOSS',
                            'away_or_draw': 'WIN' if away_goals >= home_goals else 'LOSS'
                        }
                        finished_matches += 1
            
            print(f"[INFO] {league_name}: {finished_matches} matchs terminés")
            time.sleep(0.2)  # Rate limit
            
        except Exception as e:
            print(f"[WARN] Erreur pour {league_name}: {e}")
    
    print(f"[INFO] Total résultats récupérés: {len(results_data)}")
    
    # Mettre à jour l'historique
    update_historique_with_results(args.historique, results_data, date_str)

if __name__ == "__main__":
    main() 
