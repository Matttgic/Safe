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
    
    for lig in data["ligues"]:
        if "league_id" not in lig:
            raise ValueError("Une entrée de 'ligues' ne contient pas 'league_id'.")
    return data["ligues"]

def requete_api(path: str, params: Dict[str, Any], key: str, host: str, max_retry: int = 3, pause: float = 1.5, debug: bool = False) -> Dict[str, Any]:
    headers = {
        "X-RapidAPI-Key": key,
        "X-RapidAPI-Host": host or "api-football-v1.p.rapidapi.com",
        "Accept": "application/json",
    }
    url = f"{BASE_URL}{path}"
    
    if debug:
        print(f"[DEBUG] URL: {url}")
        print(f"[DEBUG] Params: {params}")
    
    for tentative in range(1, max_retry + 1):
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        
        if debug:
            print(f"[DEBUG] Status: {resp.status_code}")
            print(f"[DEBUG] Response preview: {resp.text[:200]}")
        
        if resp.status_code == 200:
            try:
                data = resp.json()
                
                # Vérification des erreurs API-Football
                if "errors" in data and data["errors"]:
                    print(f"[WARN] API errors: {data['errors']}")
                
                return data
            except Exception as e:
                raise RuntimeError(f"JSON invalide pour {url}: {e}")
        
        # Gestion des erreurs spécifiques
        if resp.status_code == 429:
            print(f"[WARN] Rate limit atteint, pause {pause * tentative}s...")
        elif resp.status_code == 404:
            print(f"[WARN] Endpoint non trouvé: {url}")
            return {"response": [], "results": 0}
        elif resp.status_code in (500, 502, 503, 504):
            print(f"[WARN] Erreur serveur {resp.status_code}, retry {tentative}/{max_retry}")
        
        if tentative < max_retry:
            time.sleep(pause * tentative)
            continue
        
        # Dernière tentative échouée
        raise RuntimeError(f"Appel API échoué ({resp.status_code}) pour {url}\nResponse: {resp.text[:500]}")
    
    raise RuntimeError("Épuisement des retries API.")

def tester_saison_ligue(league_id: int, saisons: List[str], key: str, host: str) -> str:
    """Teste différentes saisons pour trouver la première qui marche"""
    for saison in saisons:
        try:
            data = requete_api(
                "/teams",
                {"league": league_id, "season": saison},
                key=key,
                host=host,
                max_retry=1,
                debug=False
            )
            
            results = data.get("results", 0)
            if results > 0:
                print(f"[INFO] Saison {saison} disponible pour ligue {league_id} ({results} équipes)")
                return saison
                
        except Exception:
            continue
    
    # Aucune saison trouvée
    print(f"[WARN] Aucune saison trouvée pour ligue {league_id} parmi {saisons}")
    return saisons[0]  # Retourner la saison par défaut

def lister_equipes_ligue(league_id: int, saison: str, key: str, host: str, auto_saison: bool = False) -> List[Dict[str, Any]]:
    """GET /teams?league={id}&season={saison} avec pagination si nécessaire."""
    
    # Si auto_saison est activé, tester plusieurs saisons
    if auto_saison:
        saisons_a_tester = [saison, "2024", "2023", "2022"]
        saison_finale = tester_saison_ligue(league_id, saisons_a_tester, key, host)
    else:
        saison_finale = saison
    
    equipes: List[Dict[str, Any]] = []
    page = 1
    
    while True:
        data = requete_api(
            "/teams",
            {"league": league_id, "season": saison_finale, "page": page},
            key=key,
            host=host,
        )
        
        resp = data.get("response", [])
        results = data.get("results", 0)
        
        if results == 0 and page == 1:
            print(f"[WARN] Aucune équipe trouvée pour ligue {league_id} saison {saison_finale}")
            break
        
        for item in resp:
            team = item.get("team", {}) or {}
            t_id = team.get("id")
            t_name = team.get("name")
            if t_id is not None and t_name:
                equipes.append({
                    "team_id": t_id, 
                    "name": t_name,
                    "season_used": saison_finale  # Traçabilité
                })
        
        paging = data.get("paging", {})
        cur, total = paging.get("current", 1), paging.get("total", 1)
        if cur >= total:
            break
        page += 1
        time.sleep(0.4)
    
    return equipes

def main():
    parser = argparse.ArgumentParser(description="Récupère les Team IDs pour chaque ligue définie dans ligues.yaml.")
    parser.add_argument("--entree", required=True, help="Chemin du fichier ligues.yaml")
    parser.add_argument("--sortie", required=True, help="Chemin du fichier JSON de sortie")
    parser.add_argument("--saison", required=True, help="Saison (ex: 2024)")
    parser.add_argument("--auto-saison", action="store_true", help="Auto-détection de la saison disponible")
    parser.add_argument("--debug", action="store_true", help="Mode debug verbeux")
    args = parser.parse_args()

    rapid_key = os.getenv("RAPIDAPI_KEY")
    rapid_host = os.getenv("RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com")
    
    if not rapid_key:
        print("Erreur: variable d'environnement RAPIDAPI_KEY absente.", file=sys.stderr)
        sys.exit(1)

    if args.debug:
        print(f"[DEBUG] API Host: {rapid_host}")
        print(f"[DEBUG] API Key: {rapid_key[:12]}...")

    ligues = lire_ligues_yaml(args.entree)
    print(f"[INFO] {len(ligues)} ligues à traiter")

    resultat = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "season_requested": args.saison,
        "auto_season": args.auto_saison,
        "leagues": []
    }

    for i, lig in enumerate(ligues, 1):
        league_id = int(lig["league_id"])
        nom = lig.get("nom") or lig.get("name") or f"Ligue {league_id}"
        
        print(f"[INFO] [{i}/{len(ligues)}] {nom} (ID {league_id})")
        
        try:
            equipes = lister_equipes_ligue(
                league_id, 
                args.saison, 
                key=rapid_key, 
                host=rapid_host,
                auto_saison=args.auto_saison
            )
            
            # Retirer season_used de chaque équipe pour le JSON final
            equipes_clean = []
            saison_utilisee = args.saison
            for equipe in equipes:
                if "season_used" in equipe:
                    saison_utilisee = equipe["season_used"]
                    del equipe["season_used"]
                equipes_clean.append(equipe)
            
            resultat["leagues"].append({
                "league_id": league_id,
                "league_name": nom,
                "season": saison_utilisee,
                "teams_count": len(equipes_clean),
                "teams": equipes_clean
            })
            
            print(f"[INFO] → {len(equipes_clean)} équipes (saison {saison_utilisee})")
            
        except Exception as e:
            print(f"[ERREUR] {nom}: {e}")
            resultat["leagues"].append({
                "league_id": league_id,
                "league_name": nom,
                "season": args.saison,
                "teams_count": 0,
                "teams": [],
                "error": str(e)
            })

    # Écrire la sortie
    os.makedirs(os.path.dirname(args.sortie), exist_ok=True)
    with open(args.sortie, "w", encoding="utf-8") as f:
        json.dump(resultat, f, ensure_ascii=False, indent=2)
    
    total_equipes = sum(l["teams_count"] for l in resultat["leagues"])
    print(f"[OK] Écrit: {args.sortie} ({total_equipes} équipes au total)")

if __name__ == "__main__":
    main()
