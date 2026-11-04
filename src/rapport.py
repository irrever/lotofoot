"""Rapport des matchs de la veille et suivi des grilles Loto Foot.

Sorties :
- data/resultats.json : ce que l’onglet « Résultats » de l’application affiche (matchs de la veille, précision
  des grilles) ;
- rapports/jour-AAAA-MM-JJ.md : le rapport de la veille, en texte, pour l’archive ;
- data/journal/grilles.jsonl : la probabilité de chaque match des grilles ouvertes, enregistrée une seule fois,
  avant la clôture.

Les probabilités reprennent la formule de l’application, à partir de data/donnees_publiees.json.
Sans données de résultats (exécution hors publication), seules les prévisions de grille et resultats.json sont
mis à jour. Usage : python3 src/rapport.py (lancé par boucle.sh, après bilan.py et avant la construction du site).
"""
import datetime as dt
import json
import math
import pathlib
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent
DONNEES = RACINE / 'data'
GRILLES = RACINE / 'grilles'
RAPPORTS = RACINE / 'rapports'
JOURNAL = DONNEES / 'journal' / 'predictions.jsonl'
JOURNAL_GRILLES = DONNEES / 'journal' / 'grilles.jsonl'
SORTIE = DONNEES / 'resultats.json'
GRILLES_PRIVEES = {153}    # grille personnelle : exclue de toutes les sorties (demande initiale)
GRILLES_AFFICHEES = 12     # les grilles les plus récentes dans l’onglet
ORDRE = ['H', 'D', 'A']
ETIQ = {'H': '1', 'D': 'N', 'A': '2'}
FENETRE_JOURS = 3          # tolérance entre la date de clôture d’une grille et la date du match joué
SEUIL_SURPRISE = 0.25      # résultat jugé surprenant si le modèle lui donnait moins de 25 %
MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
        'septembre', 'octobre', 'novembre', 'décembre']


def date_fr(d):
    return ('1er' if d.day == 1 else str(d.day)) + ' ' + MOIS[d.month - 1] + ' ' + str(d.year)


def malus(t):
    return (t.get('absences') or {}).get('malus', 0)


def proba_match(h, a, modele, ecart_elo):
    """Probabilités 1 / N / 2 : même calcul que l’application (les 25 variables du modèle)."""
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


def noms_ligues(donnees):
    return {t['ligue']: t.get('ligue_nom', t['ligue']) for t in donnees['equipes']}


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


