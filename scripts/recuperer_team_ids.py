#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, json, yaml, argparse
from typing import Dict, Any, List
import requests
from datetime import datetime, timezone

BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"

def lire_ligues_yaml(chemin_yaml: str) -> List[Dict[str, Any]]:
    with open(chemin_yaml, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not data or "ligues" not in data or not isinstance(data["ligues"], list):
        raise ValueError("Fichier ligues.yaml invalide: clé 'ligues' manquante ou non-liste.")
    
    for lig in data["ligues"]:
        if "league_id" not in lig:
            raise ValueError("Une entrée de 'ligues' ne contient pas 'league_id'.")
    return data["ligues"]

def requete_api(path: str, params: Dict[str, Any], key: str, host: str) -> Dict[str, Any]:
    """Requête API simplifiée et robuste"""
    headers = {
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": host,
        "Accept": "application/json",
    }
    url = f"{BASE_URL}{path}"
    
    print(f"[DEBUG] Requête: {url} avec params: {params}")
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        print(f"[DEBUG] Status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"[ERROR] HTTP {response.status_code}: {response.text[:200]}")
            return {"response": [], "results": 0}
        
        data = response.json()
        
        # Vérifier les erreurs API
        if "errors" in data and data["errors"]:
            print(f"[WARN] Erreurs API: {data['errors']}")
        
        results = data.get("results", 0)
        print(f"[DEBUG] Résultats trouvés: {results}")
        
        return data
        
    except requests.exceptions.Timeout:
        print(f"[ERROR] Timeout pour {url}")
        return {"response": [], "results": 0}
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Erreur réseau: {e}")
        return {"response": [], "results": 0}
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON invalide: {e}")
        return {"response": [], "results": 0}

def lister_equipes_ligue(league_id: int, saison: str, key: str, host: str) -> List[Dict[str, Any]]:
    """Récupère toutes les équipes d'une ligue pour une saison donnée"""
    equipes = []
    page = 1
    
    while True:
        print(f"[INFO] Page {page} pour ligue {league_id}")
        
        data = requete_api(
            "/teams",
            {"league": league_id, "season": saison, "page": page},
            key=key,
            host=host,
        )
        
        response_teams = data.get("response", [])
        
        # Si pas de résultats sur la première page, on arrête
        if not response_teams and page == 1:
            print(f"[WARN] Aucune équipe trouvée pour ligue {league_id} saison {saison}")
            break
        
        # Traiter les équipes de cette page
        for item in response_teams:
            team_data = item.get("team", {})
            if team_data and "id" in team_data and "name" in team_data:
                equipes.append({
                    "team_id": team_data["id"],
                    "name": team_data["name"],
                    "code": team_data.get("code", ""),
                    "country": team_data.get("country", ""),
                    "founded": team_data.get("founded"),
                    "logo": team_data.get("logo", "")
                })
        
        # Vérifier s'il y a d'autres pages
        paging = data.get("paging", {})
        current_page = paging.get("current", 1)
        total_pages = paging.get("total", 1)
        
        print(f"[DEBUG] Page {current_page}/{total_pages}")
        
        if current_page >= total_pages:
            break
        
        page += 1
        time.sleep(0.5)  # Pause entre les requêtes
    
    return equipes

def main():
    parser = argparse.ArgumentParser(description="Récupère les Team IDs pour chaque ligue définie dans ligues.yaml.")
    parser.add_argument("--entree", required=True, help="Chemin du fichier ligues.yaml")
    parser.add_argument("--sortie", required=True, help="Chemin du fichier JSON de sortie")
    parser.add_argument("--saison", required=True, help="Saison (ex: 2025)")
    args = parser.parse_args()

    # Variables d'environnement
    rapid_key = os.getenv("RAPIDAPI_KEY")
    rapid_host = os.getenv("RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com")
    
    if not rapid_key:
        print("❌ Erreur: variable d'environnement RAPIDAPI_KEY absente.", file=sys.stderr)
        sys.exit(1)

    print(f"🔑 API Key: {rapid_key[:10]}...")
    print(f"🌐 API Host: {rapid_host}")
    print(f"📅 Saison: {args.saison}")

    # Charger les ligues
    try:
        ligues = lire_ligues_yaml(args.entree)
        print(f"📋 {len(ligues)} ligues chargées depuis {args.entree}")
    except Exception as e:
        print(f"❌ Erreur lecture {args.entree}: {e}", file=sys.stderr)
        sys.exit(1)

    # Structure de sortie
    resultat = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "season": args.saison,
        "total_leagues": len(ligues),
        "leagues": []
    }

    # Traitement de chaque ligue
    for i, ligue in enumerate(ligues, 1):
        league_id = int(ligue["league_id"])
        nom = ligue.get("nom", f"Ligue {league_id}")
        
        print(f"\n[{i}/{len(ligues)}] 🏆 {nom} (ID: {league_id})")
        print("-" * 50)
        
        try:
            equipes = lister_equipes_ligue(league_id, args.saison, rapid_key, rapid_host)
            
            resultat["leagues"].append({
                "league_id": league_id,
                "league_name": nom,
                "season": args.saison,
                "teams_count": len(equipes),
                "teams": equipes
            })
            
            print(f"✅ {len(equipes)} équipes récupérées pour {nom}")
            
            # Afficher quelques équipes pour vérification
            if equipes:
                print("📝 Exemples d'équipes:")
                for team in equipes[:3]:
                    print(f"   - {team['name']} (ID: {team['team_id']})")
                if len(equipes) > 3:
                    print(f"   ... et {len(equipes) - 3} autres")
            
        except Exception as e:
            print(f"❌ Erreur pour {nom}: {e}")
            resultat["leagues"].append({
                "league_id": league_id,
                "league_name": nom,
                "season": args.saison,
                "teams_count": 0,
                "teams": [],
                "error": str(e)
            })

    # Statistiques finales
    total_equipes = sum(league["teams_count"] for league in resultat["leagues"])
    ligues_ok = sum(1 for league in resultat["leagues"] if league["teams_count"] > 0)
    
    print(f"\n📊 RÉSUMÉ:")
    print(f"✅ Ligues traitées avec succès: {ligues_ok}/{len(ligues)}")
    print(f"⚽ Total équipes récupérées: {total_equipes}")

    # Sauvegarder le fichier
    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    
    try:
        with open(args.sortie, "w", encoding="utf-8") as f:
            json.dump(resultat, f, ensure_ascii=False, indent=2)
        print(f"💾 Fichier sauvegardé: {args.sortie}")
        
        # Afficher la taille du fichier
        taille = os.path.getsize(args.sortie)
        print(f"📏 Taille du fichier: {taille:,} bytes")
        
    except Exception as e:
        print(f"❌ Erreur sauvegarde {args.sortie}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
