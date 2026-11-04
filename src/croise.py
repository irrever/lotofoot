"""Probabilités entre équipes de championnats différents, et clubs hors des 16 championnats suivis.

Même calcul que l’application (standalone/app.html : calculMatch, niveauAjuste, equipeHypothese) : les statistiques de
l’équipe du championnat le plus faible sont ramenées à l’échelle du plus fort, et l’écart de note des championnats
s’ajoute à l’écart Elo. Aucune cote n’est utilisée. Les constantes ci-dessous doivent rester identiques à celles de
l’application : src/test_croise.py le vérifie.
"""
import math
import unicodedata

ORDRE = ['H', 'D', 'A']
NIVEAU_VARS = ['dW', 'dD', 'dL', 'eW', 'eD', 'eL', 'forme', 'gf', 'ga', 'cadF', 'cadA', 'cor', 'car']
VARS_MOYENNE = ['dW', 'dD', 'dL', 'eW', 'eD', 'eL', 'forme', 'gf', 'ga', 'rest', 'load', 'cadF', 'cadA', 'cor', 'car']

# Niveau estimé (sur 100) des championnats hors des 16 suivis, et clubs hypothétiques de ces championnats.
CHAMPIONNATS_HYPOTHESE = {
    'NO1': {'pays': 'Norvège', 'note': 47.5},
    'AT1': {'pays': 'Autriche', 'note': 50},
    'SK1': {'pays': 'Slovaquie', 'note': 37.5},
    'CZ1': {'pays': 'Tchéquie', 'note': 45},
    'HR1': {'pays': 'Croatie', 'note': 40},
    'DK1': {'pays': 'Danemark', 'note': 47.5},
}
CLUBS_HYPOTHESE = {
    'Bodø/Glimt': {'ligue': 'NO1', 'elo': 1782, 'niveau': 'dominant',
                   'motif': 'Un des clubs les plus forts de Norvège ces dernières saisons.'},
    'LASK Linz': {'ligue': 'AT1', 'elo': 1674, 'niveau': 'haut',
                  'motif': 'Club du haut de tableau autrichien, souvent dans les places européennes, sans être dominant.'},
    'Slovan Bratislava': {'ligue': 'SK1', 'elo': 1758, 'niveau': 'dominant',
                          'motif': 'Club le plus titré de Slovaquie, en général le plus fort de son championnat.'},
    'Slavia Prague': {'ligue': 'CZ1', 'elo': 1776, 'niveau': 'dominant',
                      'motif': 'Club le plus fort de Tchéquie ces dernières saisons.'},
    'Dinamo Zagreb': {'ligue': 'HR1', 'elo': 1764, 'niveau': 'dominant',
                      'motif': 'Club le plus fort de Croatie, en général champion.'},
    'Nordsjaelland': {'ligue': 'DK1', 'elo': 1670, 'niveau': 'haut',
                      'motif': 'Club du haut de tableau danois, sans statut de favori.'},
}

# Noms de l’application (clés normalisées) : variantes courantes des noms de grilles.
ALIAS_EQUIPES = {
    'como 1907': 'Como', 'betis seville': 'Betis', 'fc porto': 'Porto', 'naples': 'Napoli',
    'club bruges': 'Club Brugge', 'aek athenes': 'AEK', 'manchester city': 'Man City', 'psg': 'Paris SG',
    'sporting': 'Sp Lisbon', 'sporting cp': 'Sp Lisbon', 'slobratislava': 'Slovan Bratislava',
}
# Noms de la page de résultats Pronosoft (clés normalisées) vers les noms de l’application.
ALIAS_PRONOSOFT = {'bod/glimt': 'Bodø/Glimt', 'atl madrid': 'Ath Madrid', 'psg': 'Paris SG',
                   'fc barcelone': 'Barcelona', 'inter milan': 'Inter', 'as rome': 'Roma'}


def norm(texte):
    """Minuscules, sans accents."""
    return ''.join(c for c in unicodedata.normalize('NFD', texte.lower()) if unicodedata.category(c) != 'Mn')


def cle(texte):
    """Clé de comparaison d’un nom d’équipe : sans accents, sans points, espaces réduits."""
    return ' '.join(norm(texte).replace('.', '').split())


def canon_pronosoft(nom):
    """Nom Pronosoft ramené au nom utilisé par l’application."""
    return ALIAS_PRONOSOFT.get(cle(nom), nom)


def proba_match(h, a, modele, ecart_elo):
    """Probabilités 1 / N / 2 : même calcul que l’application (les 25 variables du modèle, dans son ordre)."""
    v, w = h['vec'], a['vec']
    x = [ecart_elo / 100, v['dW'], v['dD'], v['dL'], w['eW'], w['eD'], w['eL'], v['forme'], w['forme'],
         v['gf'], v['ga'], w['gf'], w['ga'], v['rest'], w['rest'], v['load'], w['load'],
         v['cadF'], v['cadA'], w['cadF'], w['cadA'], v['cor'], w['cor'], v['car'], w['car']]
    z = {c: modele['ordonnee'][c] + sum(modele['coef'][c][j] * (x[j] - modele['moyenne'][j]) / modele['echelle'][j]
                                       for j in range(len(x)))
         for c in ORDRE}
    haut = max(z.values())
    e = {c: math.exp(z[c] - haut) for c in ORDRE}
    total = sum(e.values())
    return {c: e[c] / total for c in ORDRE}