def charger_jsonl(chemin):
    if not chemin.exists():
        return []
    with open(chemin, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def enregistrer_grilles(donnees, grilles, maintenant):
    """Ajoute au journal des grilles les matchs jamais enregistrés. Les lignes existantes ne sont pas modifiées."""
    deja = {e['id'] for e in charger_jsonl(JOURNAL_GRILLES)}
    par_nom = {}
    for t in donnees['equipes']:
        par_nom.setdefault(t['equipe'], []).append(t)
    nouvelles = []
    for g in grilles:
        date_cloture = g['cloture'][:10]
        for n, m in enumerate(g['matchs'], 1):
            cle = '%s|%s|%s' % (date_cloture, m['domicile'], m['exterieur'])
            if cle in deja:
                continue
            deja.add(cle)
            base = {'id': cle, 'enregistree_le': maintenant, 'format': g['format'], 'numero': g['numero'], 'n': n,
                    'cloture': g['cloture'], 'date': date_cloture, 'domicile': m['domicile'],
                    'exterieur': m['exterieur']}
            hs = par_nom.get(m['domicile'], [])
            as_ = par_nom.get(m['exterieur'], [])
            if not hs or not as_:
                nouvelles.append({**base, 'non_prevu': 'équipe hors des 16 championnats suivis'})
                continue
            paires = [(h, a) for h in hs for a in as_ if h['ligue'] == a['ligue']]
            if not paires:
                nouvelles.append({**base, 'non_prevu': 'équipes de championnats différents'})
                continue
            t_h, t_a = paires[0]
            ecart = (t_h['vec']['elo'] + malus(t_h)) - (t_a['vec']['elo'] + malus(t_a))
            p = proba_match(t_h, t_a, donnees['modele'], ecart)
            nouvelles.append({**base, 'ligue': t_h['ligue'], 'proba': {ETIQ[c]: round(p[c], 6) for c in ORDRE},
                              'pronostic': ETIQ[max(ORDRE, key=lambda c: p[c])],
                              'ecart_elo': round(ecart, 1),
                              'malus': {'domicile': malus(t_h), 'exterieur': malus(t_a)}})
    if nouvelles:
        JOURNAL_GRILLES.parent.mkdir(parents=True, exist_ok=True)
        with open(JOURNAL_GRILLES, 'a', encoding='utf-8') as f:
            for e in nouvelles:
                f.write(json.dumps(e, ensure_ascii=False) + '\n')
    return nouvelles


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


def frequences(rows):
    jouees = [r['result'] for r in rows if r['result'] in ORDRE]
    total = len(jouees) or 1
    return {c: max(jouees.count(c), 1) / total for c in ORDRE}


def jour_de_la_veille(rows, journal, entrees_grilles, idx, noms, aujourdhui):
    """Matchs joués la veille dans nos championnats, avec la prévision enregistrée quand elle existe."""
    veille = aujourdhui - dt.timedelta(days=1)
    joues = sorted({(r['league'], r['home'], r['away'], r['date'], r['result'], int(r['hg']), int(r['ag']))
                    for r in rows if r['date'] == veille and r['result'] in ORDRE
                    and r['hg'] not in (None, '') and r['ag'] not in (None, '')})
    freq = frequences(rows)
    matchs, ll_modele, ll_ref, ok = [], [], [], 0
    for ligue, dom, ext, d, res, hg, ag in joues:
        prevu = next((e for e in journal if e['ligue'] == ligue and e['domicile'] == dom and e['exterieur'] == ext
                      and e['date'] == d.isoformat()), None)
        if prevu is None:
            prevu = next((e for e in entrees_grilles if 'proba' in e and e['ligue'] == ligue
                          and e['domicile'] == dom and e['exterieur'] == ext
                          and abs((dt.date.fromisoformat(e['cloture'][:10]) - d).days) <= FENETRE_JOURS), None)
        m = {'championnat': noms.get(ligue, ligue), 'domicile': dom, 'exterieur': ext, 'score': '%d – %d' % (hg, ag),
             'issue': ETIQ[res], 'prevu': None, 'pourcent': None, 'verdict': None, 'surprise': False,
             'absences': None}
        if prevu is not None and 'proba' in prevu:
            p = {c: prevu['proba'][ETIQ[c]] for c in ORDRE}
            juste = prevu['pronostic'] == ETIQ[res]
            ll_modele.append(-math.log(max(p[res], 1e-9)))
            ll_ref.append(-math.log(freq[res]))
            ok += juste
            m.update({'prevu': prevu['pronostic'], 'pourcent': {ETIQ[c]: round(p[c], 4) for c in ORDRE},
                      'verdict': 'ok' if juste else 'ko', 'surprise': p[res] < SEUIL_SURPRISE})
            mal = prevu.get('malus') or {}
            if mal.get('domicile') or mal.get('exterieur'):
                m['absences'] = {'domicile': mal.get('domicile', 0), 'exterieur': mal.get('exterieur', 0)}
        matchs.append(m)
    n = len(ll_modele)
    return {'date': veille.isoformat(), 'joues': len(joues), 'avec_prevision': n,
            'precision': {'ok': ok, 'n': n} if n else None,
            'log_loss': round(sum(ll_modele) / n, 4) if n else None,
            'log_loss_ref': round(sum(ll_ref) / n, 4) if n else None,
            'matchs': matchs}


def markdown_jour(jour):
    veille = dt.date.fromisoformat(jour['date'])
    md = ['# Matchs du %s' % date_fr(veille), '',
          'Matchs joués la veille dans nos 16 championnats : **%d**, dont **%d** avec une prévision enregistrée avant le '
          'match.' % (jour['joues'], jour['avec_prevision']), '']
    if jour['matchs']:
        md += ['| Championnat | Match | Résultat | Prévu | Verdict |', '|---|---|---|---|---|']
        for m in jour['matchs']:
            prevu = ('%s (%s)' % (m['prevu'], ' · '.join('%s %d %%' % (c, round(m['pourcent'][c] * 100))
                                                        for c in ('1', 'N', '2')))) if m['prevu'] else 'pas de prévision'
            md.append('| %s | %s – %s | %s (%s) | %s | %s |' % (
                m['championnat'], m['domicile'], m['exterieur'], m['score'], ISSUE_TXT[m['issue']], prevu,
                {'ok': '✓', 'ko': '✗'}.get(m['verdict'], '—')))
        md.append('')
    if jour['precision']:
        p = jour['precision']
        md += ['## Bilan du jour', '',
               '- Précision : **%d / %d** (%d %%).' % (p['ok'], p['n'], round(100 * p['ok'] / p['n'])),
               '- Log-loss du modèle : **%.3f** ; référence constante (fréquences de la saison) : **%.3f**.' % (
                   jour['log_loss'], jour['log_loss_ref']), '']
        surprises = [m for m in jour['matchs'] if m['surprise']]
        if surprises:
            md += ['## Résultats surprenants', '']
            md += ['- %s : %s – %s, résultat jugé à %d %%.' % (
                m['championnat'], m['domicile'], m['exterieur'], round(m['pourcent'][m['issue']] * 100))
                for m in surprises]
            md.append('')
    else:
        md += ['Aucune prévision enregistrée pour ces matchs : rien à comparer.', '']
    md += ['---', 'Une prévision n’est comparée que si elle a été enregistrée avant le match. Un match de quelques '
           'jours ne mesure pas la qualité du modèle : seul le total sur la saison le fait (bilan).', '']
    return '\n'.join(md)


ISSUE_TXT = {'1': 'victoire domicile', 'N': 'match nul', '2': 'victoire extérieur'}


def grilles_resume(entrees, idx, noms):
    """Grilles suivies : précision sur tous les matchs joués (dédoublonnée), et les grilles les plus récentes."""
    groupes = {}
    for e in entrees:
        groupes.setdefault((e['format'], e['numero']), []).append(e)
    vus, a_venir, ok, total = set(), set(), 0, 0
    for e in entrees:
        if 'proba' not in e:
            continue
        res = resultat_de(idx, e['ligue'], e['domicile'], e['exterieur'], dt.date.fromisoformat(e['cloture'][:10]))
        if res is None:
            a_venir.add(e['id'])
            continue
        cle = (e['ligue'], e['domicile'], e['exterieur'], res[0])
        if cle not in vus:
            vus.add(cle)
            total += 1
            ok += e['pronostic'] == ETIQ[res[1]]
    recentes = sorted(groupes.items(), key=lambda kv: kv[1][0]['cloture'], reverse=True)[:GRILLES_AFFICHEES]
    liste = []
    for (fmt, numero), membres in recentes:
        matchs = []
        for e in sorted(membres, key=lambda x: x['n']):
            base = {'n': e['n'], 'championnat': noms.get(e.get('ligue', ''), e.get('ligue', '')),
                    'domicile': e['domicile'], 'exterieur': e['exterieur']}
            if 'non_prevu' in e:
                matchs.append({**base, 'non_prevu': e['non_prevu']})
                continue
            res = resultat_de(idx, e['ligue'], e['domicile'], e['exterieur'], dt.date.fromisoformat(e['cloture'][:10]))
            m = {**base, 'pronostic': e['pronostic'], 'pourcent': {ETIQ[c]: round(e['proba'][ETIQ[c]], 4)
                                                                  for c in ORDRE},
                 'score': None, 'verdict': None}
            if res is not None:
                m['score'] = '%d – %d' % (res[2], res[3])
                m['verdict'] = 'ok' if e['pronostic'] == ETIQ[res[1]] else 'ko'
            matchs.append(m)
        liste.append({'format': fmt, 'numero': numero, 'cloture': membres[0]['cloture'], 'matchs': matchs})
    return {'precision': {'ok': ok, 'n': total}, 'a_venir': len(a_venir), 'liste': liste}


def principal():
    maintenant = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    aujourdhui = maintenant.date()
    donnees = json.loads((DONNEES / 'donnees_publiees.json').read_text(encoding='utf-8'))
    noms = noms_ligues(donnees)
    nouvelles = enregistrer_grilles(donnees, charger_grilles(), maintenant.isoformat())
    print('grilles : %d matchs nouvellement enregistrés' % len(nouvelles))
    rows = []
    try:
        sys.path.insert(0, str(RACINE / 'src'))
        from load import load_all
        rows = load_all() if (DONNEES / 'raw').exists() else []
    except Exception as e:  # sans données de résultats, seules les grilles sont mises à jour
        print('résultats indisponibles :', type(e).__name__)
    entrees = charger_jsonl(JOURNAL_GRILLES)
    idx = index_resultats(rows) if rows else {}
    jour = None
    if rows:
        jour = jour_de_la_veille(rows, charger_jsonl(JOURNAL), entrees, idx, noms, aujourdhui)
        RAPPORTS.mkdir(parents=True, exist_ok=True)
        (RAPPORTS / ('jour-%s.md' % jour['date'])).write_text(markdown_jour(jour), encoding='utf-8')
        print('rapport du %s : %d matchs joués, %d avec prévision' % (jour['date'], jour['joues'], jour['avec_prevision']))
    else:
        print('pas de données de résultats : rapport du jour non produit')
    resultats = {'maj': maintenant.isoformat(), 'jour': jour, 'grilles': grilles_resume(entrees, idx, noms)}
    SORTIE.write_text(json.dumps(resultats, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    g = resultats['grilles']
    print('résultats écrits : précision des grilles %d / %d, %d matchs à venir, %d grilles affichées' % (
        g['precision']['ok'], g['precision']['n'], g['a_venir'], len(g['liste'])))


if __name__ == '__main__':
    principal()
