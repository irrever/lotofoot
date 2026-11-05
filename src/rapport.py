"""Résultats des grilles du Loto Foot : pronostic, résultat, verdict et raison, pour chaque match de grille.

- data/journal/grilles.jsonl : le pronostic de chaque match de grille, enregistré une fois, avant la clôture. Une ligne
  n’est jamais modifiée ; un match sans pronostic (équipe inconnue) est recalculé tant que sa grille n’est pas close.
- Résultats : championnats suivis (football-data) ; pour les autres matchs, page « Résultats et rapports » de
  Pronosoft (data/resultats/pronosoft.json, alimenté par src/pronosoft.py collecter).
- Chaque match reçoit un verdict, une explication, et, quand le pronostic est faux, une raison. Les raisons sont comptées
  dans le bilan pour voir ce qui fait échouer le modèle.
- Chaque prévision garde aussi la contribution de chaque facteur (points de probabilité, src/croise.py) : la fiche d’un
  match cite les plus forts, pour le pronostic et pour le résultat réel.

Sortie : data/resultats.json, lu par l’onglet « Résultats ». Usage : python3 src/rapport.py (lancé par boucle.sh).
Les probabilités reprennent la formule de l’application (src/croise.py), à partir de data/donnees_publiees.json.
"""
import datetime as dt
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from croise import calcul_match, canon_pronosoft, cle, trouver_equipe  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent
DONNEES = RACINE / 'data'
GRILLES = RACINE / 'grilles'
JOURNAL_GRILLES = DONNEES / 'journal' / 'grilles.jsonl'
PRONOSOFT = DONNEES / 'resultats' / 'pronosoft.json'
SORTIE = DONNEES / 'resultats.json'
GRILLES_PRIVEES = {153}       # grille personnelle : exclue de toutes les sorties (demande initiale)
GRILLES_AFFICHEES = 12        # les grilles les plus récentes dans l’onglet
ORDRE = ['H', 'D', 'A']
ETIQ = {'H': '1', 'D': 'N', 'A': '2'}
NOM_ISSUE = {'1': 'victoire à domicile', 'N': 'match nul', '2': 'victoire à l’extérieur'}
FENETRE_JOURS = 3             # tolérance entre la date de clôture d’une grille et la date du match (football-data)
FENETRE_PRONOSOFT_JOURS = 14  # une page Pronosoft est relevée quelques jours après le match au plus tard
RELEVES_JOURS = 7             # résultats relevés par Pronosoft pour les grilles non suivies : sur ce nombre de jours
VERSION_METHODE = 2          # 2 : position dans le championnat (écart de niveau entre championnats)
MALUS_SIGNIFICATIF = -5       # un malus d’absences plus fort (en points Elo) est cité comme raison possible
SEUIL_FAVORI = 0.5            # au-dessus de cette probabilité, le pronostic désigne un favori net
PESEES_MAX = 3                # facteurs cités pour une prévision : les plus forts, dans un sens ou dans l’autre
PESEES_SEUIL = 1.0            # en points de probabilité : un facteur plus faible n’est pas cité
MIN_PESEES_CONCLUSION = 100   # prévisions résolues avec détail par facteur avant de conclure sur un facteur
FAMILLES = {
    'niveau': 'niveau (écart Elo)', 'championnat': 'écart entre championnats', 'absences': 'absences',
    'bilan': 'bilan à domicile / à l’extérieur', 'forme': 'forme', 'attaque': 'buts marqués',
    'defense': 'buts encaissés', 'repos': 'repos', 'charge': 'nombre de matchs récents', 'tirs': 'tirs cadrés',
    'tirs_encaisses': 'tirs cadrés concédés', 'corners': 'corners', 'cartons': 'cartons',
}
LIBELLES_PESEES = {
    'niveau': 'l’écart de niveau (Elo)',
    'championnat': 'l’écart entre championnats',
    'bilan_dom': 'le bilan à domicile de {dom}',
    'bilan_ext': 'le bilan à l’extérieur de {ext}',
    'forme_dom': 'la forme de {dom}',
    'forme_ext': 'la forme de {ext}',
    'attaque_dom': 'les buts marqués par {dom}',
    'defense_dom': 'les buts encaissés par {dom}',
    'attaque_ext': 'les buts marqués par {ext}',
    'defense_ext': 'les buts encaissés par {ext}',
    'repos_dom': 'le repos de {dom}',
    'repos_ext': 'le repos de {ext}',
    'charge_dom': 'le nombre de matchs récents de {dom}',
    'charge_ext': 'le nombre de matchs récents de {ext}',
    'tirs_dom': 'les tirs cadrés de {dom}',
    'tirs_encaisses_dom': 'les tirs cadrés concédés par {dom}',
    'tirs_ext': 'les tirs cadrés de {ext}',
    'tirs_encaisses_ext': 'les tirs cadrés concédés par {ext}',
    'corners_dom': 'les corners de {dom}',
    'corners_ext': 'les corners de {ext}',
    'cartons_dom': 'les cartons de {dom}',
    'cartons_ext': 'les cartons de {ext}',
}
CAUSES = {
    'nul': 'Match nul, peu probable selon le modèle',
    'surprise': 'Favori battu',
    'serre': 'Match trop serré pour trancher',
}
FACTEURS = {
    'absences': 'Absences signalées chez le pronostic',
    'hypothese': 'Club hors des 16 championnats (niveau estimé)',
}
TRANCHES = [(0.0, 0.45, 'pronostic à moins de 45 %'), (0.45, 0.6, 'pronostic de 45 à 60 %'),
            (0.6, 1.01, 'pronostic à 60 % et plus')]
MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
        'septembre', 'octobre', 'novembre', 'décembre']


def date_fr(d):
    return ('1er' if d.day == 1 else str(d.day)) + ' ' + MOIS[d.month - 1] + ' ' + str(d.year)


def pct(p):
    return str(round(p * 100))


def charger_jsonl(chemin):
    if not chemin.exists():
        return []
    with open(chemin, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def derniere_entree(entrees):
    """Pour chaque match, la dernière ligne du journal (une ligne plus récente remplace une « non prévu »)."""
    return {e['id']: e for e in entrees}


def charger_grilles():
    """Toutes les grilles présentes dans grilles/ (sauf la grille privée) : format, numéro, clôture et matchs."""
    out = []
    for fichier in sorted(GRILLES.glob('loto-foot-*.json')):
        contenu = json.loads(fichier.read_text(encoding='utf-8'))
        for grille in contenu.get('grilles', []):
            if grille['numero'] in GRILLES_PRIVEES:
                continue
            out.append({'format': contenu['format'], 'numero': grille['numero'], 'cloture': grille['cloture'],
                        'matchs': grille['matchs']})
    return out


def pronostic_match(donnees, domicile, exterieur):
    """Champs du pronostic d’un match de grille, ou la raison pour laquelle il n’y en a pas."""
    h, a = trouver_equipe(donnees, domicile), trouver_equipe(donnees, exterieur)
    r = calcul_match(donnees, h, a) if h and a else None
    if r is None:
        return {'non_prevu': 'équipe hors des 16 championnats suivis, sans estimation de niveau'}
    p = r['p']
    out = {'proba': {ETIQ[c]: round(p[c], 6) for c in ORDRE},
           'pronostic': ETIQ[max(ORDRE, key=lambda c: p[c])],
           'ecart_elo': r['ecart'], 'gap': r['gap'], 'methode': r['methode'], 'malus': r['malus']}
    out['contributions'] = {f: {ETIQ[c]: v[c] for c in ORDRE} for f, v in r['contributions'].items()}
    if r['croise']:
        out['ligues'] = [h['ligue'], a['ligue']]
        out['notes'] = {'domicile': r['nh'], 'exterieur': r['na']}
    else:
        out['ligue'] = h['ligue']
    if r['hypothese']:
        out['hypothese'] = r['hypothese']
    return out


def enregistrer_grilles(donnees, grilles, maintenant, aujourdhui, reconstituee=False):
    """Ajoute au journal le pronostic de chaque match de grille, avant le match. Une ligne existante n’est pas modifiée.
    Une prévision reconstituée (grille déjà close au moment de l’enregistrement) est marquée comme telle."""
    actuelles = derniere_entree(charger_jsonl(JOURNAL_GRILLES))
    nouvelles = []
    for g in grilles:
        date_cloture = g['cloture'][:10]
        ouverte = dt.date.fromisoformat(date_cloture) >= aujourdhui
        for n, m in enumerate(g['matchs'], 1):
            cle_id = '%s|%s|%s' % (date_cloture, m['domicile'], m['exterieur'])
            ancienne = actuelles.get(cle_id)
            # Une prévision déjà enregistrée n’est refaite que si la méthode a changé et que la grille n’est pas close
            a_jour = ancienne is not None and 'proba' in ancienne and ancienne.get('version_methode', 1) == VERSION_METHODE
            if ancienne is not None and (a_jour or not ouverte):
                continue
            base = {'id': cle_id, 'enregistree_le': maintenant, 'format': g['format'], 'numero': g['numero'], 'n': n,
                    'cloture': g['cloture'], 'date': date_cloture, 'domicile': m['domicile'],
                    'exterieur': m['exterieur']}
            if reconstituee:
                base['reconstituee'] = True
            entree = {**base, **pronostic_match(donnees, m['domicile'], m['exterieur']), 'version_methode': VERSION_METHODE}
            if ancienne is not None and 'proba' in ancienne:
                entree['remplace'] = ancienne['enregistree_le']
            actuelles[cle_id] = entree
            nouvelles.append(entree)
    if nouvelles:
        JOURNAL_GRILLES.parent.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL_GRILLES, 'a', encoding='utf-8') as f:
            for e in nouvelles:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')
    return nouvelles


