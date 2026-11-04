"""Journal des prévisions : enregistre la probabilité de chaque match à venir, avant son déroulement.

Les rencontres à venir viennent de la liste football-data (fixtures.csv). Seuls les codes de division,
les dates, les heures et les noms d’équipes sont lus ; les colonnes de cotes du fichier ne sont ni lues
ni enregistrées. Une prévision n’est écrite qu’une fois, à la première exécution où le match apparaît.
Le fichier data/journal/predictions.jsonl ne reçoit que des lignes ajoutées en fin de fichier : aucune
prévision ancienne n’est modifiée. Le bilan (bilan.py) compare ensuite ces prévisions aux résultats.

Chaque prévision garde la probabilité du modèle (« proba ») et, pour les matchs proches, celle qui tient
compte des absences du jour (« proba_absences », avec le malus Elo appliqué à chaque équipe).

Usage : python3 journal.py [--jours 14]
"""
import argparse, csv, datetime as dt, io, json, os, ssl, sys, urllib.request, warnings
import numpy as np
warnings.filterwarnings('ignore')
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from features2 import build
from load import load_all, LEAGUES
from footactu import absences_par_equipe, du_jour_frais

HERE = os.path.dirname(os.path.abspath(__file__))
JOURNAL = os.path.join(HERE, '..', 'data', 'journal', 'predictions.jsonl')
FIXTURES_URL = 'https://www.football-data.co.uk/fixtures.csv'
CA = '/root/.ccr/ca-bundle.crt'
ORDRE = ['H', 'D', 'A']
ETIQ = {'H': '1', 'D': 'N', 'A': '2'}
# Les absences du jour ne sont prises en compte que pour les matchs des jours qui suivent
HORIZON_ABSENCES = 3
# Noms de la liste des rencontres -> noms des résultats (même source, orthographe différente)
ALIAS_LISTE = {'Sheffield Utd': 'Sheffield United', 'KV Mechelen': 'Mechelen'}


def rencontres_a_venir():
    """Lit la liste des rencontres à venir, sans conserver les colonnes de cotes."""
    ctx = ssl.create_default_context(cafile=CA) if os.path.exists(CA) else ssl.create_default_context()
    req = urllib.request.Request(FIXTURES_URL, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as rep:
        texte = rep.read().decode('utf-8-sig', errors='ignore')
    if not texte.startswith('Div') and 'HomeTeam' not in texte[:2000]:
        raise RuntimeError('réponse inattendue de la liste des rencontres')
    out = []
    for r in csv.DictReader(io.StringIO(texte)):
        if not r.get('Div') or not r.get('HomeTeam'):
            continue
        out.append({'ligue': r['Div'].strip(), 'date': dt.datetime.strptime(r['Date'].strip(), '%d/%m/%Y').date(),
                    'heure_source': (r.get('Time') or '').strip(),
                    'domicile': ALIAS_LISTE.get(r['HomeTeam'].strip(), r['HomeTeam'].strip()),
                    'exterieur': ALIAS_LISTE.get(r['AwayTeam'].strip(), r['AwayTeam'].strip())})
    return out


def principal(jours):
    rows = load_all()
    jouees = [r for r in rows if r['result'] in ORDRE and r['hg'] not in (None, '') and r['ag'] not in (None, '')]
    reference = max(r['date'] for r in jouees) + dt.timedelta(days=1)
    saison_courante = max(r['season'] for r in rows)
    data, st = build(rows)
    X = np.array([d['x'] for d in data], dtype=float)
    y = [d['y'] for d in data]
    sc = StandardScaler().fit(X)
    lr = LogisticRegression(C=0.5, max_iter=5000).fit(sc.transform(X), y)
    cl = list(lr.classes_)
    deja = set()
    if os.path.exists(JOURNAL):
        with open(JOURNAL, encoding='utf-8') as f:
            deja = {json.loads(l)['id'] for l in f if l.strip()}
    absences = absences_par_equipe(du_jour_frais())
    aujourdhui = dt.date.today()
    fin = reference + dt.timedelta(days=jours)
    try:
        liste = rencontres_a_venir()
    except Exception as e:
        print('liste des rencontres indisponible :', e)
        sys.exit(1)
    a_venir = sorted([m for m in liste if m['ligue'] in LEAGUES and reference <= m['date'] <= fin],
                     key=lambda m: (m['date'], m['ligue'], m['domicile']))
    maintenant = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    nouvelles, inconnues = [], []
    for m in a_venir:
        ident = f"{m['ligue']}|{m['date'].isoformat()}|{m['domicile']}|{m['exterieur']}"
        if ident in deja:
            continue
        if (m['ligue'], m['domicile']) not in st.R or (m['ligue'], m['exterieur']) not in st.R:
            inconnues.append(f"{m['domicile']} – {m['exterieur']} ({m['ligue']})")
            continue
        deja.add(ident)
        x = st.features(m['ligue'], m['domicile'], m['exterieur'], m['date'])
        p = lr.predict_proba(sc.transform(np.array([x], dtype=float)))[0]
        pr = {c: float(p[cl.index(c)]) for c in ORDRE}
        # Absences du jour : prises en compte pour les matchs proches seulement ; « proba » reste la prévision de base
        proche = 0 <= (m['date'] - aujourdhui).days <= HORIZON_ABSENCES
        mal_d = absences.get((m['ligue'], m['domicile']), {}).get('malus', 0) if proche else 0
        mal_e = absences.get((m['ligue'], m['exterieur']), {}).get('malus', 0) if proche else 0
        xa = st.features(m['ligue'], m['domicile'], m['exterieur'], m['date'], malus=(mal_d, mal_e))
        pa = lr.predict_proba(sc.transform(np.array([xa], dtype=float)))[0]
        pra = {c: float(pa[cl.index(c)]) for c in ORDRE}
        nouvelles.append({'id': ident, 'enregistree_le': maintenant, 'reference_donnees': reference.isoformat(),
                          'saison': saison_courante,
                          'ligue': m['ligue'], 'date': m['date'].isoformat(), 'heure_source': m['heure_source'],
                          'domicile': m['domicile'], 'exterieur': m['exterieur'],
                          'proba': {ETIQ[c]: round(pr[c], 6) for c in ORDRE},
                          'pronostic': ETIQ[max(ORDRE, key=lambda c: pr[c])],
                          'proba_absences': {ETIQ[c]: round(pra[c], 6) for c in ORDRE},
                          'malus': {'domicile': mal_d, 'exterieur': mal_e}})
    os.makedirs(os.path.dirname(JOURNAL), exist_ok=True)
    with open(JOURNAL, 'a', encoding='utf-8') as f:
        for e in nouvelles:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    avec_absences = sum(1 for e in nouvelles if e['malus']['domicile'] or e['malus']['exterieur'])
    print(f'rencontres de nos championnats du {reference.isoformat()} au {fin.isoformat()} : {len(a_venir)} | '
          f'nouvelles prévisions enregistrées : {len(nouvelles)} | avec absences du jour : {avec_absences}')
    if inconnues:
        print('équipes absentes des données, non enregistrées :', ' ; '.join(inconnues))
    for e in nouvelles:
        pr = e['proba']
        print(f"  {e['date']} {e['ligue']:4s} {e['domicile']} – {e['exterieur']} : "
              f"1 {pr['1'] * 100:.0f} %  N {pr['N'] * 100:.0f} %  2 {pr['2'] * 100:.0f} %  -> {e['pronostic']}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--jours', type=int, default=14, help='horizon des matchs enregistrés, en jours')
    principal(ap.parse_args().jours)
