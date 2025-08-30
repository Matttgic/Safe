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
from typing import Dict, List, Optional, Tuple, Any
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
    gf_avg: float  # Buts marqués en moyenne
    ga_avg: float  # Buts encaissés en moyenne
    clean_sheets_total: Optional[int] = None
    failed_to_score_total: Optional[int] = None
    over15_rate: Optional[float] = None
    
    # Indicateurs dérivés calculés après l'initialisation
    win_rate: float = field(init=False)
    goal_diff_avg: float = field(init=False)
    reliability_attack: float = field(init=False)
    reliability_defense: float = field(init=False)
    
    def __post_init__(self):
        """Calcule les métriques dérivées après la création de l'objet."""
        self.win_rate = self.wins_total / self.played_total if self.played_total > 0 else 0
        self.goal_diff_avg = self.gf_avg - self.ga_avg
        
        # Fiabilité de l'attaque (capacité à ne pas rester muet)
        if self.failed_to_score_total is not None and self.played_total > 0:
            self.reliability_attack = 1 - (self.failed_to_score_total / self.played_total)
        else:
            self.reliability_attack = min(self.gf_avg / 1.5, 0.95) # Estimation
        
        # Fiabilité de la défense (capacité à réaliser des clean sheets)
        if self.clean_sheets_total is not None and self.played_total > 0:
            self.reliability_defense = self.clean_sheets_total / self.played_total
        else:
            self.reliability_defense = max(0, 1 - self.ga_avg / 1.5) # Estimation