def charger_championnats():
    """Résultats des championnats suivis (football-data). Liste vide si indisponibles (exécution hors publication)."""
    try:
        from load import load_all
        return load_all() if (DONNEES / 'raw').exists() else []
    except Exception as e:  # sans ces données, seuls les résultats Pronosoft sont utilisés
        print('résultats des championnats indisponibles :', type(e).__name__)
        return []


def index_resultats(rows):
    """(ligue, domicile, extérieur) -> liste de (date, résultat, buts domicile, buts extérieur)."""
    idx = {}
    for r in rows:
        if r['result'] in ORDRE and r['hg'] not in (None, '') and r['ag'] not in (None, ''):
            idx.setdefault((r['league'], r['home'], r['away']), []).append(
                (r['date'], r['result'], int(r['hg']), int(r['ag'])))
    return idx


def resultat_de(idx, ligue, domicile, exterieur, date_ref):
    """Résultat du match joué à moins de FENETRE_JOURS jours de date_ref : (date, résultat, buts, buts) ou None."""
    meilleur = None
    for d, res, hg, ag in idx.get((ligue, domicile, exterieur), []):
        ecart = abs((d - date_ref).days)
        if ecart <= FENETRE_JOURS and (meilleur is None or ecart < meilleur[0]):
            meilleur = (ecart, d, res, hg, ag)
    return meilleur[1:] if meilleur else None


def charger_pronosoft():
    if not PRONOSOFT.exists():
        return []
    return json.loads(PRONOSOFT.read_text(encoding='utf-8')).get('matchs', [])


def index_pronosoft(matchs):
    """(domicile, extérieur) normalisés -> relevés (score, date du relevé)."""
    idx = {}
    for m in matchs:
        cles = (cle(canon_pronosoft(m['domicile'])), cle(canon_pronosoft(m['exterieur'])))
        idx.setdefault(cles, []).append({'score': m['score'], 'vu': dt.date.fromisoformat(m['vu'])})
    return idx


def resultat_match(e, idx_fd, idx_ps):
    """Résultat d’un match de grille : source, date, score et issue (1, N ou 2), ou None si pas encore publié."""
    date_cloture = dt.date.fromisoformat(e['cloture'][:10])
    if 'ligue' in e and idx_fd:
        res = resultat_de(idx_fd, e['ligue'], e['domicile'], e['exterieur'], date_cloture)
        if res is not None:
            d, issue, hg, ag = res
            return {'source': 'football-data', 'date': d.isoformat(), 'score': '%d – %d' % (hg, ag),
                    'issue': ETIQ[issue]}
    cles = (cle(canon_pronosoft(e['domicile'])), cle(canon_pronosoft(e['exterieur'])))
    fin = date_cloture + dt.timedelta(days=FENETRE_PRONOSOFT_JOURS)
    releves = [r for r in idx_ps.get(cles, []) if date_cloture <= r['vu'] <= fin]
    if releves:
        r = min(releves, key=lambda r: r['vu'])
        a, b = (int(x) for x in r['score'].split('-'))
        issue = '1' if a > b else ('N' if a == b else '2')
        return {'source': 'pronosoft', 'date': r['vu'].isoformat(), 'score': '%d – %d' % (a, b), 'issue': issue}
    return None


