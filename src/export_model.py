"""Export the team-statistics model and per-team feature vectors for in-browser prediction."""
import json, os, warnings, datetime as dt
import numpy as np
warnings.filterwarnings('ignore')
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from features2 import build as build_features, FEATURE_NAMES, WIN_HA, WIN_FORM, WIN_STAT, LOAD_DAYS, REST_CAP, PTS
from load import load_all, LEAGUES
from teams import ASOF

DATA = os.path.join(os.path.dirname(__file__), '..', 'data')

def team_vector(st, league, team):
    recs = st.hist[(league, team)]
    if not recs:
        return None
    dom = [r for r in recs if r['home']][-WIN_HA:]
    ext = [r for r in recs if not r['home']][-WIN_HA:]
    dW, dD, dL = st._shrink_results([r['res'] for r in dom], st._prior_share(st.lg_home[league]))
    eW, eD, eL = st._shrink_results([r['res'] for r in ext], st._prior_share(st.lg_away[league]))
    f = recs[-WIN_FORM:]
    forme = sum(PTS[r['res']] for r in f) / len(f) if f else 1.0
    last10 = recs[-WIN_STAT:]
    rest = float(min(REST_CAP, (ASOF - recs[-1]['date']).days))
    load = float(sum(1 for r in recs if 0 < (ASOF - r['date']).days <= LOAD_DAYS))
    return {
        'dW': dW, 'dD': dD, 'dL': dL, 'eW': eW, 'eD': eD, 'eL': eL,
        'forme': forme,
        'gf': st._stat_mean(league, last10, 'gf'), 'ga': st._stat_mean(league, last10, 'ga'),
        'rest': rest, 'load': load,
        'cadF': st._stat_mean(league, last10, 'cad'), 'cadA': st._stat_mean(league, last10, 'cad_c'),
        'cor': st._stat_mean(league, last10, 'cor'), 'car': st._stat_mean(league, last10, 'car'),
        'elo': st.R.get((league, team), 1500.0),
    }

def pair_features(h, a):
    return [(h['elo'] - a['elo']) / 100.0,
            h['dW'], h['dD'], h['dL'], a['eW'], a['eD'], a['eL'],
            h['forme'], a['forme'],
            h['gf'], h['ga'], a['gf'], a['ga'],
            h['rest'], a['rest'], h['load'], a['load'],
            h['cadF'], h['cadA'], a['cadF'], a['cadA'],
            h['cor'], a['cor'], h['car'], a['car']]

if __name__ == '__main__':
    rows = load_all()
    data, st = build_features(rows)
    X = np.array([d['x'] for d in data]); y = [d['y'] for d in data]
    sc = StandardScaler().fit(X)
    model = LogisticRegression(C=0.5, max_iter=5000).fit(sc.transform(X), y)
    cls = list(model.classes_)
    coef = {c: [float(v) for v in model.coef_[cls.index(c)]] for c in ['H', 'D', 'A']}
    inter = {c: float(model.intercept_[cls.index(c)]) for c in ['H', 'D', 'A']}
    model_doc = {'maj': ASOF.isoformat(), 'variables': FEATURE_NAMES,
                 'moyenne': [float(v) for v in sc.mean_], 'echelle': [float(v) for v in sc.scale_],
                 'coef': coef, 'ordonnee': inter}
    # Team vectors for the active teams (same selection as the team profiles)
    teams = json.load(open(os.path.join(DATA, 'teams_profiles.json'), encoding='utf-8'))['equipes']
    for t in teams:
        v = team_vector(st, t['ligue'], t['equipe'])
        t['vec'] = {k: (round(val, 6) if isinstance(val, float) else val) for k, val in v.items()}
    # Consistency check: pair features via vectors must equal features2 for the same pair (date = ASOF)
    checks = []
    idx = {(t['ligue'], t['equipe']): t for t in teams}
    for (lg, h, a) in [('F1', 'Paris SG', 'Marseille'), ('D1', 'Bayern Munich', 'Dortmund'), ('E0', 'Arsenal', 'Man City')]:
        if (lg, h) in idx and (lg, a) in idx:
            x_direct = st.features(lg, h, a, ASOF)
            x_vec = pair_features(st.hist and team_vector(st, lg, h), team_vector(st, lg, a))
            diff = max(abs(p - q) for p, q in zip(x_direct, x_vec))
            checks.append((h, a, round(diff, 10)))
            p_direct = model.predict_proba(sc.transform(np.array([x_direct])))[0]
            p_vec = model.predict_proba(sc.transform(np.array([x_vec])))[0]
            checks.append(('proba', [round(float(v), 4) for v in p_direct], [round(float(v), 4) for v in p_vec]))
    print('checks:', checks)
    json.dump(model_doc, open(os.path.join(DATA, 'model_doc.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    teams_doc = {'maj': ASOF.isoformat(), 'equipes': teams}
    s = json.dumps(teams_doc, ensure_ascii=False)
    print('teams', len(teams), 'bytes', len(s.encode('utf-8')))
    json.dump(teams_doc, open(os.path.join(DATA, 'teams_with_vectors.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    print('model coef sample H:', [round(v, 3) for v in coef['H'][:5]])
