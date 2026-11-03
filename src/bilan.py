"""Bilan d’observation : compare les probabilités du modèle aux résultats joués, explique les écarts
et suit la progression journée après journée.

Méthode, sans aucune cote : pour chaque journée de matchs, le modèle est réentraîné sur les seuls
matchs joués avant cette journée, puis prédit les matchs de la journée (« walk-forward »).
Un pronostic ne voit donc jamais le résultat qu’il doit prévoir.

Usage : python3 bilan.py [--saison 2627]
Sorties dans data/bilan/ : bilan-<saison>-<date des données>.md et .json, et historique.json.
"""
import argparse, datetime as dt, json, math, os, warnings
import numpy as np
warnings.filterwarnings('ignore')
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from features2 import build, FEATURE_NAMES
from load import load_all, LEAGUES

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
BILAN = os.path.join(DATA, 'bilan')
JOURNAL = os.path.join(DATA, 'journal', 'predictions.jsonl')
ORDRE = ['H', 'D', 'A']
ETIQ = {'H': '1', 'D': 'N', 'A': '2'}
NOM_RESULTAT = {'H': 'victoire à domicile (1)', 'D': 'match nul (N)', 'A': 'victoire à l’extérieur (2)'}
BORNES = [0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 1.0001]
SEUIL_ECART = 0.25
MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
LIBELLES = {
    'elo_diff': 'écart de niveau Elo', 'dom_V': 'victoires à domicile (équipe à domicile)',
    'dom_N': 'nuls à domicile (équipe à domicile)', 'dom_D': 'défaites à domicile (équipe à domicile)',
    'ext_V': 'victoires à l’extérieur (visiteur)', 'ext_N': 'nuls à l’extérieur (visiteur)',
    'ext_D': 'défaites à l’extérieur (visiteur)', 'forme_dom': 'forme sur 5 matchs (domicile)',
    'forme_ext': 'forme sur 5 matchs (visiteur)', 'buts_pour_dom': 'buts marqués (domicile)',
    'buts_contre_dom': 'buts encaissés (domicile)', 'buts_pour_ext': 'buts marqués (visiteur)',
    'buts_contre_ext': 'buts encaissés (visiteur)', 'repos_dom': 'repos avant le match (domicile)',
    'repos_ext': 'repos avant le match (visiteur)', 'charge_dom': 'matchs sur 30 jours (domicile)',
    'charge_ext': 'matchs sur 30 jours (visiteur)', 'cadres_pour_dom': 'tirs cadrés obtenus (domicile)',
    'cadres_contre_dom': 'tirs cadrés concédés (domicile)', 'cadres_pour_ext': 'tirs cadrés obtenus (visiteur)',
    'cadres_contre_ext': 'tirs cadrés concédés (visiteur)', 'corners_pour_dom': 'corners obtenus (domicile)',
    'corners_pour_ext': 'corners obtenus (visiteur)', 'cartons_dom': 'cartons reçus (domicile)',
    'cartons_ext': 'cartons reçus (visiteur)',
}


def nb(x, d=2):
    return f'{x:.{d}f}'.replace('.', ',')


def pc(x, d=0):
    return f'{x * 100:.{d}f} %'.replace('.', ',')


def fr(d):
    if isinstance(d, str):
        d = dt.date.fromisoformat(d)
    return f'{d.day} {MOIS[d.month - 1]} {d.year}'


def lundi(d):
    return d - dt.timedelta(days=d.weekday())


def valeur(nom, v):
    if nom == 'elo_diff':
        if v >= 0:
            return f'avantage Elo à domicile de {v * 100:.0f} points'
        return f'avantage Elo à l’extérieur de {-v * 100:.0f} points'
    if nom.startswith(('dom_', 'ext_')):
        return pc(v)
    if nom.startswith('forme'):
        return f'{nb(v)} point(s) par match'
    if nom.startswith('repos'):
        return f'{v:.0f} jours'
    if nom.startswith('charge'):
        return f'{v:.0f} matchs sur 30 jours'
    return f'{nb(v)} par match'


# ---------------------------------------------------------------- modèle

