"""Team profiles for display, computed from the state after all played matches."""
import json, os, pickle, datetime as dt, collections
from features2 import build as build_features, equipes_de_la_saison
from load import LEAGUES, load_all

DATA = os.path.join(os.path.dirname(__file__), '..', 'data')
ASOF = dt.date.fromisoformat(os.environ.get('LOTO_ASOF', '2026-11-02'))   # date de référence : lendemain du dernier match joué

def rang_elo(R, league, team, actifs):
    """Rang d’une équipe par Elo, parmi les équipes actives (saison en cours) de son championnat."""
    classement = sorted([(v, k[1]) for k, v in R.items() if k[0] == league and k in actifs], reverse=True)
    noms = [t for _, t in classement]
    return noms.index(team) + 1 if team in noms else None


def profile(st, league, team, actifs):
    recs = st.hist[(league, team)]
    if not recs:
        return None
    dom = [r for r in recs if r['home']][-20:]
    ext = [r for r in recs if not r['home']][-20:]
    last10 = recs[-10:]
    def counts(lst):
        v = sum(1 for r in lst if r['res'] == 'W'); n_ = sum(1 for r in lst if r['res'] == 'D')
        return {'V': v, 'N': n_, 'D': len(lst) - v - n_, 'n': len(lst)}
    def avg(lst, key):
        vals = [r[key] for r in lst if r[key] is not None]
        return round(sum(vals) / len(vals), 2) if vals else None
    last5 = recs[-5:]
    days = (ASOF - recs[-1]['date']).days
    load = sum(1 for r in recs if 0 <= (ASOF - r['date']).days <= 30)
    rank = rang_elo(st.R, league, team, actifs)
    return {
        'domicile': counts(dom), 'exterieur': counts(ext),
        'forme': ''.join({'W': 'V', 'D': 'N', 'L': 'D'}[r['res']] for r in last5),
        'buts_pour': avg(last10, 'gf'), 'buts_contre': avg(last10, 'ga'),
        'tirs_cadres_pour': avg(last10, 'cad'), 'tirs_cadres_contre': avg(last10, 'cad_c'),
        'corners_pour': avg(last10, 'cor'), 'cartons': avg(last10, 'car'),
        'jours_depuis_dernier_match': days, 'matchs_30_jours': load,
        'elo': round(st.R.get((league, team), 1500.0)), 'rang_elo_dans_le_championnat': rank,
    }

if __name__ == '__main__':
    rows = load_all()
    _, st = build_features(rows)   # rebuild the state in this process (avoids pickle issues)
    actifs = equipes_de_la_saison(rows)
    teams = []
    for (lg, team), recs in st.hist.items():
        if not recs:
            continue
        last_date = recs[-1]['date']
        if (ASOF - last_date).days > 120:   # keep teams active in the last four months
            continue
        p = profile(st, lg, team, actifs)
        if p['rang_elo_dans_le_championnat'] is None:   # ancienne équipe du championnat : hors saison en cours
            continue
        teams.append({'ligue': lg, 'ligue_nom': LEAGUES.get(lg, lg), 'equipe': team, **p})
    teams.sort(key=lambda t: (t['ligue'], t['equipe']))
    print('active teams', len(teams))
    for t in teams:
        if t['equipe'] in ('Paris SG', 'Bayern Munich'):
            print(json.dumps(t, ensure_ascii=False))
    s = json.dumps({'maj': ASOF.isoformat(), 'equipes': teams}, ensure_ascii=False)
    print('doc size bytes', len(s.encode('utf-8')))
    json.dump({'maj': ASOF.isoformat(), 'equipes': teams}, open(os.path.join(DATA, 'teams_profiles.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
