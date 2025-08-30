#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, time, argparse
import requests
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"

def charger_team_ids(fichier_path: str) -> List[Dict]:
    """Charge le fichier team_ids.json généré précédemment"""
    with open(fichier_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    equipes = []
    for league in data.get('leagues', []):
        league_id = league['league_id']
        season = league['season']
        for team in league.get('teams', []):
            equipes.append({
                'league_id': league_id,
                'season': season,
                'team_id': team['team_id'],
                'team_name': team['name']
            })
    
    return equipes

def get_team_statistics(league_id: int, season: str, team_id: int, api_key: str) -> Optional[Dict]:
    """Récupère les statistiques d'une équipe via l'endpoint /teams/statistics"""
    
    url = f"{BASE_URL}/teams/statistics"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com"
    }
    params = {
        "league": league_id,
        "season": season,
        "team": team_id
    }
    
    print(f"[API] GET {url}?league={league_id}&season={season}&team={team_id}")
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        
        if response.status_code == 429:  # Rate limit
            print(f"[WARN] Rate limit - pause 10s...")
            time.sleep(10)
            return None
        
        if response.status_code != 200:
            print(f"[ERROR] Status {response.status_code}: {response.text[:200]}")
            return None
        
        data = response.json()
        
        if data.get('errors'):
            print(f"[WARN] API Errors: {data['errors']}")
            return None
        
        results = data.get('results', 0)
        if results == 0:
            print(f"[WARN] Aucune statistique trouvée")
            return None
        
        # L'API renvoie les stats dans response
        stats_raw = data.get('response', {})
        if not stats_raw:
            return None
        
        return stats_raw
        
    except requests.exceptions.Timeout:
        print(f"[TIMEOUT] Team {team_id}")
        return None
    except Exception as e:
        print(f"[ERROR] Exception: {e}")
        return None

def extraire_stats_cles(stats_raw: Dict, team_id: int, team_name: str) -> Dict:
    """Extrait et formate les statistiques clés selon votre spec UltraSafe"""
    
    # Structure de base
    stats_clean = {
        "gf_avg": None,      # goals.for.average.total
        "ga_avg": None,      # goals.against.average.total  
        "sot_avg": None,     # shots.on.average
        "possession": None,  # possession moyenne
        "wins_total": None,  # fixtures.wins.total
        "played_total": None, # fixtures.played.total
        
        # Stats bonus
        "gf_total": None,    # goals.for.total.total
        "ga_total": None,    # goals.against.total.total
        "wins5": None,       # forme récente (si dispo)
        "pass_accuracy": None # précision passes
    }
    
    try:
        # Buts pour/contre moyens
        goals = stats_raw.get('goals', {})
        if goals.get('for', {}).get('average', {}).get('total'):
            stats_clean['gf_avg'] = float(goals['for']['average']['total'])
        if goals.get('against', {}).get('average', {}).get('total'):  
            stats_clean['ga_avg'] = float(goals['against']['average']['total'])
        
        # Buts totaux (bonus)
        if goals.get('for', {}).get('total', {}).get('total'):
            stats_clean['gf_total'] = int(goals['for']['total']['total'])
        if goals.get('against', {}).get('total', {}).get('total'):
            stats_clean['ga_total'] = int(goals['against']['total']['total'])
        
        # Tirs cadrés moyens
        shots = stats_raw.get('shots', {})
        if shots.get('on', {}).get('average'):
            stats_clean['sot_avg'] = float(shots['on']['average'])
        
        # Possession
        # (L'API peut avoir différents formats pour la possession)
        possession_data = stats_raw.get('possession', {})
        if isinstance(possession_data, dict):
            poss_avg = possession_data.get('average')
            if poss_avg:
                # Nettoyer le % si présent
                poss_val = str(poss_avg).replace('%', '')
                stats_clean['possession'] = float(poss_val)
        
        # Victoires et matchs joués
        fixtures = stats_raw.get('fixtures', {})
        if fixtures.get('wins', {}).get('total'):
            stats_clean['wins_total'] = int(fixtures['wins']['total'])
        if fixtures.get('played', {}).get('total'):
            stats_clean['played_total'] = int(fixtures['played']['total'])
        
        # Précision des passes (bonus)
        passes = stats_raw.get('passes', {})
        if passes.get('accuracy'):
            acc_val = str(passes['accuracy']).replace('%', '')
            stats_clean['pass_accuracy'] = float(acc_val)
        
        print(f"[STATS] {team_name}: GF={stats_clean['gf_avg']}, GA={stats_clean['ga_avg']}, Wins={stats_clean['wins_total']}/{stats_clean['played_total']}")
        
    except Exception as e:
        print(f"[WARN] Erreur extraction stats pour {team_name}: {e}")
    
    return stats_clean

