# 🎰 Moteur Paris UltraSafe

Implémentation de votre arbre de décision pour générer automatiquement les paris quotidiens avec un système de fiabilité robuste.

## 📋 Vue d'ensemble

Le moteur analyse les statistiques d'équipes (2024/2025 pondérées) et applique votre logique de décision pour identifier les paris **UltraSafe** et **Safe** sur :
- **+1.5 buts** (basé sur l'indice O15I)
- **Double chance** (basé sur l'indice RSI)

## 🔧 Installation et Prérequis

### Fichiers requis
```
donnees/
├── stats_equipes.jsonl      # Généré par le workflow précédent
├── matchs_du_jour.json      # Matchs à analyser
└── team_ids.json           # Référence équipes
```

### Structure attendue matchs_du_jour.json
```json
{
  "generated_at": "2025-08-30T12:00:00Z",
  "source": "manuel",
  "matchs": [
    {"team_a_id": 50, "team_b_id": 42, "commentaire": "Man City vs Arsenal"},
    {"team_a_id": 40, "team_b_id": 49, "commentaire": "Liverpool vs Chelsea"}
  ]
}
```

## 🎯 Logique de Décision (Votre Système)

### 1. Pondération Saison
- **Début saison** (played_2025 < 8) : `30% × 2025 + 70% × 2024`
- **Saison avancée** : `70% × 2025 + 30% × 2024`

### 2. Indice Over 1.5 (O15I)
```python
openA = gf_avg_A + ga_avg_A
openB = gf_avg_B + ga_avg_B
est_over15A = over15_rate_A || clamp(openA/3.0, 0.3, 0.95)
est_over15B = over15_rate_B || clamp(openB/3.0, 0.3, 0.95)

O15I = 1 - (1 - est_over15A) * (1 - est_over15B)
```

**Seuils :**
- `O15I ≥ 0.78` → **UltraSafe +1.5**
- `0.68 ≤ O15I < 0.78` → **Safe +1.5**
- `< 0.68` → **Éviter +1.5**

### 3. Indice Résultat (RSI)
```python
RSI = 0.40×Δwin + 0.25×Δgdiff_norm + 0.15×Δdef_norm + 0.10×Δatk_norm + 0.05×Δfail + 0.05×Δcs
```

**Seuils :**
- `RSI ≥ 0.60` → **UltraSafe "A ou Nul"**
- `0.45 ≤ RSI < 0.60` → **Safe "A ou Nul"**
- `RSI ≤ -0.60` → **UltraSafe "B ou Nul"**

### 4. Filtres d'Exclusion
- Échantillon faible (`played_total < 6`)
- Mélange divisions saison précédente
- Gap de niveau suspect (`|goal_diff| > 2.0`)

## 🚀 Utilisation

### Mode Standard
```bash
# Génération paris du jour
python3 scripts/moteur_paris_ultrasafe.py \
  --stats-file donnees/stats_equipes.jsonl \
  --matchs-file donnees/matchs_du_jour.json \
  --output donnees/paris_du_jour.csv \
  --historique donnees/historique.csv
```

### Mode Test
```bash
# Test avec matchs prédéfinis
python3 exemples_utilisation.py test

# Démo Premier League
python3 exemples_utilisation.py demo

# Simulation journée complète
python3 exemples_utilisation.py simulation
```

### Mode Interactif
```bash
# Console interactive pour tests
python3 exemples_utilisation.py interactif

# Exemples de commandes:
> stats 50                  # Stats Manchester City
> match 50 42              # Analyser Man City vs Arsenal  
> list 39                  # Équipes Premier League
> seuils                   # Afficher seuils actuels
```

### Seuils Personnalisés
```bash
# Créer seuils conservateurs
python3 exemples_utilisation.py seuils-conservateurs

# Utiliser seuils custom
python3 scripts/moteur_paris_ultrasafe.py \
  --seuils donnees/seuils_conservateurs.json \
  [autres arguments...]
```

## 📊 Fichiers de Sortie

### paris_du_jour.csv (écrasé quotidiennement)
```csv
Type,Match,League_ID,Pari,Fiabilité,Équipe_A,Équipe_B,O15I,RSI_A,RSI_B,Flags
UltraSafe_Over15,Man City vs Arsenal,39,+1.5 Buts,0.842,Man City,Arsenal,0.842,0.156,-0.156,
UltraSafe_Result,Liverpool vs Chelsea,39,Liverpool ou Nul (1X),0.723,Liverpool,Chelsea,0.651,0.723,-0.723,
```

### historique.csv (cumulatif)
```csv
Date,Match,League_ID,Decision_Over15,Decision_Result,O15I,RSI_A,RSI_B,Fiabilite_Over15,Fiabilite_Result,Équipe_A_ID,Équipe_B_ID,Flags
2025-08-30,Man City vs Arsenal,39,UltraSafe +1.5,Safe A ou Nul,0.842,0.156,-0.156,0.842,0.156,50,42,
```

## 🎛️ Configuration Avancée

### Seuils Personnalisables
```json
{
  "ultrasafe_over15": 0.78,
  "safe_over15": 0.68, 
  "ultrasafe_result": 0.60,
  "safe_result": 0.45,
  "played_min": 6,
  "played_combine_min": 10
}
```

### Variantes de Seuils
- **Conservateurs** : +0.05 sur tous les seuils
- **Agressifs** : -0.05 sur tous les seuils
- **Début de saison** : +0.03 automatiquement si échantillon faible

## 🔄 Workflows GitHub Actions

### Exécution Manuelle
```yaml
# Via interface GitHub
# Workflow: "Générer Paris du Jour UltraSafe"
# Inputs: matchs_source=test, debug_mode=true
```

### Exécution Automatique
```yaml
# Programmé quotidiennement à 8h UTC
schedule:
  - cron: '0 8 * * *'
```

## 📈 Validation et Monitoring

### Métriques de Qualité
- **Taux UltraSafe** : % de matchs atteignant les seuils stricts
- **Distribution fiabilité** : Histogramme des indices
- **Flags d'exclusion** : Fréquence des filtres appliqués

### Tests de Cohérence
```bash
# Validation mathématique
python3 exemples_utilisation.py coherence

# Analyse performance historique  
python3 exemples_utilisation.py performance
```

## 🎯 Bonnes Pratiques

### 1. **Début de Saison**
- Utiliser seuils conservateurs (+0.05)
- Privilégier équipes avec > 8 matchs 2025
- Surveiller flags "echantillon_faible"

### 2. **Milieu de Saison**
- Seuils standard
- Pondération 70% saison courante
- Focus sur consistency patterns

### 3. **Fin de Saison**
- Attention à la motivation variable
- Surveiller rotations/repos
- Éviter dernières journées sans enjeu

## 🐛 Debugging

### Logs Détaillés
```bash
# Mode debug complet
python3 scripts/moteur_paris_ultrasafe.py --debug [args...]

# Logs typiques:
[POND] Arsenal: début saison (7 matchs) → 30%/70%
🎯 ANALYSE: Man City vs Arsenal
   A: 2.3GF 0.9GA (18m)
   B: 2.1GF 1.1GA (16m) 
   📊 O15I: 0.847 | RSI_A: 0.234 | RSI_B: -0.234
   🎲 +1.5: UltraSafe +1.5 (0.847)
   🎲 Résultat: Safe A ou Nul (0.234)
```

### Fichiers Debug Générés
- `debug_raw_*.json` : Données API brutes (mode --debug)
- `debug_analysis_*.json` : Détails calculs indices

## ⚠️ Limitations Connues

1. **Stats bonus manquantes** : `clean_sheets`, `failed_to_score` estimées si absentes
2. **Over15_rate** : Calculée heuristiquement si non fournie par l'API
3. **Mélange divisions** : Détection à implémenter avec données historiques
4. **Coupes/amicaux** : Filtrage manuel requis dans matchs_du_jour.json

## 🔮 Roadmap

- [ ] Intégration API matchs du jour automatique
- [ ] Machine Learning pour affiner les pondérations
- [ ] Détection automatique rotations/repos
- [ ] Backtesting sur saisons précédentes
- [ ] Interface web pour visualisation

## 💡 Exemples Rapides

```bash
# Test rapide avec 5 matchs Premier League
python3 exemples_utilisation.py demo

# Mode interactif pour explorer
python3 exemples_utilisation.py interactif

# Validation complète
python3 exemples_utilisation.py test
```

---

**Note** : Le moteur implémente fidèlement votre arbre de décision. Les seuils sont ajustables selon vos retours d'expérience, mais la logique mathématique reste constante pour assurer la reproductibilité.
