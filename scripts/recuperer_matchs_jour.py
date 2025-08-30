#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, argparse, time
from datetime import datetime, timezone
from typing import Any, Dict, List, Iterable, Optional
import requests
import yaml

BASE_URL = "https://api-football-v1.p.rapidapi.com/v3"
TZ_PARIS = "Europe/Paris"

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
        raise RuntimeError(f"API error {r.status_code} for {url} params={params} body={r.text[:400]}")
    raise RuntimeError("Retries exhausted")

def _coerce_int(x: Any) -> Optional[int]:
    """Essaie de convertir x en int, sinon None."""
    if x is None:
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, float) and x.is_integer():
        return int(x)
    if isinstance(x, str):
        s = x.strip()
        if s.isdigit():
            return int(s)
        try:
            return int(float(s))
        except Exception:
            return None
    return None

def _yield_ids(val: Any) -> Iterable[int]:
    """
    Retourne une liste d'IDs entiers à partir de formats variés :
    - int / str  -> un seul ID
    - list       -> plusieurs (int/str/dict)
    - dict       -> cherche keys: league_id / id
    """
    if isinstance(val, dict):
        cid = _coerce_int(val.get("league_id") if "league_id" in val else val.get("id"))
        if cid is not None:
            yield cid
        return
    if isinstance(val, list):
        for it in val:
            # chaque élément peut être int/str/dict
            if isinstance(it, dict):
                cid = _coerce_int(it.get("league_id") if "league_id" in it else it.get("id"))
                if cid is not None:
                    yield cid
            else:
                cid = _coerce_int(it)
                if cid is not None:
                    yield cid
        return
    # scalaire
    cid = _coerce_int(val)
    if cid is not None:
        yield cid

def load_leagues(yaml_path: str) -> List[Dict[str, Any]]:
    """
    Lit ligues.yaml et renvoie une liste [{"league_id": int, "league_name": str}, ...]
    Supporte :
      - dict: { "Premier League": 39, "La Liga": [140, 850] }
      - list de dicts: [ {league_id: 39, league_name: "Premier League"}, ... ]
      - list mixtes
    """
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    out: List[Dict[str, Any]] = []
    seen: set[int] = set()

    if isinstance(data, dict):
        for name, raw in data.items():
            for lid in _yield_ids(raw):
                if lid not in seen:
                    out.append({"league_id": lid, "league_name": str(name)})
                    seen.add(lid)
    elif isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                # essaie de lire nom + valeur(s)
                name = entry.get("league_name") or entry.get("name")
                raw = entry.get("league_id", None)
                if raw is None:
                    raw = entry.get("id", None)
                # Si aucun champ direct, il se peut que l'entrée contienne plusieurs ids
                if raw is None and "ids" in entry:
                    raw = entry.get("ids")
                if name is None:
                    name = "Ligue"
                for lid in _yield_ids(raw):
                    if lid not in seen:
                        out.append({"league_id": lid, "league_name": str(name)})
                        seen.add(lid)
            else:
                # élément scalaire dans la liste
                for lid in _yield_ids(entry):
                    if lid not in seen:
                        out.append({"league_id": lid, "league_name": f"Ligue {lid}"})
                        seen.add(lid)
    else:
        raise ValueError("Format ligues.yaml non reconnu (dict ou list attendu)")

    return out

def main():
    ap = argparse.ArgumentParser(description="Récupère les fixtures du jour pour les ligues listées dans ligues.yaml")
    ap.add_argument("--ligues", required=False, default="ligues.yaml", help="Chemin du fichier des ligues (YAML)")
    ap.add_argument("--season", required=True, help="Saison (ex: 2025)")
    ap.add_argument("--date", required=True, help="Date au format YYYY-MM-DD")
    ap.add_argument("--out", required=False, default="donnees/matchs_du_jour.json",
                    help="Fichier de sortie (écrasé à chaque run). Défaut: donnees/matchs_du_jour.json")
    args = ap.parse_args()

    key = os.getenv("RAPIDAPI_KEY")
    host = os.getenv("RAPIDAPI_HOST", "api-football-v1.p.rapidapi.com")
    if not key:
        print("Erreur: RAPIDAPI_KEY manquant", file=sys.stderr)
        sys.exit(1)

    leagues = load_leagues(args.ligues)
    if not leagues:
        print("Aucune ligue trouvée dans ligues.yaml", file=sys.stderr)
        sys.exit(1)

    date_str = args.date.strip()
    season = str(args.season).strip()

    out_path = args.out.strip()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    all_fixtures: List[Dict[str, Any]] = []

    for lig in leagues:
        league_id = lig["league_id"]
        league_name = lig["league_name"]
        params = {
            # ordre comme tu le souhaites : date -> league -> season -> timezone
            "date": date_str,
            "league": league_id,
            "season": season,
            "timezone": TZ_PARIS,
        }
        data = api_get("/fixtures", params=params, key=key, host=host)
        fixtures = data.get("response", []) or []
        print(f"[INFO] {league_name} (ID {league_id}) — {len(fixtures)} match(s) le {date_str}")
        all_fixtures.extend(fixtures)
        time.sleep(0.2)

    result = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "timezone": TZ_PARIS,
        "season": season,
        "date": date_str,
        "count": len(all_fixtures),
        "fixtures": all_fixtures,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[OK] Écrit: {out_path} | Total fixtures: {len(all_fixtures)}")

if __name__ == "__main__":
    main()