def ajuste(X, y, colonnes=None):
    """Même modèle que la publication : standardisation puis régression logistique multinomiale (C = 0,5)."""
    Xa = np.asarray(X, dtype=float)
    if colonnes is not None:
        Xa = Xa[:, colonnes]
    sc = StandardScaler().fit(Xa)
    lr = LogisticRegression(C=0.5, max_iter=5000).fit(sc.transform(Xa), y)
    return {'sc': sc, 'lr': lr, 'colonnes': colonnes}


def proba(m, x):
    xa = np.asarray([x], dtype=float)
    if m['colonnes'] is not None:
        xa = xa[:, m['colonnes']]
    p = m['lr'].predict_proba(m['sc'].transform(xa))[0]
    cl = list(m['lr'].classes_)
    return {c: float(p[cl.index(c)]) for c in ORDRE}


def contributions(m, x, prevu, reel):
    """Poids de chaque variable dans l’écart entre le résultat prévu et le résultat réel.
    Positif : la variable pousse vers le résultat prévu plutôt que vers le résultat réel."""
    cl = list(m['lr'].classes_)
    z = m['sc'].transform(np.asarray([x], dtype=float))[0]
    return ((m['lr'].coef_[cl.index(prevu)] - m['lr'].coef_[cl.index(reel)]) * z).tolist()


def evalue(data, saison):
    """Walk-forward : chaque journée est prédite avec un modèle entraîné sur les matchs antérieurs."""
    for d in data:
        d['_jour'] = dt.date.fromisoformat(d['date'])
    cible = [d for d in data if d['season'] == saison]
    recs = []
    for jour in sorted({d['_jour'] for d in cible}):
        train = [d for d in data if d['_jour'] < jour]
        Xtr = [d['x'] for d in train]
        ytr = [d['y'] for d in train]
        plein = ajuste(Xtr, ytr)
        elo = ajuste(Xtr, ytr, colonnes=[0])          # niveau Elo seul : première variable
        base = {c: ytr.count(c) / len(ytr) for c in ORDRE}  # référence : fréquences observées
        for d in cible:
            if d['_jour'] != jour:
                continue
            p = proba(plein, d['x'])
            pe = proba(elo, d['x'])
            prevu = max(ORDRE, key=lambda c: p[c])
            reel = d['y']
            recs.append({
                'date': d['date'], 'jour': jour, 'semaine': lundi(jour).isoformat(),
                'ligue': d['league'], 'domicile': d['home'], 'exterieur': d['away'],
                'reel': reel, 'pred': prevu, 'p': p, 'x': d['x'],
                'ecart': contributions(plein, d['x'], prevu, reel),
                'z': plein['sc'].transform(np.asarray([d['x']], dtype=float))[0].tolist(),
                'll': -math.log(max(p[reel], 1e-12)), 'll_elo': -math.log(max(pe[reel], 1e-12)),
                'll_base': -math.log(max(base[reel], 1e-12)), 'juste': prevu == reel,
                'brier': sum((p[c] - (1.0 if c == reel else 0.0)) ** 2 for c in ORDRE),
                'p_elo': pe, 'p_base': base,
            })
    return recs


# ---------------------------------------------------------------- métriques

def differences(rs, a, b):
    """Écart moyen de log-loss (b − a) : positif quand a est meilleur, avec intervalle à 95 %."""
    ecarts = [r[b] - r[a] for r in rs]
    n = len(ecarts)
    m = sum(ecarts) / n
    if n < 2:
        return {'moyenne': m, 'bas': None, 'haut': None, 'matchs': n}
    s = (sum((e - m) ** 2 for e in ecarts) / (n - 1)) ** 0.5
    marge = 1.96 * s / n ** 0.5
    return {'moyenne': m, 'bas': m - marge, 'haut': m + marge, 'matchs': n}


