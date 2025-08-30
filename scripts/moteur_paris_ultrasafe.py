#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moteur de Paris UltraSafe
Implémente l'arbre de décision pour générer paris_du_jour.csv et historique.csv
"""

import os, sys, json, csv, argparse
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from collections import defaultdict
import math

@dataclass
class TeamStats:
    """Statistiques d'une équipe (pondérées 2024/2025)"""
    team_id: int
    team_name: str
    league_id: int
    
    # Stats de base
    played_total: int
    wins_total: int
    gf_avg: float
    ga_avg: float
    
    # Stats bonus (peuvent être None)
    clean_sheets_total: Optional[int] = None
    failed_to_score_total: Optional[int] = None
    over15_rate: Optional[float] = None
    
    # Indicateurs dérivés (calculés)
    win_rate: float = 0.0
    goal_diff_avg: float = 0.0
    attack_open: float = 0.0
    defense_leak: float = 0.0
    reliability_attack: float = 0.0
    reliability_defense: float = 0.0
    
    def __post_init__(self):
        """Calcule les indicateurs dérivés"""
        self.win_rate = self.wins_total / max(self.played_total, 1)
        self.goal_diff_avg = self.gf_avg - self.ga_avg
        self.attack_open = self.gf_avg
        self.defense_leak = self.ga_avg
        
        # Fiabilité attaque (éviter failed_to_score)
        if self.failed_to_score_total is not None:
            self.reliability_attack = 1 - (self.failed_to_score_total / max(self.played_total, 1))
        else:
            # Estimation basée sur gf_avg (équipes qui marquent > 1.5/match = fiables)
            self.reliability_attack = min(self.gf_avg / 1.5, 0.95)
        
        # Fiabilité défense (clean sheets)
        if self.clean_sheets_total is not None:
            self.reliability_defense = self.clean_sheets_total / max(self.played_total, 1)
        else:
            # Estimation inverse de ga_avg (défenses < 1.0/match = fiables)
            self.reliability_defense = max(0, 1 - self.ga_avg / 1.5)

