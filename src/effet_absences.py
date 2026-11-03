"""Mesure l'effet des absences des meilleurs buteurs sur les résultats, à partir de l'historique (API-Football).

Pour chaque équipe, on compare les points obtenus dans les matchs où l'un de ses trois meilleurs buteurs est
absent (blessé ou suspendu, statut « Missing Fixture ») à ceux des autres matchs. Chaque équipe sert de
référence à elle-même (effets fixes par équipe) : le niveau propre de l'équipe ne fausse donc pas la mesure.

Seul le résultat agrégé est enregistré (data/absences/effet_absences.json) : aucun nom de joueur, aucun match.
Aucune cote n'est utilisée.

Usage : API_FOOTBALL_KEY=... API_FOOTBALL_SAISON=2024 python3 src/effet_absences.py
"""
import json
import math
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

RACINE = pathlib.Path(__file__).resolve().parent.parent
LIGUES = json.load(open(RACINE / 'data' / 'ligues_api.json', encoding='utf-8'))
BASE = os.environ.get('API_FOOTBALL_BASE', 'https://v3.football.api-sports.io')
SAISON = int(os.environ.get('API_FOOTBALL_SAISON', '2024'))
PAUSE = float(os.environ.get('API_FOOTBALL_PAUSE', '7'))  # 10 appels par minute au maximum
SORTIE = RACINE / 'data' / 'absences' / 'effet_absences.json'
CODES = ['E0', 'E1', 'SP1', 'I1', 'D1', 'F1', 'N1', 'T1']  # championnats où l'API renvoie les blessures
TOP = 3  # nombre de meilleurs buteurs suivis par équipe


def appeler(cle, chemin, params):
    url = BASE + chemin + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'x-apisports-key': cle, 'User-Agent': 'Lotofoot-effet/1.0'})
    with urllib.request.urlopen(req, timeout=90) as rep:
        donnees = json.load(rep)
    if donnees.get('errors'):
        raise RuntimeError('API : %s' % donnees['errors'])
    return donnees.get('response') or []


def collecte(cle):
    matchs, buteurs, blessures = [], defaultdict(lambda: defaultdict(list)), []
    for code in CODES:
        lid = LIGUES[code]
        matchs += appeler(cle, '/fixtures', {'league': lid, 'season': SAISON})
        time.sleep(PAUSE)
        for p in appeler(cle, '/players/topscorers', {'league': lid, 'season': SAISON}):
            statistique = (p.get('statistics') or [{}])[0]
            equipe = (statistique.get('team') or {}).get('id')
            buts = (statistique.get('goals') or {}).get('total') or 0
            if equipe is not None and (p.get('player') or {}).get('id') is not None:
                buteurs[code][equipe].append((buts, p['player']['id']))
        time.sleep(PAUSE)
        blessures += appeler(cle, '/injuries', {'league': lid, 'season': SAISON})
        time.sleep(PAUSE)
        print('%-4s matchs %d | blessures %d' % (code, len(matchs), len(blessures)), flush=True)
    return matchs, buteurs, blessures


def points(buts_pour, buts_contre):
    return 3 if buts_pour > buts_contre else (1 if buts_pour == buts_contre else 0)


def mesure(matchs, buteurs, blessures):
    cles = {}  # équipe -> identifiants de ses meilleurs buteurs
    for code, par_equipe in buteurs.items():
        for equipe, liste in par_equipe.items():
            liste.sort(reverse=True)
            cles[equipe] = {pid for _, pid in liste[:TOP]}
    absents = set()
    for x in blessures:
        joueur, match = x.get('player') or {}, x.get('fixture') or {}
        if joueur.get('type') == 'Missing Fixture' and match.get('id') is not None and joueur.get('id') is not None:
            absents.add((match['id'], joueur['id']))
    lignes = []  # (équipe, points, absence d'un meilleur buteur)
    for m in matchs:
        if ((m.get('fixture') or {}).get('status') or {}).get('short') not in ('FT', 'AET', 'PEN'):
            continue
        buts = m.get('goals') or {}
        if buts.get('home') is None or buts.get('away') is None:
            continue
        mid = m['fixture']['id']
        dom, ext = m['teams']['home']['id'], m['teams']['away']['id']
        for equipe, pour, contre in ((dom, buts['home'], buts['away']), (ext, buts['away'], buts['home'])):
            absence = any((mid, pid) in absents for pid in cles.get(equipe, set()))
            lignes.append((equipe, points(pour, contre), 1 if absence else 0))
    # Régression à effets fixes par équipe : points = équipe + effet × absence
    par_equipe = defaultdict(list)
    for equipe, pts, d in lignes:
        par_equipe[equipe].append((pts, d))
    sxy = sxx = 0.0
    residus = []
    for equipe, liste in par_equipe.items():
        n = len(liste)
        mp = sum(p for p, _ in liste) / n
        md = sum(d for _, d in liste) / n
        for p, d in liste:
            sxy += (p - mp) * (d - md)
            sxx += (d - md) ** 2
    if sxx == 0:
        return None
    beta = sxy / sxx
    for equipe, liste in par_equipe.items():
        n = len(liste)
        mp = sum(p for p, _ in liste) / n
        md = sum(d for _, d in liste) / n
        for p, d in liste:
            residus.append(((p - mp) - beta * (d - md)))
    ddl = max(len(lignes) - len(par_equipe) - 1, 1)
    se = math.sqrt(sum(r * r for r in residus) / ddl / sxx)
    return {
        'saison': SAISON,
        'championnats': CODES,
        'equipes': len(par_equipe),
        'matchs_equipe': len(lignes),
        'matchs_avec_absence': sum(d for _, _, d in lignes),
        'effet_points_par_match': round(beta, 4),
        'erreur_standard': round(se, 4),
        'intervalle_95': [round(beta - 1.96 * se, 4), round(beta + 1.96 * se, 4)],
        'meilleurs_buteurs_suivis': TOP,
    }


def main():
    cle = os.environ.get('API_FOOTBALL_KEY', '').strip()
    if not cle:
        print('Aucune clé API-Football : rien à mesurer.')
        return 0
    matchs, buteurs, blessures = collecte(cle)
    resultat = mesure(matchs, buteurs, blessures)
    if resultat is None:
        print('Pas assez de données pour mesurer l’effet.')
        return 1
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    with open(SORTIE, 'w', encoding='utf-8') as f:
        json.dump(resultat, f, ensure_ascii=False, indent=1)
    print(json.dumps(resultat, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