def resume(rs):
    if not rs:
        return None
    n = len(rs)

    def moy(cle):
        return sum(r[cle] for r in rs) / n
    ll, ll_e, ll_b = moy('ll'), moy('ll_elo'), moy('ll_base')
    return {
        'matchs': n, 'precision': moy('juste'), 'brier': moy('brier'),
        'log_loss': ll, 'log_loss_elo': ll_e, 'log_loss_reference': ll_b,
        'competence': 1 - ll / ll_b, 'competence_elo': 1 - ll_e / ll_b,
        'ecart_reference': differences(rs, 'll', 'll_base'), 'ecart_elo': differences(rs, 'll', 'll_elo'),
        'prevue': {c: sum(r['p'][c] for r in rs) / n for c in ORDRE},
        'observee': {c: sum(1 for r in rs if r['reel'] == c) / n for c in ORDRE},
    }


def calibration(rs):
    out = []
    for c in ORDRE:
        for lo, hi in zip(BORNES, BORNES[1:]):
            sel = [r for r in rs if lo <= r['p'][c] < hi]
            if sel:
                out.append({'resultat': c, 'de': lo, 'a': min(hi, 1.0), 'matchs': len(sel),
                            'prevue': sum(r['p'][c] for r in sel) / len(sel),
                            'observee': sum(1 for r in sel if r['reel'] == c) / len(sel)})
    return out


def par_semaine(recs):
    out = []
    for s in sorted({r['semaine'] for r in recs}):
        une = resume([r for r in recs if r['semaine'] == s])
        cum = resume([r for r in recs if r['semaine'] <= s])
        out.append({'semaine': s, 'matchs': une['matchs'], 'precision': une['precision'],
                    'log_loss': une['log_loss'], 'log_loss_cumule': cum['log_loss'],
                    'log_loss_reference_cumule': cum['log_loss_reference'], 'log_loss_elo_cumule': cum['log_loss_elo'],
                    'precision_cumulee': cum['precision'], 'competence_cumulee': cum['competence']})
    return out


def par_ligue(recs):
    out = []
    for lg in sorted({r['ligue'] for r in recs}):
        out.append({'ligue': lg, 'nom': LEAGUES.get(lg, lg), **resume([r for r in recs if r['ligue'] == lg])})
    return sorted(out, key=lambda x: -x['matchs'])


# ---------------------------------------------------------------- explication des écarts

def faits_match(brut):
    if brut is None:
        return ['statistiques du match indisponibles']
    f = [f"score {brut['hg']}–{brut['ag']}"]
    if brut['hst'] is not None and brut['ast'] is not None:
        f.append(f"tirs cadrés {brut['hst']}–{brut['ast']}")
    if brut['hs'] is not None and brut['as_'] is not None:
        f.append(f"tirs {brut['hs']}–{brut['as_']}")
    if brut['hc'] is not None and brut['ac'] is not None:
        f.append(f"corners {brut['hc']}–{brut['ac']}")
    if brut['hr']:
        f.append(f"expulsion(s) à domicile : {brut['hr']}")
    if brut['ar']:
        f.append(f"expulsion(s) à l’extérieur : {brut['ar']}")
    return f


def lecture(r):
    brut = r['brut']
    if brut is None or brut['hst'] is None or brut['ast'] is None:
        return 'statistiques de tirs insuffisantes pour trancher : écart probablement lié à la variance.'
    total = max(1, brut['hst'] + brut['ast'])
    part = {'H': brut['hst'] / total, 'A': brut['ast'] / total}
    prevu, reel = r['pred'], r['reel']
    if prevu in part and reel != prevu and part[prevu] >= 0.6:
        return ('le favori a eu la plus grande part des tirs cadrés, sans que cela se traduise au score : '
                'efficacité insuffisante ou réussite adverse.')
    if reel in part and reel != prevu and part[reel] >= 0.6:
        return ('le résultat réel suit la domination en tirs cadrés, que le modèle n’avait pas anticipée : '
                'ses variables (Elo, forme, résultats récents) ont davantage pesé que les tirs de ce match.')
    if reel in part and reel != prevu and part[reel] < 0.4:
        return ('le vainqueur a tiré moins souvent cadré que son adversaire : résultat lié surtout à '
                'l’efficacité ou à la chance.')
    return 'les statistiques de tirs ne désignent pas de cause nette : l’écart relève surtout de la variance d’un match.'


