"""Team profiles for display, computed from the state after all played matches."""
import json, os, pickle, datetime as dt, collections
from features2 import build as build_features
from load import LEAGUES, load_all

DATA = os.path.join(os.path.dirname(__file__), '..', 'data')
ASOF = dt.date.fromisoformat(os.environ.get('LOTO_ASOF', '2026-11-02'))   # date de référence : lendemain du dernier match joué

def profile(st, league, team):
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
    # league table position by Elo
    same = sorted([(v, k[1]) for k, v in st.R.items() if k[0] == league], reverse=True)
    rank = [t for _, t in same].index(team) + 1 if team in [t for _, t in same] else None
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
    _, st = build_features(load_all())   # rebuild the state in this process (avoids pickle issues)
    teams = []
    for (lg, team), recs in st.hist.items():
        if not recs:
            continue
        last_date = recs[-1]['date']
        if (ASOF - last_date).days > 120:   # keep teams active in the last four months
            continue
        p = profile(st, lg, team)
        teams.append({'ligue': lg, 'ligue_nom': LEAGUES.get(lg, lg), 'equipe': team, **p})
    teams.sort(key=lambda t: (t['ligue'], t['equipe']))
    print('active teams', len(teams))
    for t in teams:
        if t['equipe'] in ('Paris SG', 'Bayern Munich'):
            print(json.dumps(t, ensure_ascii=False))
    s = json.dumps({'maj': ASOF.isoformat(), 'equipes': teams}, ensure_ascii=False)
    print('doc size bytes', len(s.encode('utf-8')))
    json.dump({'maj': ASOF.isoformat(), 'equipes': teams}, open(os.path.join(DATA, 'teams_profiles.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
