#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moteur de Paris UltraSafe
Implémente l'arbre de décision pour générer paris_du_jour.csv et historique.csv
"""

import os
import sys
import json
import csv
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

# --- Structures de Données (Dataclasses) ---

@dataclass
class TeamStats:
    """Représente les statistiques consolidées et pondérées d'une équipe."""
    team_id: int
    team_name: str
    league_id: int
    played_total: int
    wins_total: int
    gf_avg: float
    ga_avg: float
    clean_sheets_total: Optional[int] = None
    failed_to_score_total: Optional[int] = None
    over15_rate: Optional[float] = None
    
    win_rate: float = field(init=False)
    goal_diff_avg: float = field(init=False)
    reliability_attack: float = field(init=False)
    reliability_defense: float = field(init=False)
    
    def __post_init__(self):
        """Calcule les métriques dérivées."""
        self.win_rate = self.wins_total / self.played_total if self.played_total > 0 else 0
        self.goal_diff_avg = self.gf_avg - self.ga_avg
        
        if self.failed_to_score_total is not None and self.played_total > 0:
            self.reliability_attack = 1 - (self.failed_to_score_total / self.played_total)
        else:
            self.reliability_attack = min(self.gf_avg / 1.5, 0.95)
        
        if self.clean_sheets_total is not None and self.played_total > 0:
            self.reliability_defense = self.clean_sheets_total / self.played_total
        else:
            self.reliability_defense = max(0, 1 - self.ga_avg / 1.5)

@dataclass 
class MatchAnalysis:
    """Contient tous les résultats de l'analyse d'un match."""
    equipe_a: str
    equipe_b: str
    equipe_a_id: int
    equipe_b_id: int
    league_id: int
    o15i: float
    rsi_a: float
    rsi_b: float
    decision_over15: str
    decision_result: str
    fiabilite_over15: float
    fiabilite_result: float
    flags: List[str]

# --- Classe Principale du Moteur ---