def points_attention_donnees(cal):
    """Tranches de calibration où le résultat observé s’écarte du prévu de plus de deux erreurs-types."""
    sortie = []
    for c in cal:
        pr, n = c['prevue'], c['matchs']
        se = (pr * (1 - pr) / n) ** 0.5 if n else 0
        if n >= 30 and se > 0 and abs(c['observee'] - pr) / se >= 2:
            sortie.append(dict(c, sens='sous-estime' if c['observee'] > pr else 'surestime'))
    return sortie


def facteurs_recurrents_donnees(recs):
    n, items = facteurs_recurrents(recs)
    return {'ecarts': n, 'items': [[LIBELLES[nom], k] for nom, k in items]}


def journal_entrees(index):
    """Chaque prévision du journal, avec son résultat (1, N ou 2) lorsqu’il est connu."""
    if not os.path.exists(JOURNAL):
        return []
    with open(JOURNAL, encoding='utf-8') as f:
        entrees = [json.loads(l) for l in f if l.strip()]
    sortie = []
    for e in entrees:
        brut = index.get((e['ligue'], e['date'], e['domicile'], e['exterieur']))
        reel = ETIQ[brut['result']] if brut is not None else None
        sortie.append({'date': e['date'], 'ligue': e['ligue'], 'nom_ligue': LEAGUES.get(e['ligue'], e['ligue']),
                       'domicile': e['domicile'], 'exterieur': e['exterieur'], 'proba': e['proba'],
                       'pronostic': e['pronostic'], 'reel': reel,
                       'juste': None if reel is None else reel == e['pronostic']})
    return sorted(sortie, key=lambda x: (x['date'], x['ligue'], x['domicile']))


def facteur(nom, v, z):
    txt = f"{LIBELLES[nom]} : {valeur(nom, v)}"
    if nom != 'elo_diff':
        txt += ', ' + ('au-dessus de la moyenne' if z > 0 else 'sous la moyenne')
    return txt


def facteurs_recurrents(recs):
    """Variables qui ont le plus poussé vers le prévu, sur l’ensemble des écarts marquants."""
    ecarts = [r for r in recs if r['p'][r['reel']] < SEUIL_ECART]
    compte = {}
    for r in ecarts:
        top = sorted([j for j in range(len(FEATURE_NAMES)) if r['ecart'][j] > 0], key=lambda j: -r['ecart'][j])[:3]
        for j in top:
            compte[FEATURE_NAMES[j]] = compte.get(FEATURE_NAMES[j], 0) + 1
    return len(ecarts), sorted(compte.items(), key=lambda kv: -kv[1])[:6]


def points_attention(cal):
    """Tranches où le résultat observé s’écarte du prévu de plus de deux erreurs-types."""
    lignes = []
    for c in cal:
        p, n = c['prevue'], c['matchs']
        se = (p * (1 - p) / n) ** 0.5 if n else 0
        if n >= 30 and se > 0 and abs(c['observee'] - p) / se >= 2:
            sens = 'sous-estime' if c['observee'] > p else 'surestime'
            lignes.append(f"- {NOM_RESULTAT[c['resultat']]} annoncé entre {pc(c['de'])} et {pc(min(c['a'], 1.0))} : "
                          f"observé {pc(c['observee'], 1)} contre {pc(p, 1)} prévu, sur {n} matchs. "
                          f"Le modèle {sens} ce résultat à ce niveau de probabilité.")
    return lignes


def explique(r):
    poussent = sorted([j for j in range(len(FEATURE_NAMES)) if r['ecart'][j] > 0],
                      key=lambda j: -r['ecart'][j])[:3]
    return {'date': r['date'], 'ligue': r['ligue'], 'nom_ligue': LEAGUES.get(r['ligue'], r['ligue']),
            'domicile': r['domicile'], 'exterieur': r['exterieur'],
            'prevu': ETIQ[r['pred']], 'reel': ETIQ[r['reel']],
            'proba_prevue': r['p'][r['pred']], 'proba_reel': r['p'][r['reel']],
            'facteurs_pour_le_prevu': [facteur(FEATURE_NAMES[j], r['x'][j], r['z'][j]) for j in poussent],
            'faits': faits_match(r['brut']), 'lecture': lecture(r)}