def main():
    parser = argparse.ArgumentParser(description="Récupère les statistiques détaillées des équipes")
    parser.add_argument("--teams-file", required=True, help="Fichier team_ids.json")
    parser.add_argument("--output", required=True, help="Fichier de sortie .jsonl")
    parser.add_argument("--league", type=int, help="Traiter une seule ligue (optionnel)")
    parser.add_argument("--limit", type=int, help="Limiter le nombre d'équipes (test)")
    parser.add_argument("--pause", type=float, default=2.0, help="Pause entre requêtes (secondes)")
    args = parser.parse_args()

    api_key = os.getenv("RAPIDAPI_KEY")
    if not api_key:
        print("❌ RAPIDAPI_KEY manquante")
        sys.exit(1)

    print(f"🔑 API Key: {api_key[:10]}...")
    print(f"📁 Teams file: {args.teams_file}")
    print(f"💾 Output: {args.output}")
    print(f"⏸️ Pause: {args.pause}s")

    # Charger les équipes
    try:
        equipes = charger_team_ids(args.teams_file)
        print(f"📋 {len(equipes)} équipes chargées")
    except Exception as e:
        print(f"❌ Erreur lecture {args.teams_file}: {e}")
        sys.exit(1)

    # Filtrage optionnel
    if args.league:
        equipes = [e for e in equipes if e['league_id'] == args.league]
        print(f"🎯 Filtré sur ligue {args.league}: {len(equipes)} équipes")
    
    if args.limit:
        equipes = equipes[:args.limit]
        print(f"⚡ Limité à {args.limit} équipes pour test")

    # Préparer fichier de sortie
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    
    # Traitement avec sauvegarde progressive (JSONL = 1 ligne par équipe)
    successes = 0
    echecs = 0
    start_time = time.time()
    
    with open(args.output, 'w', encoding='utf-8') as f:
        
        for i, equipe in enumerate(equipes, 1):
            league_id = equipe['league_id']
            season = equipe['season']  
            team_id = equipe['team_id']
            team_name = equipe['team_name']
            
            print(f"\n[{i}/{len(equipes)}] 📊 {team_name} (L{league_id}, T{team_id})")
            print("-" * 60)
            
            # Estimation temps restant
            if i > 1:
                elapsed = time.time() - start_time
                avg_time = elapsed / (i - 1)
                remaining_time = avg_time * (len(equipes) - i)
                print(f"⏱️ Temps écoulé: {elapsed:.1f}s | Estimation: {remaining_time:.1f}s")
            
            try:
                # Récupérer statistiques brutes
                stats_raw = get_team_statistics(league_id, season, team_id, api_key)
                
                if stats_raw:
                    # Extraire les stats clés
                    stats_clean = extraire_stats_cles(stats_raw, team_id, team_name)
                    
                    # Format final JSONL
                    record = {
                        "league_id": league_id,
                        "season": season,
                        "team_id": team_id, 
                        "team_name": team_name,
                        "stats": stats_clean,
                        "source_timestamp": datetime.now(timezone.utc).isoformat(),
                        "raw_data_available": True
                    }
                    
                    # Écrire ligne JSONL
                    f.write(json.dumps(record, ensure_ascii=False) + '\n')
                    f.flush()  # Force l'écriture
                    
                    successes += 1
                    print(f"✅ Statistiques sauvegardées")
                    
                else:
                    # Équipe sans stats
                    record = {
                        "league_id": league_id,
                        "season": season, 
                        "team_id": team_id,
                        "team_name": team_name,
                        "stats": {},
                        "source_timestamp": datetime.now(timezone.utc).isoformat(),
                        "raw_data_available": False,
                        "error": "Aucune statistique disponible"
                    }
                    
                    f.write(json.dumps(record, ensure_ascii=False) + '\n')
                    f.flush()
                    
                    echecs += 1
                    print(f"❌ Aucune statistique disponible")
                
                # Pause entre requêtes
                if i < len(equipes):
                    print(f"⏸️ Pause {args.pause}s...")
                    time.sleep(args.pause)
                    
            except KeyboardInterrupt:
                print(f"\n🛑 Interruption - {successes} équipes traitées")
                break
            except Exception as e:
                echecs += 1
                print(f"❌ Erreur critique: {e}")
                
                # Sauvegarder l'erreur aussi
                record = {
                    "league_id": league_id,
                    "season": season,
                    "team_id": team_id, 
                    "team_name": team_name,
                    "stats": {},
                    "source_timestamp": datetime.now(timezone.utc).isoformat(),
                    "raw_data_available": False,
                    "error": str(e)
                }
                
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
                f.flush()

    # Statistiques finales
    total_time = time.time() - start_time
    
    print(f"\n📊 RÉSUMÉ FINAL:")
    print(f"✅ Équipes avec statistiques: {successes}")
    print(f"❌ Équipes sans statistiques: {echecs}")
    print(f"⏱️ Temps total: {total_time:.1f}s")
    print(f"💾 Fichier: {args.output}")
    
    # Vérifier le fichier
    if os.path.exists(args.output):
        taille = os.path.getsize(args.output)
        lignes = sum(1 for line in open(args.output, 'r'))
        print(f"📏 Taille fichier: {taille:,} bytes")
        print(f"📄 Lignes JSONL: {lignes}")
    
    print(f"\n🎯 Prêt pour la logique UltraSafe ! 🚀")

if __name__ == "__main__":
    main()