def explication_ok(e):
    prono, p = e['pronostic'], e['proba'][e['pronostic']]
    if prono == 'N':
        texte = 'Le match nul était l’issue la plus probable (%s %%) : il s’est produit.' % pct(p)
    elif p >= SEUIL_FAVORI:
        equipe = e['domicile'] if prono == '1' else e['exterieur']
        texte = '%s était favori à %s %%, et a gagné.' % (equipe, pct(p))
    else:
        texte = ('Pronostic « %s » le plus probable, mais sans favori net (%s %%) : il s’est confirmé.'
                 % (NOM_ISSUE[prono], pct(p)))
    if e.get('hypothese'):
        texte += ' Un des clubs est hors des 16 championnats : son niveau est estimé.'
    return texte


def facteurs_de(e):
    """Facteurs signalés avant le match, qui peuvent expliquer un échec : absences chez l’équipe pronostiquée,
    club hors des 16 championnats (niveau estimé)."""
    prono = e['pronostic']
    mal = e.get('malus') or {}
    m = (mal.get('domicile' if prono == '1' else 'exterieur') or 0) if prono in ('1', '2') else 0
    out = []
    if m <= MALUS_SIGNIFICATIF:
        out.append('absences')
    if e.get('hypothese'):
        out.append('hypothese')
    return out


def raison_erreur(e, res):
    """Raison principale d’un pronostic faux (match nul, favori battu, match serré), explication et facteurs."""
    prono, issue = e['pronostic'], res['issue']
    pp, pi = e['proba'][prono], e['proba'][issue]
    equipe = e['domicile'] if prono == '1' else (e['exterieur'] if prono == '2' else None)
    if issue == 'N':
        cause = 'nul'
        texte = ('Match nul : le modèle ne lui donnait que %s %%, contre %s %% pour le pronostic (%s).'
                 % (pct(pi), pct(pp), NOM_ISSUE[prono]))
    elif pp >= SEUIL_FAVORI:
        cause = 'surprise'
        texte = '%s était favori à %s %% et a perdu.' % (equipe or 'Le pronostic', pct(pp))
    else:
        cause = 'serre'
        texte = ('Aucune issue nette : le pronostic (%s) ne dépassait pas %s %%, et le résultat (%s) '
                 'était possible à %s %%.' % (NOM_ISSUE[prono], pct(pp), NOM_ISSUE[issue], pct(pi)))
    facteurs = facteurs_de(e)
    if 'absences' in facteurs:
        mal = e.get('malus') or {}
        m = mal.get('domicile' if prono == '1' else 'exterieur')
        texte += (' %s avait des absences signalées (malus de %d points Elo) : le modèle les a prises en compte, '
                  'mais leur effet a pu être sous-estimé.' % (equipe, -m))
    if 'hypothese' in facteurs:
        texte += (' %s : niveau estimé, car le club évolue hors des 16 championnats suivis ; le pronostic est donc '
                  'moins fiable.' % ' et '.join(e['hypothese']))
    return cause, texte, facteurs


