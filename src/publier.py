"""Met à jour les données de Lotofoot en reprenant exactement la méthode en place.
1. Télécharge les résultats depuis football-data.co.uk : la saison en cours à chaque exécution, les saisons
   passées une seule fois (sauf --sans-telechargement).
2. Recalcule les profils et vecteurs des équipes, puis le modèle à 25 variables (teams.py, export_model.py),
   avec pour date de référence le lendemain du dernier match joué.
3. Recalcule la fiche de qualité (evaluation_publiee.py) et le classement Elo des championnats.
4. Écrit data/donnees_publiees.json (les versions précédentes sont gardées dans data/historique/),
   puis reconstruit l’application (standalone/construire.py).
"""
import datetime as dt
import json
import os
import pathlib
import shutil
import ssl
import subprocess
import sys
import urllib.request

SRC = pathlib.Path(__file__).resolve().parent
DATA = SRC.parent / 'data'
RAW = DATA / 'raw'
sys.path.insert(0, str(SRC))

SAISON = '2627'  # saison en cours : téléchargée à chaque exécution
SAISONS_PASSEES = ['1516', '1617', '1718', '1819', '1920', '2021', '2122', '2223', '2324', '2425', '2526']
DIVISIONS = ['E0', 'E1', 'SP1', 'SP2', 'I1', 'I2', 'D1', 'D2', 'F1', 'F2', 'N1', 'P1', 'B1', 'T1', 'SC0', 'G1']
CA = '/root/.ccr/ca-bundle.crt'
MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
        'septembre', 'octobre', 'novembre', 'décembre']


def date_fr(d):
    return ('1er' if d.day == 1 else str(d.day)) + ' ' + MOIS[d.month - 1] + ' ' + str(d.year)


def version_publiee(asof):
    """Version des données : date de référence, complétée par LOTO_REVISION quand les données changent sans nouveau match."""
    rev = os.environ.get('LOTO_REVISION')
    return asof.isoformat() + ('.' + rev if rev else '')


def telecharger(saisons=None):
    """Retourne la liste des fichiers ajoutés ou modifiés. Par défaut : toutes les saisons."""
    ctx = ssl.create_default_context(cafile=CA) if os.path.exists(CA) else ssl.create_default_context()
    RAW.mkdir(parents=True, exist_ok=True)
    modifies = []
    for saison in (saisons or [SAISON] + SAISONS_PASSEES):
        for div in DIVISIONS:
            chemin = RAW / ('%s_%s.csv' % (saison, div))
            if saison != SAISON and chemin.exists():
                continue  # saison passée déjà téléchargée : elle ne change plus
            url = 'https://www.football-data.co.uk/mmz4281/%s/%s.csv' % (saison, div)
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, context=ctx, timeout=60) as rep:
                contenu = rep.read()
            if b'Div' not in contenu[:40]:
                raise RuntimeError('Réponse inattendue pour %s %s : %r' % (saison, div, contenu[:60]))
            if not chemin.exists() or chemin.read_bytes() != contenu:
                chemin.write_bytes(contenu)
                modifies.append('%s %s' % (saison, div))
    return modifies


def etape(script, env):
    print('>>', script, flush=True)
    subprocess.run([sys.executable, str(SRC / script)], cwd=str(SRC), env=env, check=True,
                   stdout=subprocess.DEVNULL)


def classement_elo(st, actifs):
    """Trois meilleures équipes Elo de chaque championnat, parmi les équipes de la saison en cours."""
    from load import LEAGUES
    par_ligue = {}
    for (lg, equipe), v in st.R.items():
        if (lg, equipe) in actifs:
            par_ligue.setdefault(lg, []).append((v, equipe))
    top = []
    for code, nom in LEAGUES.items():
        if par_ligue.get(code):
            meilleures = sorted(par_ligue[code], reverse=True)[:3]
            top.append({'code': code, 'nom': nom, 'equipes': [e for _, e in meilleures]})
    return top


