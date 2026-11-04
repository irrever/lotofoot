"""Team features v2, computed only from matches played BEFORE each match (no look-ahead).

Adds to v1: rest days, match load over 30 days, shots on target, corners and cards.
"""
import json, math, os, collections, pickle, datetime as dt
from load import load_all
from model import probs_from_x

DATA = os.path.join(os.path.dirname(__file__), '..', 'data')
PARAMS = json.load(open(os.path.join(DATA, 'model_state.json'), encoding='utf-8'))
K_ELO, HA, S_ELO, C_ELO = PARAMS['K'], PARAMS['HA'], PARAMS['S'], PARAMS['c']
SHRINK = 8
WIN_HA = 20      # last home (or away) matches
WIN_FORM = 5     # last matches for points per game
WIN_STAT = 10    # last matches for goals, shots, corners, cards
LOAD_DAYS = 30   # window for match load
REST_CAP = 21

FEATURE_NAMES = [
    'elo_diff',
    'dom_V', 'dom_N', 'dom_D', 'ext_V', 'ext_N', 'ext_D',
    'forme_dom', 'forme_ext',
    'buts_pour_dom', 'buts_contre_dom', 'buts_pour_ext', 'buts_contre_ext',
    'repos_dom', 'repos_ext', 'charge_dom', 'charge_ext',
    'cadres_pour_dom', 'cadres_contre_dom', 'cadres_pour_ext', 'cadres_contre_ext',
    'corners_pour_dom', 'corners_pour_ext', 'cartons_dom', 'cartons_ext',
]
PTS = {'W': 3, 'D': 1, 'L': 0}
STATS = ['gf', 'ga', 'cad', 'cad_c', 'cor', 'car']   # per-team stats averaged over the last WIN_STAT matches

def zeros_cnt():
    return [0, 0, 0]

def stat_dict():
    return {k: [0.0, 0] for k in STATS}

