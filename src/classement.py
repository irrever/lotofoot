"""Classement par points de la saison en cours, pour chaque championnat suivi.

Lit les résultats téléchargés par publier.py (data/raw/<saison>_<division>.csv) et écrit data/classements.json :
rang, équipe, points, matchs joués et différence de buts. Sert à repérer le haut et le bas du tableau
(match surprise). Aucune donnée externe n’est ajoutée.

Usage : python3 src/classement.py
"""
import csv
import collections
import datetime as dt
import json
import pathlib

RACINE = pathlib.Path(__file__).resolve().parent.parent
RAW = RACINE / 'data' / 'raw'
SORTIE = RACINE / 'data' / 'classements.json'
SAISON = '2627'
DIVISIONS = ['E0', 'E1', 'SP1', 'SP2', 'I1', 'I2', 'D1', 'D2', 'F1', 'F2', 'N1', 'P1', 'B1', 'T1', 'SC0', 'G1']


def lire(chemin):
    txt = chemin.read_bytes().decode('latin-1', errors='replace').replace('\r', '')
    return list(csv.DictReader([l for l in txt.split('\n') if l.strip()]))


def classement(rows):
    st = collections.defaultdict(lambda: {'pts': 0, 'gf': 0, 'ga': 0, 'j': 0})
    for r in rows:
        try:
            hg, ag = int(r['FTHG']), int(r['FTAG'])
        except (KeyError, TypeError, ValueError):
            continue  # match non joué
        h, a = (r.get('HomeTeam') or '').strip(), (r.get('AwayTeam') or '').strip()
        if not h or not a:
            continue
        st[h]['j'] += 1
        st[a]['j'] += 1
        st[h]['gf'] += hg; st[h]['ga'] += ag
        st[a]['gf'] += ag; st[a]['ga'] += hg
        if hg > ag:
            st[h]['pts'] += 3
        elif hg < ag:
            st[a]['pts'] += 3
        else:
            st[h]['pts'] += 1; st[a]['pts'] += 1
    ordre = sorted(st.items(), key=lambda kv: (-kv[1]['pts'], -(kv[1]['gf'] - kv[1]['ga']), -kv[1]['gf'], kv[0]))
    return [{'rang': i + 1, 'equipe': nom, 'points': v['pts'], 'matchs': v['j'], 'diff': v['gf'] - v['ga']}
            for i, (nom, v) in enumerate(ordre)]


def principal():
    par_championnat = {}
    for div in DIVISIONS:
        chemin = RAW / ('%s_%s.csv' % (SAISON, div))
        if chemin.exists():
            table = classement(lire(chemin))
            if table:
                par_championnat[div] = table
    SORTIE.write_text(json.dumps({'saison': SAISON, 'date': dt.date.today().isoformat(),
                                  'par_championnat': par_championnat}, ensure_ascii=False, indent=1), encoding='utf-8')
    print('classements écrits :', len(par_championnat), 'championnats')


if __name__ == '__main__':
    principal()