def raisons_de(e, res):
    """Ce que le modèle retenait pour ce match, et ce qui l’a contredit : écart de niveau, marge entre les issues,
    absences, niveau estimé. Chaque raison est une phrase précise, tirée des données enregistrées. Le score n’est pas
    répété : il reste sur la ligne du match."""
    prono, issue, p = e['pronostic'], res['issue'], e['proba']
    a, b = (int(x) for x in res['score'].split('–'))
    ecart = abs(float(e.get('ecart_elo') or 0))
    equipe = e['domicile'] if prono == '1' else (e['exterieur'] if prono == '2' else None)
    marge = (p[prono] - max(v for k, v in p.items() if k != prono)) * 100
    raisons = []
    if prono == issue:
        if equipe and ecart >= 40:
            raisons.append('L’écart de niveau (%d points Elo) allait dans le sens de %s : le modèle a bien lu le niveau.'
                           % (ecart, equipe))
        else:
            raisons.append('L’écart de niveau était faible (%d points Elo) : le bon résultat tient à la marge du modèle '
                           '(%d points).' % (ecart, marge))
        if abs(a - b) >= 2:
            raisons.append('Victoire nette : le résultat n’a pas été serré.')
    elif issue == 'N':
        if ecart < 60:
            raisons.append('Équipes proches : écart de %d points Elo seulement, un nul était plausible.' % ecart)
        else:
            raisons.append('L’écart de %d points Elo allait dans le sens du pronostic, mais le match s’est fermé : le niveau '
                           'mesuré ne suffit pas à prévoir un nul.' % ecart)
        raisons.append('Le modèle donnait %s %% au nul, contre %s %% au pronostic.' % (pct(p['N']), pct(p[prono])))
    elif p[prono] >= SEUIL_FAVORI:
        raisons.append('%s était favori à %s %% et a perdu.' % (equipe or 'Le nul', pct(p[prono])))
        if ecart >= 100:
            raisons.append('L’écart de %d points Elo était fort : le résultat contredit le niveau mesuré. Cause probable hors '
                           'modèle : forme récente, blessures non signalées, contexte du match.' % ecart)
        elif ecart >= 40:
            raisons.append('L’écart de %d points Elo était modéré : une défaite restait plausible.' % ecart)
        else:
            raisons.append('L’écart de niveau n’était que de %d points Elo : le favori tenait surtout à la marge du modèle '
                           '(%d points).' % (ecart, marge))
    else:
        raisons.append('Aucune issue nette : %s à %s %%, %s à %s %%, soit une marge de %d points.'
                       % (NOM_ISSUE[prono], pct(p[prono]), NOM_ISSUE[issue], pct(p[issue]), marge))
        if ecart < 40:
            raisons.append('Écart de niveau de %d points Elo seulement : le modèle n’avait pas de raison forte de trancher.'
                           % ecart)
        else:
            raisons.append('Écart de %d points Elo, mais la marge entre les issues était trop faible pour trancher.' % ecart)
    if issue not in (prono, 'N'):
        if abs(a - b) >= 2:
            raisons.append('Défaite nette : l’erreur est franche, ce n’est pas un détail de match.')
        else:
            raisons.append('Un seul but d’écart : un match qui aurait pu basculer.')
    mal = (e.get('malus') or {}).get('domicile' if prono == '1' else 'exterieur') if prono in ('1', '2') else None
    if equipe and mal and mal <= MALUS_SIGNIFICATIF:
        raisons.append('Absences signalées chez %s (malus de %d points Elo) : prises en compte, mais leur effet a pu être '
                       'sous-estimé.' % (equipe, -mal))
    if e.get('hypothese'):
        raisons.append('Niveau estimé pour %s, club hors des 16 championnats : c’est une source d’erreur probable.'
                       % ' et '.join(e['hypothese']))
    if len(set(e.get('ligues') or [])) > 1:
        raisons.append('Match entre championnats (%s et %s) : l’écart de niveau entre eux est une estimation.'
                       % tuple(e['ligues']))
    return raisons


def analyser(e, res):
    """Statut, cause principale, facteurs, explication et raisons d’un match de grille."""
    if 'proba' not in e:
        return {'statut': 'sans_pronostic', 'cause': None, 'facteurs': [], 'raisons': [],
                'explication': 'Pas de pronostic : %s.' % e.get('non_prevu', 'donnée manquante')}
    if res is None:
        return {'statut': 'attente', 'cause': None, 'facteurs': [], 'raisons': [],
                'explication': 'Résultat pas encore publié.'}
    if e['pronostic'] == res['issue']:
        return {'statut': 'ok', 'cause': None, 'facteurs': facteurs_de(e), 'explication': explication_ok(e),
                'raisons': raisons_de(e, res)}
    cause, texte, facteurs = raison_erreur(e, res)
    return {'statut': 'ko', 'cause': cause, 'facteurs': facteurs, 'explication': texte, 'raisons': raisons_de(e, res)}


def famille_de(code):
    """Famille d’un facteur : bilan_dom et bilan_ext ont la même famille, forme_dom et forme_ext aussi, etc."""
    return code.rsplit('_', 1)[0] if code.endswith(('_dom', '_ext')) else code