@dataclass 
class MatchAnalysis:
    """Contient tous les résultats de l'analyse d'un match."""
    equipe_a: str
    equipe_b: str
    equipe_a_id: int
    equipe_b_id: int
    league_id: int
    o15i: float  # Over 1.5 Index
    rsi_a: float # Relative Strength Index pour l'équipe A
    rsi_b: float # Relative Strength Index pour l'équipe B
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
            'ultrasafe_over15': 0.78,
            'safe_over15': 0.68,
            'ultrasafe_result': 0.60,
            'safe_result': 0.45,
            'played_min': 6,
            'played_combine_min': 10
        }
        self.stats_cache: Dict[int, TeamStats] = {}

    def charger_stats_equipes(self, fichier_stats: str):
        """Charge et traite le fichier stats_equipes.jsonl en pondérant les saisons."""
        print(f"📊 Chargement des statistiques depuis {fichier_stats}...")
        stats_par_saison = defaultdict(lambda: defaultdict(dict))

        with open(fichier_stats, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip(): continue
                try:
                    record = json.loads(line)
                    if record.get('raw_data_available', False):
                        team_id = record['team_id']
                        season = record['season']
                        stats_par_saison[season][team_id] = record
                except json.JSONDecodeError:
                    if self.debug: print(f"[AVERTISSEMENT] Ligne JSON invalide ignorée.")
        
        self._creer_stats_ponderees(stats_par_saison.get('2024', {}), stats_par_saison.get('2025', {}))

    def _creer_stats_ponderees(self, stats2024: Dict, stats2025: Dict):
        """Crée les stats finales en pondérant 2024 et 2025."""
        all_team_ids = set(stats2024.keys()) | set(stats2025.keys())
        
        for team_id in all_team_ids:
            s24_record = stats2024.get(team_id, {})
            s25_record = stats2025.get(team_id, {})
            
            meta = s25_record or s24_record
            if not meta: continue
                
            s24 = s24_record.get('stats', {})
            s25 = s25_record.get('stats', {})
            
            played2025 = s25.get('played_total', 0)
            weight2025, weight2024 = (0.7, 0.3) if played2025 >= 8 else (0.3, 0.7)
            
            stats_final = {}
            for field in ['played_total', 'wins_total', 'gf_avg', 'ga_avg', 'clean_sheets_total', 'failed_to_score_total', 'over15_rate']:
                val2025 = s25.get(field)
                val2024 = s24.get(field)
                
                if val2025 is not None and val2024 is not None:
                    stats_final[field] = weight2025 * val2025 + weight2024 * val2024
                else:
                    stats_final[field] = val2025 if val2025 is not None else val2024
            
            if stats_final.get('played_total', 0) > 0:
                self.stats_cache[team_id] = TeamStats(
                    team_id=team_id,
                    team_name=meta['team_name'],
                    league_id=meta['league_id'],
                    **{k: v for k, v in stats_final.items() if v is not None}
                )
        print(f"✅ Cache de statistiques créé avec {len(self.stats_cache)} équipes.")

    def analyser_match(self, team_a_id: int, team_b_id: int) -> Optional[MatchAnalysis]:
        """Analyse complète d'un match selon l'arbre de décision."""
        team_a = self.stats_cache.get(team_a_id)
        team_b = self.stats_cache.get(team_b_id)

        if not team_a or not team_b:
            if self.debug: print(f"[AVERTISSEMENT] Statistiques manquantes pour le match {team_a_id} vs {team_b_id}.")
            return None
        
        if team_a.league_id != team_b.league_id:
            if self.debug: print(f"[AVERTISSEMENT] Ligues différentes pour {team_a.team_name} vs {team_b.team_name}.")
            return None

        # 1. Calcul des indices
        o15i = 1 - (1 - team_a.over15_rate) * (1 - team_b.over15_rate)
        delta_win = team_a.win_rate - team_b.win_rate
        delta_gdiff = (team_a.goal_diff_avg - team_b.goal_diff_avg) / 2.0 # Normalisé
        delta_def = (team_b.ga_avg - team_a.ga_avg) / 3.0 # Normalisé
        rsi_a = (0.50 * delta_win + 0.30 * delta_gdiff + 0.20 * delta_def)
        rsi_b = -rsi_a
        
        # 2. Application des filtres
        flags = []
        if team_a.played_total < self.SEUILS['played_min']: flags.append(f"echantillon_faible_A({team_a.played_total})")
        if team_b.played_total < self.SEUILS['played_min']: flags.append(f"echantillon_faible_B({team_b.played_total})")
        if (team_a.played_total + team_b.played_total) < self.SEUILS['played_combine_min']: flags.append("echantillon_combine_faible")

        # 3. Prise de décision
        seuil_ultra_o15, seuil_safe_o15 = self.SEUILS['ultrasafe_over15'], self.SEUILS['safe_over15']
        seuil_ultra_res, seuil_safe_res = self.SEUILS['ultrasafe_result'], self.SEUILS['safe_result']

        if flags: # Pénalité si flags
            seuil_ultra_o15, seuil_safe_o15 = seuil_ultra_o15 + 0.05, seuil_safe_o15 + 0.03
            seuil_ultra_res, seuil_safe_res = seuil_ultra_res + 0.05, seuil_safe_res + 0.03

        decision_over15 = "UltraSafe +1.5" if o15i >= seuil_ultra_o15 else "Safe +1.5" if o15i >= seuil_safe_o15 else "Éviter +1.5"
        
        if rsi_a >= seuil_ultra_res and "echantillon_combine_faible" not in flags: decision_result = "UltraSafe A ou Nul"
        elif rsi_a >= seuil_safe_res: decision_result = "Safe A ou Nul"
        elif rsi_b >= seuil_ultra_res and "echantillon_combine_faible" not in flags: decision_result = "UltraSafe B ou Nul"
        elif rsi_b >= seuil_safe_res: decision_result = "Safe B ou Nul"
        else: decision_result = "Éviter Résultat"

        return MatchAnalysis(
            equipe_a=team_a.team_name, equipe_b=team_b.team_name,
            equipe_a_id=team_a_id, equipe_b_id=team_b_id,
            league_id=team_a.league_id, o15i=o15i, rsi_a=rsi_a, rsi_b=rsi_b,
            decision_over15=decision_over15, decision_result=decision_result,
            fiabilite_over15=o15i, fiabilite_result=max(abs(rsi_a), abs(rsi_b)),
            flags=flags
        )

    def generer_paris(self, matchs: List[Tuple[int, int]], output_file: str, historique_file: str):
        """Génère les fichiers CSV de paris et d'historique."""
        print(f"\n🎰 Génération des paris pour {len(matchs)} matchs...")
        analyses = [self.analyser_match(a, b) for a, b in matchs]
        analyses = [a for a in analyses if a] # Filtrer les analyses None

        ultrasafe_paris = [a for a in analyses if "UltraSafe" in a.decision_over15 or "UltraSafe" in a.decision_result]
        ultrasafe_paris.sort(key=lambda x: x.fiabilite_result, reverse=True)
        
        # Écriture de paris_du_jour.csv
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Type', 'Match', 'Pari', 'Fiabilité', 'League_ID', 'Flags'])
            for analysis in ultrasafe_paris:
                if "UltraSafe" in analysis.decision_over15:
                    writer.writerow(['UltraSafe_Over15', f"{analysis.equipe_a} vs {analysis.equipe_b}", '+1.5 Buts', f"{analysis.fiabilite_over15:.3f}", analysis.league_id, '|'.join(analysis.flags)])
                if "UltraSafe" in analysis.decision_result:
                    pari = f"{analysis.equipe_a} ou Nul" if analysis.rsi_a > 0 else f"{analysis.equipe_b} ou Nul"
                    writer.writerow(['UltraSafe_Result', f"{analysis.equipe_a} vs {analysis.equipe_b}", pari, f"{analysis.fiabilite_result:.3f}", analysis.league_id, '|'.join(analysis.flags)])
        
        # Mise à jour de l'historique
        self._ajouter_historique(analyses, historique_file)
        print(f"✅ {len(ultrasafe_paris)} paris UltraSafe écrits dans {output_file}.")

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
    parser.add_argument("--stats-file", required=True, help="Chemin vers le fichier stats_equipes.jsonl")
    parser.add_argument("--matchs-file", required=True, help="Chemin vers le fichier JSON des matchs du jour")
    parser.add_argument("--output", default="donnees/paris_du_jour.csv", help="Fichier de sortie pour les paris")
    parser.add_argument("--historique", default="donnees/historique.csv", help="Fichier d'historique des analyses")
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
    
    moteur.charger_stats_equipes(args.stats_file)
    matchs = charger_matchs(args.matchs_file)

    if not matchs:
        print("ℹ️ Aucun match à analyser. Arrêt du processus.")
        # Crée un fichier de paris vide pour éviter les erreurs dans le workflow
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, 'w', newline='', encoding='utf-8') as f:
            f.write('Type,Match,Pari,Fiabilité,League_ID,Flags\n')
        sys.exit(0)
    
    moteur.generer_paris(matchs, args.output, args.historique)
    print("\n🎉 Processus terminé avec succès !")

if __name__ == "__main__":
    main()