# ---------------------------------------------------------------- journal des prévisions

def bilan_journal(index):
    """Compare les prévisions enregistrées avant match aux résultats connus."""
    if not os.path.exists(JOURNAL):
        return None
    with open(JOURNAL, encoding='utf-8') as f:
        entrees = [json.loads(l) for l in f if l.strip()]
    evaluees, attente = [], 0
    for e in entrees:
        brut = index.get((e['ligue'], e['date'], e['domicile'], e['exterieur']))
        if brut is None:
            attente += 1
            continue
        reel = brut['result']
        p = {'H': e['proba']['1'], 'D': e['proba']['N'], 'A': e['proba']['2']}
        prevu = max(ORDRE, key=lambda c: p[c])
        evaluees.append({'juste': prevu == reel, 'll': -math.log(max(p[reel], 1e-12)),
                         'brier': sum((p[c] - (1.0 if c == reel else 0.0)) ** 2 for c in ORDRE)})
    out = {'enregistrees': len(entrees), 'evaluees': len(evaluees), 'en_attente': attente}
    if evaluees:
        n = len(evaluees)
        out.update({'precision': sum(e['juste'] for e in evaluees) / n,
                    'log_loss': sum(e['ll'] for e in evaluees) / n,
                    'brier': sum(e['brier'] for e in evaluees) / n})
    return out


# ---------------------------------------------------------------- rédaction

def ecart_txt(e):
    if e['bas'] is None:
        return f"{nb(e['moyenne'], 3)} par match (échantillon trop petit pour un intervalle)"
    return (f"{nb(e['moyenne'], 3)} par match (intervalle à 95 % : {nb(e['bas'], 3)} à {nb(e['haut'], 3)})")


def verdict(e):
    if e['bas'] is None:
        return 'échantillon insuffisant'
    if e['bas'] > 0:
        return 'amélioration nette, l’intervalle est au-dessus de zéro'
    if e['haut'] < 0:
        return 'dégradation nette, l’intervalle est sous zéro'
    return 'pas de différence démontrée à ce stade'