def facteurs_forts(e, etiquette):
    """Facteurs qui pèsent au moins PESEES_SEUIL points sur la probabilité de l’issue, les plus forts d’abord."""
    contrib = e.get('contributions') or {}
    pts = [(code, v[etiquette]) for code, v in contrib.items() if abs(v.get(etiquette, 0)) >= PESEES_SEUIL]
    return sorted(pts, key=lambda kv: -abs(kv[1]))


def compter_familles(listes):
    """Nombre de prévisions où chaque famille apparaît (une fois par prévision)."""
    compte = {}
    for familles in listes:
        for f in set(familles):
            compte[f] = compte.get(f, 0) + 1
    return compte


def facteurs_erreurs(analyses):
    """Familles de facteurs qui ont poussé vers le pronostic raté, et vers le résultat réel, sur les prévisions ratées qui
    ont un détail par facteur. Tant qu’il y a moins de MIN_PESEES_CONCLUSION prévisions détaillées, aucun effectif
    n’est donné : un échantillon si petit ne dit pas quel facteur pèse à tort."""
    resolues = [x for x in analyses if x['a']['statut'] in ('ok', 'ko')]
    detaillees = [x for x in resolues if x['e'].get('contributions')]
    ratees = [x for x in detaillees if x['a']['statut'] == 'ko']
    vers_pronostic = compter_familles(
        [[famille_de(c) for c, v in facteurs_forts(x['e'], x['e']['pronostic']) if v > 0] for x in ratees])
    vers_resultat = compter_familles(
        [[famille_de(c) for c, v in facteurs_forts(x['e'], x['res']['issue']) if v > 0] for x in ratees])

    def liste(compte):
        return [{'famille': FAMILLES.get(f, f), 'n': n} for f, n in sorted(compte.items(), key=lambda kv: (-kv[1], kv[0]))]

    conclusion = len(detaillees) >= MIN_PESEES_CONCLUSION
    return {'detaillees': len(detaillees), 'ratees': len(ratees),
            'sans_detail': len(resolues) - len(detaillees),
            'ratees_sans_detail': sum(1 for x in resolues if x['a']['statut'] == 'ko' and not x['e'].get('contributions')),
            'seuil': MIN_PESEES_CONCLUSION, 'conclusion': conclusion,
            'vers_pronostic': liste(vers_pronostic) if conclusion else [],
            'vers_resultat': liste(vers_resultat) if conclusion else []}


def precision_probas(analyses):
    """Log-loss des probabilités annoncées sur les prévisions résolues : moyenne de −ln(probabilité donnée au résultat réel).
    Plus c’est bas, mieux les probabilités collent aux résultats ; des probabilités égales (1/3) donnent ln 3."""
    pertes = [-math.log(max(x['e']['proba'][x['res']['issue']], 1e-9)) for x in analyses
              if x['a']['statut'] in ('ok', 'ko') and 'proba' in x['e']]
    if not pertes:
        return None
    return {'n': len(pertes), 'log_loss': round(sum(pertes) / len(pertes), 3), 'hasard': round(math.log(3), 3)}


def bilan(analyses):
    """Précision sur les matchs à pronostic résolu, raisons des erreurs, facteurs signalés, et précision par tranche
    de probabilité."""
    resolus = [x for x in analyses if x['a']['statut'] in ('ok', 'ko')]
    ratés = [x for x in resolus if x['a']['statut'] == 'ko']
    ok = len(resolus) - len(ratés)
    causes, facteurs = {}, {}
    for x in ratés:
        causes[x['a']['cause']] = causes.get(x['a']['cause'], 0) + 1
        for f in x['a']['facteurs']:
            facteurs[f] = facteurs.get(f, 0) + 1
    tranches = []
    for bas, haut, libelle in TRANCHES:
        dans = [x for x in resolus if bas <= x['e']['proba'][x['e']['pronostic']] < haut]
        tranches.append({'libelle': libelle, 'n': len(dans), 'ok': sum(1 for x in dans if x['a']['statut'] == 'ok')})
    return {'resolus': len(resolus), 'ok': ok, 'ko': len(ratés),
            'precision': round(ok / len(resolus), 3) if resolus else None,
            'sans_pronostic': sum(1 for x in analyses if x['a']['statut'] == 'sans_pronostic'),
            'en_attente': sum(1 for x in analyses if x['a']['statut'] == 'attente'),
            'causes': [{'code': c, 'libelle': CAUSES[c], 'n': n}
                       for c, n in sorted(causes.items(), key=lambda kv: -kv[1])],
            'facteurs': [{'code': f, 'libelle': FACTEURS[f], 'n': n}
                         for f, n in sorted(facteurs.items(), key=lambda kv: -kv[1])],
            'tranches': tranches, 'facteurs_erreurs': facteurs_erreurs(analyses),
            'precision_probas': precision_probas(analyses)}