class MoteurUltraSafe:
    """Moteur principal de calcul des paris UltraSafe."""
    
    def __init__(self, debug_mode=False):
        self.debug = debug_mode
        self.SEUILS = {
            'ultrasafe_over15': 0.78, 'safe_over15': 0.68,
            'ultrasafe_result': 0.60, 'safe_result': 0.45,
            'played_min': 6, 'played_combine_min': 10
        }
        self.stats_cache: Dict[int, TeamStats] = {}

    def charger_stats_equipes(self, primary_stats_file: str, fallback_stats_file: Optional[str] = None):
        """Charge les statistiques depuis les fichiers jsonl."""
        print(f"📊 Chargement des statistiques depuis {primary_stats_file}...")
        
        stats2025 = self._read_stats_file(primary_stats_file)
        stats2024 = self._read_stats_file(fallback_stats_file) if fallback_stats_file else {}
        
        print(f"📈 Données 2025: {len(stats2025)} équipes valides.")
        print(f"📈 Données 2024: {len(stats2024)} équipes valides.")
        
        # Logique adaptative : si peu de données en 2025, on privilégie 2024.
        if len(stats2025) < 50:
            print("🆕 Début de saison détecté. Application de la stratégie fallback (priorité 2024).")
            self._creer_stats_ponderees(stats2024, stats2025, fallback_mode=True)
        else:
            print("📊 Saison en cours. Application de la pondération standard.")
            self._creer_stats_ponderees(stats2024, stats2025, fallback_mode=False)
            
    def _read_stats_file(self, file_path: Optional[str]) -> Dict[int, Dict]:
        """Lit un fichier .jsonl et retourne un dictionnaire de stats par team_id."""
        if not file_path or not os.path.exists(file_path):
            return {}
        
        stats_dict = {}
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                try:
                    record = json.loads(line)
                    # On vérifie juste si les stats essentielles sont là.
                    if 'stats' in record and record['stats'].get('played_total') is not None:
                        stats_dict[record['team_id']] = record
                except json.JSONDecodeError:
                    if self.debug: print(f"[AVERTISSEMENT] Ligne JSON invalide dans {os.path.basename(file_path)}.")
        return stats_dict

    def _creer_stats_ponderees(self, stats2024: Dict, stats2025: Dict, fallback_mode: bool):
        """Crée le cache final en pondérant les statistiques."""
        all_team_ids = set(stats2024.keys()) | set(stats2025.keys())
        
        for team_id in all_team_ids:
            s24_record = stats2024.get(team_id, {})
            s25_record = stats2025.get(team_id, {})
            
            meta = s25_record or s24_record
            if not meta: continue
                
            s24 = s24_record.get('stats', {})
            s25 = s25_record.get('stats', {})
            
            # Définir les poids en fonction du mode
            played2025 = s25.get('played_total', 0)
            if fallback_mode:
                weight2025, weight2024 = (0.2, 0.8) if played2025 > 0 else (0.0, 1.0)
            else: # Mode standard
                weight2025, weight2024 = (0.7, 0.3) if played2025 >= 8 else (0.3, 0.7)
            
            stats_final = {}
            fields_to_process = ['played_total', 'wins_total', 'gf_avg', 'ga_avg', 'clean_sheets_total', 'failed_to_score_total', 'over15_rate']
            
            for field in fields_to_process:
                val2025 = s25.get(field)
                val2024 = s24.get(field)
                
                if val2025 is not None and val2024 is not None:
                    stats_final[field] = weight2025 * val2025 + weight2024 * val2024
                else:
                    stats_final[field] = val2025 if val2025 is not None else val2024

            if stats_final.get('played_total') is not None and stats_final.get('played_total', 0) > 0:
                # Calcul de l'over15_rate si manquant
                if stats_final.get('over15_rate') is None:
                    open_avg = stats_final.get('gf_avg', 0) + stats_final.get('ga_avg', 0)
                    stats_final['over15_rate'] = max(0.3, min(0.95, open_avg / 3.0))

                self.stats_cache[team_id] = TeamStats(
                    team_id=team_id, team_name=meta['team_name'], league_id=meta['league_id'],
                    **{k: v for k, v in stats_final.items() if v is not None}
                )

        print(f"✅ Cache de statistiques final créé avec {len(self.stats_cache)} équipes.")

    def analyser_match(self, team_a_id: int, team_b_id: int) -> Optional[MatchAnalysis]:
        """Analyse complète d'un match."""
        team_a = self.stats_cache.get(team_a_id)
        team_b = self.stats_cache.get(team_b_id)

        if not team_a or not team_b:
            if self.debug: print(f"[AVERTISSEMENT] Stats manquantes pour {team_a_id} vs {team_b_id}.")
            return None
        
        if team_a.league_id != team_b.league_id:
            if self.debug: print(f"[AVERTISSEMENT] Ligues différentes: {team_a.team_name} vs {team_b.team_name}.")
            return None

        # Calcul des indices
        o15i = 1 - (1 - team_a.over15_rate) * (1 - team_b.over15_rate)
        delta_win = team_a.win_rate - team_b.win_rate
        delta_gdiff = (team_a.goal_diff_avg - team_b.goal_diff_avg) / 2.0
        delta_def = (team_b.ga_avg - team_a.ga_avg) / 3.0
        rsi_a = (0.50 * delta_win + 0.30 * delta_gdiff + 0.20 * delta_def)
        
        flags = []
        if team_a.played_total < self.SEUILS['played_min']: flags.append(f"low_sample_A({team_a.played_total})")
        if team_b.played_total < self.SEUILS['played_min']: flags.append(f"low_sample_B({team_b.played_total})")

        # Prise de décision
        s = self.SEUILS
        decision_over15 = "UltraSafe +1.5" if o15i >= s['ultrasafe_over15'] else "Safe +1.5" if o15i >= s['safe_over15'] else "Éviter"
        
        if rsi_a >= s['ultrasafe_result']: decision_result = "UltraSafe A ou Nul"
        elif rsi_a >= s['safe_result']: decision_result = "Safe A ou Nul"
        elif rsi_a <= -s['ultrasafe_result']: decision_result = "UltraSafe B ou Nul"
        elif rsi_a <= -s['safe_result']: decision_result = "Safe B ou Nul"
        else: decision_result = "Éviter"

        return MatchAnalysis(
            equipe_a=team_a.team_name, equipe_b=team_b.team_name,
            equipe_a_id=team_a_id, equipe_b_id=team_b_id,
            league_id=team_a.league_id, o15i=o15i, rsi_a=rsi_a, rsi_b=-rsi_a,
            decision_over15=decision_over15, decision_result=decision_result,
            fiabilite_over15=o15i, fiabilite_result=abs(rsi_a),
            flags=flags
        )

    def generer_paris(self, matchs: List[Tuple[int, int]], output_file: str, historique_file: str):
        """Génère les fichiers CSV."""
        print(f"\n🎰 Génération des paris pour {len(matchs)} matchs...")
        analyses = [self.analyser_match(a, b) for a, b in matchs if self.analyser_match(a, b)]
        
        all_paris = [a for a in analyses if a.decision_over15 != "Éviter" or a.decision_result != "Éviter"]
        all_paris.sort(key=lambda x: x.fiabilite_result, reverse=True)
        
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Type', 'Match', 'League_ID', 'Decision_Over15', 'Decision_Result', 'O15I', 'RSI_A', 'Fiabilite_Over15', 'Fiabilite_Result', 'Flags'])
            for analysis in all_paris:
                if analysis.decision_over15 != "Éviter":
                    writer.writerow(['Over15', f"{analysis.equipe_a} vs {analysis.equipe_b}", analysis.league_id, analysis.decision_over15, 'Éviter', f"{analysis.fiabilite_over15:.3f}", f"{analysis.rsi_a:.3f}", f"{analysis.fiabilite_over15:.3f}", f"{analysis.fiabilite_result:.3f}", '|'.join(analysis.flags)])
                if analysis.decision_result != "Éviter":
                    writer.writerow(['Result', f"{analysis.equipe_a} vs {analysis.equipe_b}", analysis.league_id, 'Éviter', analysis.decision_result, f"{analysis.o15i:.3f}", f"{analysis.rsi_a:.3f}", f"{analysis.fiabilite_over15:.3f}", f"{analysis.fiabilite_result:.3f}", '|'.join(analysis.flags)])
        
        self._ajouter_historique(analyses, historique_file)
        print(f"✅ {len(all_paris)} paris écrits dans {output_file}.")

    def _ajouter_historique(self, analyses: List[MatchAnalysis], historique_file: str):
        """Ajoute les analyses du jour au fichier d'historique."""
        file_exists = os.path.exists(historique_file)
        os.makedirs(os.path.dirname(historique_file), exist_ok=True)
        with open(historique_file, 'a', newline='', encoding='utf-8') as f:
            header = ['Date', 'Match', 'League_ID', 'Decision_Over15', 'Decision_Result', 'O15I', 'RSI_A', 'Fiabilite_Over15', 'Fiabilite_Result', 'Flags']
            writer = csv.DictWriter(f, fieldnames=header)
            if not file_exists:
                writer.writeheader()
            date_today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            for analysis in analyses:
                writer.writerow({
                    'Date': date_today, 'Match': f"{analysis.equipe_a} vs {analysis.equipe_b}",
                    'League_ID': analysis.league_id, 'Decision_Over15': analysis.decision_over15,
                    'Decision_Result': analysis.decision_result, 'O15I': f"{analysis.o15i:.3f}",
                    'RSI_A': f"{analysis.rsi_a:.3f}", 'Fiabilite_Over15': f"{analysis.fiabilite_over15:.3f}",
                    'Fiabilite_Result': f"{analysis.fiabilite_result:.3f}", 'Flags': '|'.join(analysis.flags)
                })