@dataclass 
class MatchAnalysis:
    """Résultat de l'analyse d'un match"""
    equipe_a: str
    equipe_b: str
    league_id: int
    
    # Indices calculés
    o15i: float
    rsi_a: float
    rsi_b: float
    
    # Décisions
    decision_over15: str
    decision_result: str
    
    # Fiabilité [0-1]
    fiabilite_over15: float
    fiabilite_result: float
    
    # Flags & métadonnées
    flags: List[str]
    equipe_a_id: int
    equipe_b_id: int
    
    def to_dict(self) -> Dict:
        """Conversion pour CSV/JSON"""
        return {
            'match': f"{self.equipe_a} vs {self.equipe_b}",
            'league_id': self.league_id,
            'equipe_a': self.equipe_a,
            'equipe_b': self.equipe_b,
            'equipe_a_id': self.equipe_a_id,
            'equipe_b_id': self.equipe_b_id,
            'O15I': round(self.o15i, 3),
            'RSI_A': round(self.rsi_a, 3),
            'RSI_B': round(self.rsi_b, 3),
            'decision_over15': self.decision_over15,
            'decision_result': self.decision_result,
            'fiabilite_over15': round(self.fiabilite_over15, 3),
            'fiabilite_result': round(self.fiabilite_result, 3),
            'flags': '|'.join(self.flags),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

class MoteurUltraSafe:
    """Moteur principal de calcul des paris UltraSafe"""
    
    def __init__(self):
        # Seuils configurables (ton système)
        self.SEUILS = {
            'ultrasafe_over15': 0.78,
            'safe_over15': 0.68,
            'ultrasafe_result': 0.60,
            'safe_result': 0.45,
            'played_min': 6,
            'played_combine_min': 10
        }
        
        # Cache des stats équipes
        self.stats_cache: Dict[int, TeamStats] = {}
        
    def charger_stats_equipes(self, fichier_stats: str) -> None:
        """Charge et traite le fichier stats_equipes.jsonl"""
        print(f"📊 Chargement stats depuis {fichier_stats}...")
        
        stats_2024 = defaultdict(dict)
        stats_2025 = defaultdict(dict)
        
        with open(fichier_stats, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                if not line.strip():
                    continue
                    
                try:
                    record = json.loads(line)
                    
                    if not record.get('raw_data_available', False):
                        continue
                    
                    team_id = record['team_id']
                    season = record['season']
                    stats = record.get('stats', {})
                    
                    # Stocker par saison
                    if season == '2024':
                        stats_2024[team_id] = {
                            'team_name': record['team_name'],
                            'league_id': record['league_id'],
                            'stats': stats
                        }
                    elif season == '2025':
                        stats_2025[team_id] = {
                            'team_name': record['team_name'], 
                            'league_id': record['league_id'],
                            'stats': stats
                        }
                        
                except json.JSONDecodeError as e:
                    print(f"[WARN] JSON error ligne {line_num}: {e}")
                except Exception as e:
                    print(f"[WARN] Error processing ligne {line_num}: {e}")
        
        print(f"📈 Stats 2024: {len(stats_2024)} équipes")
        print(f"📈 Stats 2025: {len(stats_2025)} équipes")
        
        # Pondération et fusion
        self._creer_stats_ponderees(stats_2024, stats_2025)
        
    def _creer_stats_ponderees(self, stats_2024: Dict, stats_2025: Dict) -> None:
        """Crée les stats pondérées selon la logique saison"""
        
        for team_id in set(stats_2024.keys()) | set(stats_2025.keys()):
            s24 = stats_2024.get(team_id, {}).get('stats', {})
            s25 = stats_2025.get(team_id, {}).get('stats', {})
            
            # Métadonnées (priorité 2025 puis 2024)
            meta = stats_2025.get(team_id) or stats_2024.get(team_id)
            if not meta:
                continue
                
            team_name = meta['team_name']
            league_id = meta['league_id']
            
            # Pondération selon played_2025
            played_2025 = s25.get('played_total') or 0
            
            if played_2025 < 8:  # Début de saison
                weight_2025, weight_2024 = 0.3, 0.7
                print(f"[POND] {team_name}: début saison ({played_2025} matchs) → 30%/70%")
            else:  # Saison avancée
                weight_2025, weight_2024 = 0.7, 0.3
                
            # Fusion pondérée des stats numériques
            stats_final = {}
            for field in ['played_total', 'wins_total', 'gf_avg', 'ga_avg', 
                         'clean_sheets_total', 'failed_to_score_total']:
                val_2025 = s25.get(field)
                val_2024 = s24.get(field)
                
                if val_2025 is not None and val_2024 is not None:
                    stats_final[field] = weight_2025 * val_2025 + weight_2024 * val_2024
                elif val_2025 is not None:
                    stats_final[field] = val_2025
                elif val_2024 is not None:
                    stats_final[field] = val_2024
                else:
                    stats_final[field] = 0
            
            # Over 1.5 rate (estimation si absent)
            over15_2025 = s25.get('over15_rate')
            over15_2024 = s24.get('over15_rate')
            
            if over15_2025 and over15_2024:
                over15_final = weight_2025 * over15_2025 + weight_2024 * over15_2024
            else:
                # Estimation: open_avg / 3.0, clampé [0.3, 0.95]
                open_avg = (stats_final['gf_avg'] + stats_final['ga_avg'])
                over15_final = max(0.3, min(0.95, open_avg / 3.0))
            
            # Créer TeamStats
            try:
                team_stats = TeamStats(
                    team_id=team_id,
                    team_name=team_name,
                    league_id=league_id,
                    played_total=int(stats_final['played_total']),
                    wins_total=int(stats_final['wins_total']),
                    gf_avg=float(stats_final['gf_avg']),
                    ga_avg=float(stats_final['ga_avg']),
                    clean_sheets_total=int(stats_final['clean_sheets_total']) if stats_final['clean_sheets_total'] else None,
                    failed_to_score_total=int(stats_final['failed_to_score_total']) if stats_final['failed_to_score_total'] else None,
                    over15_rate=float(over15_final)
                )
                
                self.stats_cache[team_id] = team_stats
                
            except Exception as e:
                print(f"[WARN] Impossible de créer TeamStats pour {team_name}: {e}")
        
        print(f"✅ Cache final: {len(self.stats_cache)} équipes")
    
    def calculer_o15i(self, team_a: TeamStats, team_b: TeamStats) -> float:
        """Calcule l'indice Over 1.5 selon ta formule"""
        
        # Estimation over15 par équipe
        est_over15_a = team_a.over15_rate if team_a.over15_rate else max(0.3, min(0.95, (team_a.gf_avg + team_a.ga_avg) / 3.0))
        est_over15_b = team_b.over15_rate if team_b.over15_rate else max(0.3, min(0.95, (team_b.gf_avg + team_b.ga_avg) / 3.0))
        
        # Combinaison indépendante
        o15i = 1 - (1 - est_over15_a) * (1 - est_over15_b)
        
        return o15i
    
    def calculer_rsi(self, team_a: TeamStats, team_b: TeamStats) -> Tuple[float, float]:
        """Calcule les indices RSI pour A vs B et B vs A"""
        
        # Deltas normalisés
        delta_win = team_a.win_rate - team_b.win_rate  # [-1, +1]
        
        delta_gdiff = team_a.goal_diff_avg - team_b.goal_diff_avg
        delta_gdiff_norm = delta_gdiff / 2.0  # Normalise sur [-1, +1] pour ±2 buts/match
        
        delta_atk = team_a.gf_avg - team_b.gf_avg  
        delta_atk_norm = delta_atk / 3.0  # Normalise sur [-1, +1] pour ±3 buts/match
        
        delta_def = team_b.ga_avg - team_a.ga_avg  # "A encaisse moins" = positif
        delta_def_norm = delta_def / 3.0
        
        delta_fail = team_a.reliability_attack - team_b.reliability_attack  # [-1, +1]
        delta_cs = team_a.reliability_defense - team_b.reliability_defense  # [-1, +1]
        
        # RSI selon tes pondérations
        rsi_a = (0.40 * delta_win + 
                 0.25 * delta_gdiff_norm + 
                 0.15 * delta_def_norm +
                 0.10 * delta_atk_norm + 
                 0.05 * delta_fail + 
                 0.05 * delta_cs)
        
        rsi_b = -rsi_a  # Symétrique
        
        return rsi_a, rsi_b
    
    def appliquer_filtres(self, team_a: TeamStats, team_b: TeamStats) -> List[str]:
        """Applique les filtres d'exclusion et retourne les flags"""
        flags = []
        
        # 1. Échantillon faible
        if team_a.played_total < self.SEUILS['played_min']:
            flags.append(f"echantillon_faible_A({team_a.played_total})")
        if team_b.played_total < self.SEUILS['played_min']:
            flags.append(f"echantillon_faible_B({team_b.played_total})")
        
        # Combined sample too small
        if (team_a.played_total + team_b.played_total) < self.SEUILS['played_combine_min']:
            flags.append("echantillon_combine_faible")
        
        # 2. Mélange divisions (à implémenter si données dispo)
        # Cette logique nécessiterait l'historique des divisions
        # flags.append("melange_divisions") si détecté
        
        # 3. Différence de niveau suspecte (heuristique)
        if abs(team_a.goal_diff_avg - team_b.goal_diff_avg) > 2.0:
            flags.append("gap_niveau_important")
        
        return flags
    
    def prendre_decision_over15(self, o15i: float, flags: List[str]) -> Tuple[str, float]:
        """Décision pour le pari +1.5 buts"""
        
        # Downgrade si échantillon faible
        seuil_ultra = self.SEUILS['ultrasafe_over15']
        seuil_safe = self.SEUILS['safe_over15']
        
        if any('echantillon' in flag for flag in flags):
            seuil_ultra += 0.05  # Plus strict
            seuil_safe += 0.03
        
        if o15i >= seuil_ultra:
            return "UltraSafe +1.5", o15i
        elif o15i >= seuil_safe:
            return "Safe +1.5", o15i
        else:
            return "Éviter +1.5", o15i
    
    def prendre_decision_result(self, rsi_a: float, rsi_b: float, flags: List[str]) -> Tuple[str, float]:
        """Décision pour le pari résultat (double chance)"""
        
        # Exclusions
        no_ultrasafe = any(flag in ['melange_divisions', 'echantillon_combine_faible'] for flag in flags)
        
        # Downgrade si échantillon faible
        seuil_ultra = self.SEUILS['ultrasafe_result']
        seuil_safe = self.SEUILS['safe_result']
        
        if any('echantillon' in flag for flag in flags):
            seuil_ultra += 0.05
            seuil_safe += 0.03
        
        # Décision côté A
        if rsi_a >= seuil_ultra and not no_ultrasafe:
            return "UltraSafe A ou Nul", rsi_a
        elif rsi_a >= seuil_safe:
            return "Safe A ou Nul", rsi_a
        
        # Décision côté B (si RSI_A pas suffisant)
        elif rsi_b >= seuil_ultra and not no_ultrasafe:
            return "UltraSafe B ou Nul", rsi_b
        elif rsi_b >= seuil_safe:
            return "Safe B ou Nul", rsi_b
        
        else:
            # Match trop serré
            fiabilite = max(abs(rsi_a), abs(rsi_b))
            return "Éviter Résultat", fiabilite
    
    def analyser_match(self, team_a_id: int, team_b_id: int) -> Optional[MatchAnalysis]:
        """Analyse complète d'un match selon ton arbre de décision"""
        
        # Récupérer les stats
        team_a = self.stats_cache.get(team_a_id)
        team_b = self.stats_cache.get(team_b_id)
        
        if not team_a or not team_b:
            print(f"[WARN] Stats manquantes: Team {team_a_id} ou {team_b_id}")
            return None
        
        # Vérifier même ligue
        if team_a.league_id != team_b.league_id:
            print(f"[WARN] Ligues différentes: {team_a.team_name} (L{team_a.league_id}) vs {team_b.team_name} (L{team_b.league_id})")
            return None
        
        print(f"\n🎯 ANALYSE: {team_a.team_name} vs {team_b.team_name}")
        print(f"   A: {team_a.gf_avg:.1f}GF {team_a.ga_avg:.1f}GA ({team_a.played_total}m)")
        print(f"   B: {team_b.gf_avg:.1f}GF {team_b.ga_avg:.1f}GA ({team_b.played_total}m)")
        
        # 1. Appliquer filtres
        flags = self.appliquer_filtres(team_a, team_b)
        
        # 2. Calculer indices
        o15i = self.calculer_o15i(team_a, team_b)
        rsi_a, rsi_b = self.calculer_rsi(team_a, team_b)
        
        print(f"   📊 O15I: {o15i:.3f} | RSI_A: {rsi_a:.3f} | RSI_B: {rsi_b:.3f}")
        if flags:
            print(f"   ⚠️ Flags: {flags}")
        
        # 3. Prendre décisions
        decision_over15, fiab_over15 = self.prendre_decision_over15(o15i, flags)
        decision_result, fiab_result = self.prendre_decision_result(rsi_a, rsi_b, flags)
        
        print(f"   🎲 +1.5: {decision_over15} ({fiab_over15:.3f})")
        print(f"   🎲 Résultat: {decision_result} ({fiab_result:.3f})")
        
        return MatchAnalysis(
            equipe_a=team_a.team_name,
            equipe_b=team_b.team_name,
            league_id=team_a.league_id,
            o15i=o15i,
            rsi_a=rsi_a,
            rsi_b=rsi_b,
            decision_over15=decision_over15,
            decision_result=decision_result,
            fiabilite_over15=fiab_over15,
            fiabilite_result=fiab_result,
            flags=flags,
            equipe_a_id=team_a_id,
            equipe_b_id=team_b_id
        )
    
    def generer_paris_du_jour(self, matchs_input: List[Tuple[int, int]], 
                             output_csv: str, historique_csv: str) -> None:
        """Génère les fichiers CSV selon ton système"""
        
        print(f"\n🎰 GÉNÉRATION PARIS DU JOUR ({len(matchs_input)} matchs)")
        print("=" * 60)
        
        analyses = []
        ultrasafe_over15 = []
        ultrasafe_result = []
        
        # Analyser tous les matchs
        for team_a_id, team_b_id in matchs_input:
            analysis = self.analyser_match(team_a_id, team_b_id)
            if analysis:
                analyses.append(analysis)
                
                # Collecter UltraSafe
                if analysis.decision_over15.startswith("UltraSafe"):
                    ultrasafe_over15.append(analysis)
                if analysis.decision_result.startswith("UltraSafe"):
                    ultrasafe_result.append(analysis)
        
        # Trier par fiabilité décroissante
        ultrasafe_over15.sort(key=lambda x: x.fiabilite_over15, reverse=True)
        ultrasafe_result.sort(key=lambda x: x.fiabilite_result, reverse=True)
        
        print(f"\n📊 RÉSULTATS:")
        print(f"   🎯 UltraSafe +1.5: {len(ultrasafe_over15)} matchs")
        print(f"   🎯 UltraSafe Résultat: {len(ultrasafe_result)} matchs")
        
        # Générer paris_du_jour.csv (écrasé chaque jour)
        self._ecrire_paris_du_jour(ultrasafe_over15, ultrasafe_result, output_csv)
        
        # Ajouter à l'historique
        self._ajouter_historique(analyses, historique_csv)
        
        print(f"✅ Paris du jour: {output_csv}")
        print(f"✅ Historique mis à jour: {historique_csv}")
    
    def _ecrire_paris_du_jour(self, ultrasafe_over15: List[MatchAnalysis], 
                             ultrasafe_result: List[MatchAnalysis], output_csv: str) -> None:
        """Écrit le fichier paris_du_jour.csv"""
        
        os.makedirs(os.path.dirname(output_csv) if os.path.dirname(output_csv) else '.', exist_ok=True)
        
        with open(output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Header
            writer.writerow([
                'Type', 'Match', 'League_ID', 'Pari', 'Fiabilité', 
                'Équipe_A', 'Équipe_B', 'O15I', 'RSI_A', 'RSI_B', 'Flags'
            ])
            
            # UltraSafe +1.5 (top 3)
            for i, analysis in enumerate(ultrasafe_over15[:3], 1):
                writer.writerow([
                    'UltraSafe_Over15',
                    f"{analysis.equipe_a} vs {analysis.equipe_b}",
                    analysis.league_id,
                    '+1.5 Buts',
                    analysis.fiabilite_over15,
                    analysis.equipe_a,
                    analysis.equipe_b,
                    analysis.o15i,
                    analysis.rsi_a,
                    analysis.rsi_b,
                    '|'.join(analysis.flags)
                ])
            
            # UltraSafe Résultat (top 3)
            for i, analysis in enumerate(ultrasafe_result[:3], 1):
                pari_type = "1X" if analysis.rsi_a > analysis.rsi_b else "X2"
                equipe_fav = analysis.equipe_a if analysis.rsi_a > analysis.rsi_b else analysis.equipe_b
                
                writer.writerow([
                    'UltraSafe_Result',
                    f"{analysis.equipe_a} vs {analysis.equipe_b}",
                    analysis.league_id,
                    f"{equipe_fav} ou Nul ({pari_type})",
                    analysis.fiabilite_result,
                    analysis.equipe_a,
                    analysis.equipe_b,
                    analysis.o15i,
                    analysis.rsi_a,
                    analysis.rsi_b,
                    '|'.join(analysis.flags)
                ])
    
    def _ajouter_historique(self, analyses: List[MatchAnalysis], historique_csv: str) -> None:
        """Ajoute les analyses à l'historique (append mode)"""
        
        # Créer le fichier avec header si n'existe pas
        file_exists = os.path.exists(historique_csv)
        os.makedirs(os.path.dirname(historique_csv) if os.path.dirname(historique_csv) else '.', exist_ok=True)
        
        with open(historique_csv, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Header seulement si nouveau fichier
            if not file_exists:
                writer.writerow([
                    'Date', 'Match', 'League_ID', 'Decision_Over15', 'Decision_Result',
                    'O15I', 'RSI_A', 'RSI_B', 'Fiabilite_Over15', 'Fiabilite_Result',
                    'Équipe_A_ID', 'Équipe_B_ID', 'Flags'
                ])
            
            # Ajouter toutes les analyses du jour
            date_today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            
            for analysis in analyses:
                writer.writerow([
                    date_today,
                    f"{analysis.equipe_a} vs {analysis.equipe_b}",
                    analysis.league_id,
                    analysis.decision_over15,
                    analysis.decision_result,
                    analysis.o15i,
                    analysis.rsi_a,
                    analysis.rsi_b,
                    analysis.fiabilite_over15,
                    analysis.fiabilite_result,
                    analysis.equipe_a_id,
                    analysis.equipe_b_id,
                    '|'.join(analysis.flags)
                ])

def charger_matchs_du_jour(fichier_matchs: str) -> List[Tuple[int, int]]:
    """Charge la liste des matchs du jour depuis JSON/CSV"""
    
    if not os.path.exists(fichier_matchs):
        print(f"❌ Fichier matchs du jour manquant: {fichier_matchs}")
        return []
    
    matchs = []
    
    try:
        if fichier_matchs.endswith('.json'):
            with open(fichier_matchs, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # Format attendu: {"matchs": [{"team_a_id": 50, "team_b_id": 42}, ...]}
            for match in data.get('matchs', []):
                team_a = match.get('team_a_id')
                team_b = match.get('team_b_id')
                if team_a and team_b:
                    matchs.append((team_a, team_b))
        
        elif fichier_matchs.endswith('.csv'):
            with open(fichier_matchs, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                
                for row in reader:
                    team_a = int(row['team_a_id'])
                    team_b = int(row['team_b_id'])
                    matchs.append((team_a, team_b))
        
        print(f"📅 {len(matchs)} matchs chargés depuis {fichier_matchs}")
        return matchs
        
    except Exception as e:
        print(f"❌ Erreur lecture {fichier_matchs}: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(description="Moteur Paris UltraSafe")
    parser.add_argument("--stats-file", required=True, help="Fichier stats_equipes.jsonl")
    parser.add_argument("--matchs-file", required=True, help="Fichier matchs du jour (JSON/CSV)")
    parser.add_argument("--output", default="donnees/paris_du_jour.csv", help="Fichier paris du jour")
    parser.add_argument("--historique", default="donnees/historique.csv", help="Fichier historique")
    parser.add_argument("--seuils", help="Fichier JSON seuils custom (optionnel)")
    parser.add_argument("--debug", action="store_true", help="Mode debug verbose")
    
    args = parser.parse_args()
    
    print("🎰 MOTEUR ULTRASAFE - GÉNÉRATION PARIS DU JOUR")
    print("=" * 60)
    
    # Initialiser le moteur
    moteur = MoteurUltraSafe()
    
    # Charger seuils custom si fournis
    if args.seuils:
        try:
            with open(args.seuils, 'r', encoding='utf-8') as f:
                seuils_custom = json.load(f)
            moteur.SEUILS.update(seuils_custom)
            print(f"🎛️ Seuils custom chargés: {seuils_custom}")
        except Exception as e:
            print(f"[WARN] Impossible de charger seuils custom: {e}")
    
    print(f"🎯 Seuils actuels: {moteur.SEUILS}")
    
    # Charger les statistiques des équipes
    try:
        moteur.charger_stats_equipes(args.stats_file)
    except Exception as e:
        print(f"❌ Erreur chargement stats: {e}")
        sys.exit(1)
    
    # Charger les matchs du jour
    matchs_input = charger_matchs_du_jour(args.matchs_file)
    if not matchs_input:
        print("❌ Aucun match à analyser")
        sys.exit(1)
    
    # Générer les paris
    try:
        moteur.generer_paris_du_jour(matchs_input, args.output, args.historique)
        
        print(f"\n🎉 SUCCÈS!")
        print(f"📁 Paris du jour: {args.output}")
        print(f"📁 Historique: {args.historique}")
        
        # Affichage du résumé
        if os.path.exists(args.output):
            with open(args.output, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                paris_count = sum(1 for _ in reader)
            print(f"📊 {paris_count} paris UltraSafe générés")
        
    except Exception as e:
        print(f"❌ Erreur génération paris: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

# Fonctions utilitaires pour testing/debug

def creer_matchs_test() -> None:
    """Crée un fichier de test avec quelques matchs Premier League"""
    matchs_test = {
        "matchs": [
            {"team_a_id": 50, "team_b_id": 42, "commentaire": "Man City vs Arsenal"},
            {"team_a_id": 40, "team_b_id": 49, "commentaire": "Liverpool vs Chelsea"},
            {"team_a_id": 33, "team_b_id": 47, "commentaire": "Man United vs Tottenham"},
            {"team_a_id": 66, "team_b_id": 51, "commentaire": "Aston Villa vs Brighton"},
            {"team_a_id": 48, "team_b_id": 45, "commentaire": "West Ham vs Everton"}
        ]
    }
    
    with open('donnees/matchs_test.json', 'w', encoding='utf-8') as f:
        json.dump(matchs_test, f, indent=2, ensure_ascii=False)
    
    print("✅ Fichier test créé: donnees/matchs_test.json")

def afficher_stats_equipe(moteur: MoteurUltraSafe, team_id: int) -> None:
    """Debug: affiche les stats détaillées d'une équipe"""
    team = moteur.stats_cache.get(team_id)
    if not team:
        print(f"❌ Équipe {team_id} non trouvée")
        return
    
    print(f"\n📊 STATS DÉTAILLÉES: {team.team_name} (ID: {team_id})")
    print(f"   🏆 Ligue: {team.league_id}")
    print(f"   ⚽ Matchs joués: {team.played_total}")
    print(f"   🎯 Victoires: {team.wins_total} ({team.win_rate:.1%})")
    print(f"   ⚽ Buts pour/contre: {team.gf_avg:.2f} / {team.ga_avg:.2f}")
    print(f"   📈 Diff buts: {team.goal_diff_avg:+.2f}")
    print(f"   🛡️ Clean sheets: {team.clean_sheets_total}")
    print(f"   ❌ Failed to score: {team.failed_to_score_total}")
    print(f"   📊 Over 1.5 rate: {team.over15_rate:.1%}")
    print(f"   🎯 Fiabilité attaque: {team.reliability_attack:.1%}")
    print(f"   🛡️ Fiabilité défense: {team.reliability_defense:.1%}")

if __name__ == "__main__":
    main() 