def rediger(meta, glob, sem, cal, lig, ecarts, journal, delta, recurrents):
    L = []

    def ajoute(*lignes):
        L.extend(lignes)
    ajoute(f"# Bilan d’observation · saison {meta['saison_libelle']}", '',
           f"Données jusqu’au **{fr(meta['date_donnees'])}** · {glob['matchs']} matchs évalués sur "
           f"{meta['journees']} journées · rédigé le {fr(meta['genere_le'])}.", '',
           'Méthode : pour chaque journée, le modèle est réentraîné sur les seuls matchs antérieurs, '
           'puis prédit les matchs de la journée. Aucune cote n’est utilisée.', '')
    ajoute('## Résultat global', '',
           f"- Précision (le résultat le plus probable s’est réalisé) : **{pc(glob['precision'], 1)}** "
           f"(au hasard : 33 %).",
           f"- Log-loss, plus bas = mieux : modèle **{nb(glob['log_loss'], 3)}**, référence constante "
           f"{nb(glob['log_loss_reference'], 3)}, Elo seul {nb(glob['log_loss_elo'], 3)}.",
           f"- Modèle contre référence : {ecart_txt(glob['ecart_reference'])} — {verdict(glob['ecart_reference'])}.",
           f"- Modèle contre Elo seul : {ecart_txt(glob['ecart_elo'])} — {verdict(glob['ecart_elo'])}.", '')
    ajoute('## Calibration', '',
           'Quand le modèle annonce une probabilité, la fréquence observée doit être proche.', '')
    for c in ORDRE:
        ajoute(f"- {NOM_RESULTAT[c]} : prévu en moyenne **{pc(glob['prevue'][c], 1)}**, "
               f"observé **{pc(glob['observee'][c], 1)}**.")
    ajoute('')
    ajoute('## Points d’attention', '')
    attention = points_attention(cal)
    ajoute(*(attention or ['Aucun écart de calibration au-delà de deux erreurs-types.']), '')
    if delta:
        ajoute('## Depuis le bilan précédent', '',
               f"Bilan du {fr(delta['date_donnees'])} : {delta['matchs_ajoutes']} matchs ajoutés. "
               f"Log-loss {nb(delta['avant'], 3)} → **{nb(delta['apres'], 3)}** ; "
               f"précision {pc(delta['precision_avant'], 1)} → **{pc(delta['precision_apres'], 1)}**.", '')
    ajoute('## Progression journée après journée', '',
           '| Semaine (lundi) | Matchs | Précision | Log-loss | Log-loss cumulée | Référence cumulée | Compétence cumulée |',
           '|---|---:|---:|---:|---:|---:|---:|')
    for s in sem:
        ajoute(f"| {fr(s['semaine'])} | {s['matchs']} | {pc(s['precision'], 1)} | {nb(s['log_loss'], 3)} | "
               f"{nb(s['log_loss_cumule'], 3)} | {nb(s['log_loss_reference_cumule'], 3)} | "
               f"{pc(s['competence_cumulee'], 1)} |")
    ajoute('', '## Calibration détaillée', '',
           '| Résultat | Tranche de probabilité | Matchs | Prévu | Observé |',
           '|---|---|---:|---:|---:|')
    for c in cal:
        ajoute(f"| {ETIQ[c['resultat']]} | {pc(c['de'])} à {pc(min(c['a'], 1.0))} | {c['matchs']} | "
               f"{pc(c['prevue'], 1)} | {pc(c['observee'], 1)} |")
    ajoute('', '## Championnats', '',
           '| Championnat | Matchs | Précision | Log-loss | Compétence vs référence |',
           '|---|---:|---:|---:|---:|')
    for g in lig:
        ajoute(f"| {g['nom']} | {g['matchs']} | {pc(g['precision'], 1)} | {nb(g['log_loss'], 3)} | "
               f"{pc(g['competence'], 1)} |")
    ajoute('', f"## Écarts marquants (résultat réel jugé à moins de {pc(SEUIL_ECART)})", '')
    n_ecarts, top_facteurs = recurrents
    if n_ecarts:
        ajoute(f"Sur les {n_ecarts} écarts de la saison, les variables qui ont le plus poussé vers le prévu :",
               *[f"- {LIBELLES[nom]} : cité {k} fois" for nom, k in top_facteurs], '')
    if not ecarts:
        ajoute('Aucun écart de ce niveau.', '')
    for i, e in enumerate(ecarts, 1):
        ajoute(f"### {i}. {fr(e['date'])} · {e['nom_ligue']} · {e['domicile']} – {e['exterieur']}",
               f"Prévu : **{e['prevu']}** ({pc(e['proba_prevue'])}) · Réel : **{e['reel']}** ({pc(e['proba_reel'])} prévu pour ce résultat).",
               f"- **Ce qui poussait vers le prévu :** {' ; '.join(e['facteurs_pour_le_prevu']) or 'aucun facteur marquant'}.",
               f"- **Ce qui s’est passé :** {' ; '.join(e['faits'])}.",
               f"- **Lecture :** {e['lecture']}", '')
    ajoute('## Prévisions enregistrées avant match', '')
    if journal is None or journal['enregistrees'] == 0:
        ajoute("Le journal est vide : lancer `journal.py` avant les matchs pour enregistrer des prévisions prospectives.", '')
    else:
        ajoute(f"{journal['enregistrees']} prévisions enregistrées, {journal['evaluees']} évaluées, "
               f"{journal['en_attente']} en attente de résultat.")
        if journal['evaluees']:
            ajoute(f"Précision : **{pc(journal['precision'], 1)}** ; log-loss : **{nb(journal['log_loss'], 3)}**.", '')
        else:
            ajoute('')
    ajoute('## Limites', '',
           '- Un match est un événement à faible signal : une probabilité de 25 % se réalise une fois sur quatre.',
           '- Les lectures des écarts (tirs, expulsions) sont des indices, pas des preuves causales.',
           '- Les clubs hors des 16 championnats suivis ne sont pas évalués : aucun résultat n’est récupéré pour eux.',
           '- Le gain du modèle se juge sur l’intervalle à 95 %, pas sur une seule semaine.', '')
    return '\n'.join(L)