def main():
    sans_telechargement = '--sans-telechargement' in sys.argv
    modifies = [] if sans_telechargement else telecharger()
    print('Fichiers téléchargés et modifiés :', modifies or 'aucun')

    from load import load_all
    rows = load_all()
    joues = [r for r in rows if r['result'] in ('H', 'D', 'A')]
    derniere = max(r['date'] for r in joues)
    asof = derniere + dt.timedelta(days=1)
    print('Dernier match joué :', derniere, '| date de référence :', asof)

    env = dict(os.environ, LOTO_ASOF=asof.isoformat())
    etape('teams.py', env)
    etape('export_model.py', env)

    from features2 import build, equipes_de_la_saison
    data, st = build(rows)
    actifs = equipes_de_la_saison(rows)
    import evaluation_publiee as ev
    f = ev.fiche(data)
    v5 = json.load(open(DATA / 'stats_v5.json', encoding='utf-8'))
    NOTES = json.load(open(DATA / 'notes_championnats.json', encoding='utf-8'))
    comparaison = [
        {'nom': 'Probabilités moyennes de l’historique', 'erreur_test': round(f['test']['moyenne'], 4),
         'precision_test': None, 'erreur_recent': round(f['recent']['moyenne'], 4), 'precision_recent': None},
        {'nom': 'Modèle statistique (matchs d’un même championnat)', 'erreur_test': round(f['test']['modele'], 4),
         'precision_test': round(f['test']['modele_precision'] * 100, 1),
         'erreur_recent': round(f['recent']['modele'], 4),
         'precision_recent': round(f['recent']['modele_precision'] * 100, 1)},
        {'nom': 'Elo seul (matchs d’un même championnat ; utilisé entre championnats)',
         'erreur_test': round(f['test']['elo'], 4), 'precision_test': round(f['test']['elo_precision'] * 100, 1),
         'erreur_recent': None, 'precision_recent': None},
    ]
    stats = {
        'periode_stats': v5['periode_stats'], 'periode_test': v5['periode_test'],
        'periode_recent': '2026-27 (saison en cours, jusqu’au %s)' % date_fr(derniere),
        'n_matchs_test': f['test']['n'], 'n_matchs_recent': f['recent']['n'],
        'base_stats': v5['base_stats'], 'comparaison': comparaison,
        'top_equipes': classement_elo(st, actifs),
        'notes': NOTES['notes'], 'notes_methode': NOTES['methode'], 'points_elo_par_note': NOTES['points_elo_par_point_de_note'],
        'parametres_elo': v5['parametres_elo'],
    }
    equipes = json.load(open(DATA / 'teams_with_vectors.json', encoding='utf-8'))['equipes']
    # Absences du jour (foot-actu.com) : joueurs absents, buteur et passeur principaux, malus Elo par équipe
    from footactu import absences_par_equipe, du_jour_frais
    du = du_jour_frais()
    par_equipe = absences_par_equipe(du)
    for t in equipes:
        a = par_equipe.get((t['ligue'], t['equipe']))
        if a:
            t['absences'] = a
    print('Absences du jour :', du['date'] if du else 'aucun relevé récent', '| équipes concernées :', len(par_equipe))
    modele = json.load(open(DATA / 'model_doc.json', encoding='utf-8'))
    donnees = {'version': version_publiee(asof), 'derniere_date': derniere.isoformat(),
               'equipes': equipes, 'stats': stats, 'modele': modele,
               'absences_date': du['date'] if du else None,
               'publie_le': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}

    sortie = DATA / 'donnees_publiees.json'
    if sortie.exists():
        ancienne = json.load(open(sortie, encoding='utf-8'))
        hist = DATA / 'historique'
        hist.mkdir(exist_ok=True)
        shutil.copy(sortie, hist / ('donnees_%s.json' % ancienne['version']))
        print('Version précédente gardée :', ancienne['version'])
    sortie.write_text(json.dumps(donnees, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print('Données écrites | version', donnees['version'], '| matchs 2026-27 :', stats['n_matchs_recent'])
    for c in comparaison:
        print('  ', c['nom'], '| test', c['erreur_test'], c['precision_test'],
              '| en cours', c['erreur_recent'], c['precision_recent'])
    subprocess.run([sys.executable, str(SRC.parent / 'standalone' / 'construire.py')], check=True)


if __name__ == '__main__':
    main()