class State:
    def __init__(self):
        self.R = {}
        self.hist = collections.defaultdict(list)          # (league, team) -> list of records
        self.lg_home = collections.defaultdict(zeros_cnt)  # league -> home V/N/D counts
        self.lg_away = collections.defaultdict(zeros_cnt)
        self.lg_stat = collections.defaultdict(stat_dict)

    def _prior_share(self, counts):
        t = sum(counts)
        return (1/3, 1/3, 1/3) if t == 0 else (counts[0]/t, counts[1]/t, counts[2]/t)

    def _shrink_results(self, results, prior):
        n = len(results)
        v = sum(1 for r in results if r == 'W'); d = sum(1 for r in results if r == 'D'); l = n - v - d
        return ((v + SHRINK*prior[0]) / (n + SHRINK), (d + SHRINK*prior[1]) / (n + SHRINK), (l + SHRINK*prior[2]) / (n + SHRINK))

    def _stat_mean(self, league, recs, key):
        vals = [r[key] for r in recs if r[key] is not None]
        g_sum, g_n = self.lg_stat[league][key]
        prior = g_sum / g_n if g_n else 0.0
        return (sum(vals) + SHRINK * prior) / (len(vals) + SHRINK)

    def features(self, league, home, away, date, malus=(0.0, 0.0)):
        # malus : points Elo ajoutés à chaque équipe (absences du jour) ; (0, 0) pour la prévision de base
        kh, ka = (league, home), (league, away)
        Rh, Ra = self.R.get(kh, 1500.0) + malus[0], self.R.get(ka, 1500.0) + malus[1]
        hh, ha_ = self.hist[kh], self.hist[ka]
        dom = [r for r in hh if r['home']][-WIN_HA:]
        ext = [r for r in ha_ if not r['home']][-WIN_HA:]
        dW, dD, dL = self._shrink_results([r['res'] for r in dom], self._prior_share(self.lg_home[league]))
        eW, eD, eL = self._shrink_results([r['res'] for r in ext], self._prior_share(self.lg_away[league]))
        fh = hh[-WIN_FORM:]; fa = ha_[-WIN_FORM:]
        forme_h = sum(PTS[r['res']] for r in fh) / len(fh) if fh else 1.0
        forme_a = sum(PTS[r['res']] for r in fa) / len(fa) if fa else 1.0
        lh = hh[-WIN_STAT:]; la = ha_[-WIN_STAT:]
        def rest(hist):
            if not hist: return float(REST_CAP)
            return float(min(REST_CAP, (date - hist[-1]['date']).days))
        def load_n(hist):
            return float(sum(1 for r in hist if 0 < (date - r['date']).days <= LOAD_DAYS))
        return [
            (Rh - Ra) / 100.0,
            dW, dD, dL, eW, eD, eL,
            forme_h, forme_a,
            self._stat_mean(league, lh, 'gf'), self._stat_mean(league, lh, 'ga'),
            self._stat_mean(league, la, 'gf'), self._stat_mean(league, la, 'ga'),
            rest(hh), rest(ha_), load_n(hh), load_n(ha_),
            self._stat_mean(league, lh, 'cad'), self._stat_mean(league, lh, 'cad_c'),
            self._stat_mean(league, la, 'cad'), self._stat_mean(league, la, 'cad_c'),
            self._stat_mean(league, lh, 'cor'), self._stat_mean(league, la, 'cor'),
            self._stat_mean(league, lh, 'car'), self._stat_mean(league, la, 'car'),
        ]

    def update(self, league, home, away, date, row, res):
        kh, ka = (league, home), (league, away)
        Rh, Ra = self.R.get(kh, 1500.0), self.R.get(ka, 1500.0)
        ph, pd, pa = probs_from_x((Rh + HA - Ra) / S_ELO, C_ELO)
        delta = K_ELO * ({'H': 1.0, 'D': 0.5, 'A': 0.0}[res] - (ph + 0.5*pd))
        self.R[kh] = Rh + delta; self.R[ka] = Ra - delta
        hg, ag = int(row['hg']), int(row['ag'])
        res_h = {'H': 'W', 'D': 'D', 'A': 'L'}[res]; res_a = {'H': 'L', 'D': 'D', 'A': 'W'}[res]
        def cards(y, r):
            if y is None and r is None: return None
            return float((y or 0) + (r or 0))
        h_cards = cards(row['hy'], row['hr']); a_cards = cards(row['ay'], row['ar'])
        rec_h = {'home': True, 'date': date, 'res': res_h, 'gf': float(hg), 'ga': float(ag),
                 'cad': None if row['hst'] is None else float(row['hst']),
                 'cad_c': None if row['ast'] is None else float(row['ast']),
                 'cor': None if row['hc'] is None else float(row['hc']),
                 'car': h_cards}
        rec_a = {'home': False, 'date': date, 'res': res_a, 'gf': float(ag), 'ga': float(hg),
                 'cad': None if row['ast'] is None else float(row['ast']),
                 'cad_c': None if row['hst'] is None else float(row['hst']),
                 'cor': None if row['ac'] is None else float(row['ac']),
                 'car': a_cards}
        self.hist[kh].append(rec_h); self.hist[ka].append(rec_a)
        self.lg_home[league][{'W': 0, 'D': 1, 'L': 2}[res_h]] += 1
        self.lg_away[league][{'W': 0, 'D': 1, 'L': 2}[res_a]] += 1
        for rec in (rec_h, rec_a):
            for key in ['gf', 'ga', 'cad', 'cad_c', 'cor', 'car']:
                if rec[key] is not None:
                    self.lg_stat[league][key][0] += rec[key]
                    self.lg_stat[league][key][1] += 1

def build(rows):
    st = State()
    out = []
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and rows[j]['date'] == rows[i]['date']:
            j += 1
        day = [r for r in rows[i:j] if r['result'] in ('H', 'D', 'A') and r['hg'] not in (None, '') and r['ag'] not in (None, '')]
        for r in day:
            x = st.features(r['league'], r['home'], r['away'], r['date'])
            out.append({'season': r['season'], 'league': r['league'], 'date': str(r['date']), 'home': r['home'], 'away': r['away'],
                        'y': r['result'], 'x': x})
        for r in day:
            st.update(r['league'], r['home'], r['away'], r['date'], r, r['result'])
        i = j
    return out, st

if __name__ == '__main__':
    rows = load_all()
    data, st = build(rows)
    print('rows', len(data), 'features', len(FEATURE_NAMES), 'teams', len(st.R))
    assert all(len(d['x']) == len(FEATURE_NAMES) for d in data)
    json.dump({'features': FEATURE_NAMES, 'rows': data}, open(os.path.join(DATA, 'features2_dataset.json'), 'w', encoding='utf-8'))
    pickle.dump(st, open(os.path.join(DATA, 'state2.pkl'), 'wb'))
    print('saved')