def principal(saison_demandee):
    rows = load_all()
    data, _ = build(rows)
    saison = saison_demandee or max(d['season'] for d in data)
    recs = evalue(data, saison)
    if not recs:
        raise SystemExit(f'aucun match joué pour la saison {saison}')
    index = {(r['league'], str(r['date']), r['home'], r['away']): r for r in rows if r['result'] in ORDRE}
    for r in recs:
        r['brut'] = index.get((r['ligue'], r['date'], r['domicile'], r['exterieur']))
    date_donnees = max(r['date'] for r in recs)
    glob = resume(recs)
    sem = par_semaine(recs)
    lig = par_ligue(recs)
    cal = calibration(recs)
    surprises = sorted([r for r in recs if r['p'][r['reel']] < SEUIL_ECART], key=lambda r: r['p'][r['reel']])[:15]
    ecarts = [explique(r) for r in surprises]
    journal = bilan_journal(index)
    if journal is not None:
        journal['entrees'] = journal_entrees(index)

    chemin_hist = os.path.join(BILAN, 'historique.json')
    histo = []
    if os.path.exists(chemin_hist):
        with open(chemin_hist, encoding='utf-8') as f:
            histo = json.load(f)
    avant = [h for h in histo if h['saison'] == saison and h['date_donnees'] < date_donnees]
    precedent = max(avant, key=lambda h: h['date_donnees']) if avant else None
    delta = None
    if precedent:
        delta = {'date_donnees': precedent['date_donnees'], 'matchs_ajoutes': glob['matchs'] - precedent['matchs'],
                 'avant': precedent['log_loss'], 'apres': glob['log_loss'],
                 'precision_avant': precedent['precision'], 'precision_apres': glob['precision']}
    entree = {'saison': saison, 'date_donnees': date_donnees, 'genere_le': dt.date.today().isoformat(),
              'matchs': glob['matchs'], 'precision': glob['precision'], 'log_loss': glob['log_loss'],
              'log_loss_reference': glob['log_loss_reference'], 'competence': glob['competence']}
    histo = [h for h in histo if not (h['saison'] == saison and h['date_donnees'] == date_donnees)] + [entree]
    histo.sort(key=lambda h: (h['saison'], h['date_donnees']))
    os.makedirs(BILAN, exist_ok=True)
    with open(chemin_hist, 'w', encoding='utf-8') as f:
        json.dump(histo, f, ensure_ascii=False, indent=1)

    meta = {'saison': saison, 'saison_libelle': f'20{saison[:2]}-{saison[2:]}', 'date_donnees': date_donnees,
            'genere_le': dt.date.today().isoformat(), 'journees': len({r['jour'] for r in recs})}
    base = os.path.join(BILAN, f'bilan-{saison}-{date_donnees}')
    with open(base + '.md', 'w', encoding='utf-8') as f:
        f.write(rediger(meta, glob, sem, cal, lig, ecarts, journal, delta, facteurs_recurrents(recs)))
    with open(base + '.json', 'w', encoding='utf-8') as f:
        json.dump({'meta': meta, 'resume': glob, 'semaines': sem, 'calibration': cal, 'ligues': lig,
                   'ecarts': ecarts, 'journal': journal, 'depuis_precedent': delta,
                   'attention': points_attention_donnees(cal), 'facteurs_recurrents': facteurs_recurrents_donnees(recs)},
                  f, ensure_ascii=False, indent=1)
    print(f'saison {saison} : {glob["matchs"]} matchs évalués, précision {pc(glob["precision"], 1)}, '
          f'log-loss {nb(glob["log_loss"], 3)} (référence {nb(glob["log_loss_reference"], 3)}, '
          f'Elo seul {nb(glob["log_loss_elo"], 3)})')
    print(f'gain vs référence : {ecart_txt(glob["ecart_reference"])} → {verdict(glob["ecart_reference"])}')
    print(f'gain vs Elo seul : {ecart_txt(glob["ecart_elo"])} → {verdict(glob["ecart_elo"])}')
    print(f'écrit : {base}.md et .json')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--saison', default=None, help='code de saison, par exemple 2627')
    principal(ap.parse_args().saison)