def note_de(donnees, code):
    """Note de championnat sur 100 : celle des 16 championnats suivis, sinon l’estimation."""
    for n in donnees.get('stats', {}).get('notes', []):
        if n.get('code') == code:
            return n.get('note')
    h = CHAMPIONNATS_HYPOTHESE.get(code)
    return h['note'] if h else None


def moyenne_elo_ligue(donnees, code):
    """Elo moyen d’un championnat : celui des équipes suivies, ou, pour un championnat hypothétique, 1 512 + 0,96 × note."""
    elos = [t['vec']['elo'] for t in donnees['equipes'] if t['ligue'] == code]
    if elos:
        return sum(elos) / len(elos)
    return 1512 + 0.96 * note_de(donnees, code)


def moyenne(equipes, champs):
    out = {}
    for k in champs:
        vals = [t['vec'][k] for t in equipes if isinstance(t.get('vec', {}).get(k), (int, float))]
        out[k] = sum(vals) / len(vals) if vals else 0.0
    return out


def moyenne_championnat(donnees, code):
    ts = [t for t in donnees['equipes'] if t['ligue'] == code]
    return moyenne(ts or donnees['equipes'], NIVEAU_VARS)


def niveau_ajuste(vec, own, opp, donnees):
    """Statistiques de l’équipe ramenées au niveau du championnat le plus fort (si son championnat est plus faible)."""
    out = dict(vec)
    if not own or not opp or own == opp:
        return out
    n_own, n_opp = note_de(donnees, own), note_de(donnees, opp)
    if n_own is None or n_opp is None or n_own >= n_opp:
        return out
    ratio = n_own / n_opp
    fort, faible = moyenne_championnat(donnees, opp), moyenne_championnat(donnees, own)
    for f in NIVEAU_VARS:
        out[f] = fort[f] + ratio * (vec[f] - faible[f])
    return out


def equipe_hypothese(donnees, nom):
    h = CLUBS_HYPOTHESE[nom]
    vec = moyenne(donnees['equipes'], VARS_MOYENNE)
    vec['elo'] = h['elo']
    return {'ligue': h['ligue'], 'equipe': nom, 'vec': vec, 'hypothese': True, 'niveau': h['niveau'],
            'motif': h['motif']}


def trouver_equipe(donnees, nom):
    """L’équipe d’un nom de grille : une des 16 championnats suivis, ou un club hypothétique ; sinon None."""
    k = cle(nom)
    if not k:
        return None
    cibles = [k] + ([cle(ALIAS_EQUIPES[k])] if k in ALIAS_EQUIPES else [])
    for c in cibles:
        for t in donnees['equipes']:
            if cle(t['equipe']) == c:
                return t
    for c in cibles:
        for nom_h in CLUBS_HYPOTHESE:
            if cle(nom_h) == c:
                return equipe_hypothese(donnees, nom_h)
    return None


def avec_absences(t):
    """Statistiques de l’équipe, Elo corrigé du malus d’absences (même règle que l’application)."""
    v = dict(t['vec'])
    m = malus_de(t)
    if m:
        v['elo'] = t['vec']['elo'] + m
    return v


def malus_de(t):
    return (t.get('absences') or {}).get('malus', 0) or 0


def calcul_match(donnees, h, a):
    """Probabilités 1 / N / 2 du match « h reçoit a ». Renvoie None si une note de championnat manque."""
    cross = h['ligue'] != a['ligue']
    gap, nh, na = 0.0, None, None
    if cross:
        nh, na = note_de(donnees, h['ligue']), note_de(donnees, a['ligue'])
        if nh is None or na is None:
            return None
        gap = donnees.get('stats', {}).get('points_elo_par_note', 4) * (nh - na)
    vh, va = avec_absences(h), avec_absences(a)
    if cross:
        vh = niveau_ajuste(vh, h['ligue'], a['ligue'], donnees)
        va = niveau_ajuste(va, a['ligue'], h['ligue'], donnees)
        # Position dans le championnat : chaque club est comparé à la moyenne de son propre championnat
        vh['elo'] -= moyenne_elo_ligue(donnees, h['ligue'])
        va['elo'] -= moyenne_elo_ligue(donnees, a['ligue'])
    ecart = vh['elo'] - va['elo'] + gap
    p = proba_match({'vec': vh}, {'vec': va}, donnees['modele'], ecart)
    hypothese = [t['equipe'] for t in (h, a) if t.get('hypothese')]
    if not cross:
        methode = 'meme_championnat'
    elif hypothese:
        methode = 'hypothese'
    else:
        methode = 'inter_championnats'
    return {'p': p, 'ecart': round(ecart, 1), 'gap': round(gap, 1), 'croise': cross, 'nh': nh, 'na': na,
            'methode': methode, 'hypothese': hypothese,
            'malus': {'domicile': malus_de(h), 'exterieur': malus_de(a)}}