def libelle_pesee(code, e):
    """Libellé d’un facteur d’une prévision, avec l’équipe concernée."""
    if code == 'absences':
        mal = e.get('malus') or {}
        dom, ext = mal.get('domicile') or 0, mal.get('exterieur') or 0
        if dom < 0 and ext >= 0:
            return 'les absences de %s' % e['domicile']
        if ext < 0 and dom >= 0:
            return 'les absences de %s' % e['exterieur']
        return 'les absences des deux équipes' if dom < 0 and ext < 0 else 'les absences'
    return LIBELLES_PESEES[code].format(dom=e['domicile'], ext=e['exterieur'])


def pesees(e, issue):
    """Facteurs qui ont le plus pesé sur la probabilité du pronostic, puis sur celle du résultat réel, en points de
    probabilité (variation si ce facteur était neutre). None si la prévision n’a pas été décomposée."""
    contrib = e.get('contributions')
    if not contrib:
        return None

    def classer(etiquette):
        return [{'libelle': libelle_pesee(code, e), 'points': p} for code, p in facteurs_forts(e, etiquette)[:PESEES_MAX]]

    return {'pronostic': classer(e['pronostic']),
            'resultat': classer(issue) if issue and issue != e['pronostic'] else None}


def match_resume(x, noms):
    e, res, a = x['e'], x['res'], x['a']
    if 'ligue' in e:
        championnat = noms.get(e['ligue'], e['ligue'])
    elif e.get('hypothese'):
        championnat = 'Hors des 16 championnats (estimé)'
    else:
        championnat = 'Entre championnats'
    return {'n': e['n'], 'domicile': e['domicile'], 'exterieur': e['exterieur'], 'championnat': championnat,
            'methode': e.get('methode'), 'pronostic': e.get('pronostic'),
            'pourcent': {c: round(e['proba'][c] * 100) for c in ('1', 'N', '2')} if 'proba' in e else None,
            'score': res['score'] if res else None, 'issue': res['issue'] if res else None,
            'source': res['source'] if res else None,
            'statut': a['statut'], 'cause': a['cause'], 'cause_libelle': CAUSES.get(a['cause']),
            'explication': a['explication'], 'facteurs': [FACTEURS[f] for f in a['facteurs']],
            'reconstituee': bool(e.get('reconstituee')), 'raisons': a.get('raisons', []),
            'pesees': pesees(e, res['issue'] if res else None),
            'pesees_reconstituees': bool(e.get('contributions_reconstituees'))}


def constat_grille(matchs):
    """Constat d’une grille : bilan des pronostics résolus, raison de chaque échec, matchs sans prévision."""
    prefixe = ('Prévisions reconstituées après coup, à partir des données d’avant la clôture. '
               if any(m.get('reconstituee') for m in matchs) else '')
    resolus = [m for m in matchs if m['statut'] in ('ok', 'ko')]
    if not resolus:
        texte = 'Pas encore de résultat à comparer.'
    else:
        bons = sum(1 for m in resolus if m['statut'] == 'ok')
        texte = '%d bon(s) sur %d pronostics résolus (%d %%).' % (bons, len(resolus), round(100 * bons / len(resolus)))
        for m in resolus:
            if m['statut'] == 'ko':
                raison = m['cause_libelle'] or 'raison non déterminée'
                if m['facteurs']:
                    raison += ' ; ' + ', '.join(m['facteurs'])
                texte += ' Raté : %s – %s (%s).' % (m['domicile'], m['exterieur'], raison)
    sans = sum(1 for m in matchs if m['statut'] == 'sans_pronostic')
    if sans:
        texte += ' %d match(s) sans prévision (équipe hors de nos championnats).' % sans
    return prefixe + texte


