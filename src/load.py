import csv, glob, os, datetime as dt
RAW = os.path.join(os.path.dirname(__file__), '..', 'data', 'raw')
LEAGUES = {
    'F1': 'France L1', 'F2': 'France L2',
    'E0': 'Angleterre PL', 'E1': 'Angleterre Championship',
    'SP1': 'Espagne Liga', 'SP2': 'Espagne Liga 2',
    'I1': 'Italie Serie A', 'I2': 'Italie Serie B',
    'D1': 'Allemagne Bundesliga', 'D2': 'Allemagne 2. Bundesliga',
    'N1': 'Pays-Bas Eredivisie', 'P1': 'Portugal Liga', 'B1': 'Belgique Pro League',
    'T1': 'Turquie Super Lig', 'SC0': 'Écosse Premiership', 'G1': 'Grèce Super League',
}

def parse_date(s):
    s = s.strip()
    for fmt in ('%d/%m/%Y', '%d/%m/%y'):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

def inum(x):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None

def fnum(x):
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None

def load_all():
    rows = []
    for path in sorted(glob.glob(os.path.join(RAW, '*.csv'))):
        base = os.path.basename(path)
        season, div = base.split('_', 1)[0], base.split('_', 1)[1][:-4]
        with open(path, encoding='utf-8-sig', errors='ignore') as fh:
            for r in csv.DictReader(fh):
                d = parse_date(r.get('Date', ''))
                if d is None or not r.get('HomeTeam'):
                    continue
                res = (r.get('FTR') or '').strip() or None
                rows.append({
                    'season': season, 'league': div, 'date': d,
                    'home': r['HomeTeam'].strip(), 'away': r['AwayTeam'].strip(),
                    'result': res, 'hg': r.get('FTHG'), 'ag': r.get('FTAG'),
                    'hs': inum(r.get('HS')), 'as_': inum(r.get('AS')), 'hst': inum(r.get('HST')), 'ast': inum(r.get('AST')),
                    'hc': inum(r.get('HC')), 'ac': inum(r.get('AC')), 'hy': inum(r.get('HY')), 'ay': inum(r.get('AY')),
                    'hr': inum(r.get('HR')), 'ar': inum(r.get('AR')),
                })
    rows.sort(key=lambda x: (x['date'], x['league']))
    return rows

if __name__ == '__main__':
    rows = load_all()
    played = [r for r in rows if r['result'] in ('H', 'D', 'A')]
    fixtures = [r for r in rows if r['result'] is None]
    print('total', len(rows), 'played', len(played), 'fixtures', len(fixtures))
    print('last played date', max(r['date'] for r in played))
    print('next fixtures sample dates', sorted({r['date'] for r in fixtures})[:5])
