"""Fiche de qualité recalculée avec le même code que le modèle, sur les mêmes saisons que les tests publiés.
- Test : entraînement sur les saisons jusqu’à 2324, évaluation sur 2425 et 2526 ;
- Saison en cours : entraînement jusqu’à 2526, évaluation sur 2627.
Méthodes : modèle à 25 variables (C = 0.5), probabilités moyennes de l’historique, Elo seul."""
import math

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

LABELS = ['H', 'D', 'A']
TOUTES = list(range(25))
SANS_ELO = list(range(1, 25))
C_ELO, HA, S_ELO = 0.6, 90.0, 250.0   # paramètres de l’Elo (model_state.json)


def perte(P, y):
    """Erreur de log-vraisemblance moyenne : plus elle est basse, mieux c’est."""
    idx = {'H': 0, 'D': 1, 'A': 2}
    return -float(np.mean([math.log(max(float(P[i][idx[c]]), 1e-12)) for i, c in enumerate(y)]))


def precision(P, y):
    pred = [LABELS[int(np.argmax(p))] for p in P]
    return float(np.mean([a == b for a, b in zip(pred, y)]))


def modele(tr, te, cols):
    Xtr = np.array([[r['x'][j] for j in cols] for r in tr], dtype=float)
    Xte = np.array([[r['x'][j] for j in cols] for r in te], dtype=float)
    sc = StandardScaler().fit(Xtr)
    m = LogisticRegression(C=0.5, max_iter=5000).fit(sc.transform(Xtr), [r['y'] for r in tr])
    cls = list(m.classes_)
    P = np.array(m.predict_proba(sc.transform(Xte)))
    return P[:, [cls.index('H'), cls.index('D'), cls.index('A')]]


def moyenne(tr, te):
    n = len(tr)
    part = [sum(1 for r in tr if r['y'] == c) / n for c in LABELS]
    return [part] * len(te)


def elo_seul(te):
    out = []
    for r in te:
        x = (r['x'][0] * 100 + HA) / S_ELO
        pH = 1 / (1 + math.exp(-(x - C_ELO)))
        pA = 1 / (1 + math.exp(-(-C_ELO - x)))
        out.append([pH, max(0.0, 1 - pH - pA), pA])
    return out


def fiche(rows):
    cas = {
        'test': ([r for r in rows if r['season'] <= '2324'], [r for r in rows if r['season'] in ('2425', '2526')]),
        'recent': ([r for r in rows if r['season'] <= '2526'], [r for r in rows if r['season'] == '2627']),
    }
    res = {}
    for nom, (tr, te) in cas.items():
        y = [r['y'] for r in te]
        P_av = modele(tr, te, TOUTES)
        res[nom] = {'n': len(te), 'moyenne': perte(moyenne(tr, te), y), 'modele': perte(P_av, y),
                    'modele_precision': precision(P_av, y), 'sans_elo': perte(modele(tr, te, SANS_ELO), y)}
        if nom == 'test':
            P_el = elo_seul(te)
            res[nom]['elo'] = perte(P_el, y)
            res[nom]['elo_precision'] = precision(P_el, y)
    return res