def grilles_resumees(analyses, noms):
    """Les grilles les plus récentes, avec leurs matchs dans l’ordre de la grille."""
    groupes = {}
    for x in analyses:
        groupes.setdefault((x['e']['format'], x['e']['numero']), []).append(x)
    recentes = sorted(groupes.values(), key=lambda membres: membres[0]['e']['cloture'], reverse=True)
    liste = []
    for membres in recentes[:GRILLES_AFFICHEES]:
        membres.sort(key=lambda x: x['e']['n'])
        cloture = dt.date.fromisoformat(membres[0]['e']['cloture'][:10])
        resumes = [match_resume(x, noms) for x in membres]
        liste.append({'format': membres[0]['e']['format'], 'numero': membres[0]['e']['numero'],
                      'cloture': membres[0]['e']['cloture'], 'cloture_fr': date_fr(cloture),
                      'complete': all(x['res'] is not None for x in membres),
                      'matchs': resumes, 'constat': constat_grille(resumes)})
    return liste


def releves_pronosoft(matchs, suivies, aujourdhui):
    """Résultats relevés par Pronosoft, par grille, pour les grilles non suivies (pas de prévision enregistrée)."""
    limite = aujourdhui - dt.timedelta(days=RELEVES_JOURS)
    groupes = {}
    for m in matchs:
        vu = dt.date.fromisoformat(m['vu'])
        if vu < limite:
            continue
        try:
            a, b = (int(x) for x in m['score'].split('-'))
        except ValueError:
            continue
        issue = '1' if a > b else ('N' if a == b else '2')
        for libelle in m.get('grilles', []):
            parties = libelle.split()
            if len(parties) != 4 or parties[:2] != ['Loto', 'Foot'] or not parties[3].startswith('n'):
                continue
            try:
                cle_grille = (int(parties[2]), int(parties[3][1:]))
            except ValueError:
                continue
            if cle_grille in suivies or cle_grille[1] in GRILLES_PRIVEES:
                continue
            g = groupes.setdefault(cle_grille, {'format': cle_grille[0], 'numero': cle_grille[1], 'releve': vu, 'matchs': []})
            g['releve'] = max(g['releve'], vu)
            g['matchs'].append({'domicile': canon_pronosoft(m['domicile']), 'exterieur': canon_pronosoft(m['exterieur']), 'score': '%d – %d' % (a, b), 'issue': issue})
    liste = sorted(groupes.values(), key=lambda g: (g['releve'], g['numero']), reverse=True)[:GRILLES_AFFICHEES]
    for g in liste:
        g['releve'] = g['releve'].isoformat()
    return liste


def principal():
    maintenant = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    aujourdhui = maintenant.date()
    donnees = json.loads((DONNEES / 'donnees_publiees.json').read_text(encoding='utf-8'))
    noms = {t['ligue']: t.get('ligue_nom', t['ligue']) for t in donnees['equipes']}
    nouvelles = enregistrer_grilles(donnees, charger_grilles(), maintenant.isoformat(), aujourdhui)
    print('grilles : %d matchs nouvellement enregistrés' % len(nouvelles))
    rows = charger_championnats()
    idx_fd = index_resultats(rows) if rows else {}
    matchs_ps = charger_pronosoft()
    idx_ps = index_pronosoft(matchs_ps)
    print('résultats : %d matchs de championnats, %d relevés Pronosoft' % (
        len(rows), sum(len(v) for v in idx_ps.values())))
    analyses = []
    for e in derniere_entree(charger_jsonl(JOURNAL_GRILLES)).values():
        res = resultat_match(e, idx_fd, idx_ps)
        analyses.append({'e': e, 'res': res, 'a': analyser(e, res)})
    suivies = {(x['e']['format'], x['e']['numero']) for x in analyses}
    sortie = {'maj': maintenant.isoformat(), 'bilan': bilan(analyses), 'grilles': grilles_resumees(analyses, noms),
              'releves': releves_pronosoft(matchs_ps, suivies, aujourdhui)}
    SORTIE.write_text(json.dumps(sortie, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    b = sortie['bilan']
    print('résultats écrits : %d pronostics résolus, %d bons ; %d en attente ; %d grilles affichées' % (
        b['resolus'], b['ok'], b['en_attente'], len(sortie['grilles'])))


if __name__ == '__main__':
    principal()