def charger_matchs(fichier_matchs: str) -> List[Tuple[int, int]]:
    """Charge la liste des matchs à analyser depuis un fichier JSON."""
    try:
        with open(fichier_matchs, 'r', encoding='utf-8') as f:
            data = json.load(f)
        matchs = [(m['team_a_id'], m['team_b_id']) for m in data.get('matchs', []) if m.get('team_a_id') and m.get('team_b_id')]
        print(f"📅 {len(matchs)} matchs chargés depuis {fichier_matchs}")
        return matchs
    except Exception as e:
        print(f"❌ Erreur lors du chargement de {fichier_matchs}: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(description="Moteur de Paris UltraSafe")
    parser.add_argument("--stats-file", required=True, help="Chemin vers le fichier de stats principal (ex: 2025)")
    parser.add_argument("--fallback-stats", help="Chemin vers le fichier de stats de secours (ex: 2024)")
    parser.add_argument("--matchs-file", required=True, help="Chemin vers le fichier JSON des matchs du jour")
    parser.add_argument("--output", default="donnees/paris_du_jour.csv", help="Fichier de sortie pour les paris")
    parser.add_argument("--historique", default="donnees/historique.csv", help="Fichier d'historique")
    parser.add_argument("--seuils", help="Chemin vers un fichier JSON de seuils custom (optionnel)")
    parser.add_argument("--debug", action="store_true", help="Activer les logs détaillés")
    args = parser.parse_args()

    print("=" * 60)
    print("🎰 MOTEUR ULTRASAFE - DÉMARRAGE DE LA GÉNÉRATION DES PARIS")
    print("=" * 60)

    moteur = MoteurUltraSafe(debug_mode=args.debug)

    if args.seuils:
        try:
            with open(args.seuils, 'r') as f:
                moteur.SEUILS.update(json.load(f))
            print(f"🎛️ Seuils custom chargés: {moteur.SEUILS}")
        except Exception as e:
            print(f"[AVERTISSEMENT] Impossible de charger le fichier de seuils : {e}")
    
    moteur.charger_stats_equipes(args.stats_file, args.fallback_stats)
    
    if len(moteur.stats_cache) == 0:
        print("⚠️ DIAGNOSTIC: Le cache de statistiques est vide ! Aucune équipe n'a pu être chargée.")
    
    matchs = charger_matchs(args.matchs_file)

    if not matchs:
        print("ℹ️ Aucun match à analyser. Le processus s'arrête.")
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, 'w', newline='', encoding='utf-8') as f:
            f.write('Type,Match,Pari,Fiabilité,League_ID,Flags\n')
        sys.exit(0)
    
    moteur.generer_paris(matchs, args.output, args.historique)
    print("\n🎉 Processus terminé avec succès !")

if __name__ == "__main__":
    main() 
