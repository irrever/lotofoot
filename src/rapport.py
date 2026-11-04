"""Rapport des matchs de la veille et suivi des grilles Loto Foot.

- Grilles : chaque match des grilles ouvertes (grilles/loto-foot-*.json) reçoit la probabilité du modèle, enregistrée
  une seule fois, avant la clôture (data/journal/grilles.jsonl). Une fois le match joué, il est jugé.
- Rapport quotidien : les matchs joués la veille dans nos 16 championnats, avec la prévision enregistrée quand elle
  existe, le verdict et le bilan du jour (rapports/jour-AAAA-MM-JJ.md).
- Visuel : rapports/grilles.html, toutes les grilles suivies avec leurs pronostics, leurs résultats et la précision.

Les probabilités reprennent la formule de l’application, à partir des données publiées (data/donnees_publiees.json).
Sans données de résultats (exécution hors publication), seules les nouvelles prévisions de grille sont enregistrées
et le visuel est mis à jour.

Usage : python3 src/rapport.py
"""
import datetime as dt
import html
import json
import math
import pathlib
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent
DONNEES = RACINE / 'data'
GRILLES = RACINE / 'grilles'
GRILLES_PRIVEES = {153}  # grille personnelle : exclue de toutes les sorties publiées (demande initiale)
JOURNAL_GRILLES = DONNEES / 'journal' / 'grilles.jsonl'
RAPPORTS = RACINE / 'rapports'
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


def charger_grilles():
    """Toutes les grilles présentes dans grilles/ : format, numéro, clôture et matchs."""
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
            nouvelles.append({**base, 'ligue': t_h['ligue'], 'ligue_nom': t_h.get('ligue_nom', t_h['ligue']),
                              'proba': {ETIQ[c]: round(p[c], 6) for c in ORDRE},
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
    """Résultat du match joué à moins de FENETRE_JOURS jours de date_ref, ou None."""
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


def rapport_du_jour(rows, journal, entrees_grilles, aujourdhui):
    """Matchs joués la veille, avec la prévision enregistrée quand elle existe. Écrit rapports/jour-*.md."""
    veille = aujourdhui - dt.timedelta(days=1)
    idx = index_resultats(rows)
    joues = sorted({(r['league'], r['home'], r['away'], r['date'], r['result'], int(r['hg']), int(r['ag']))
                    for r in rows if r['date'] == veille and r['result'] in ORDRE
                    and r['hg'] not in (None, '') and r['ag'] not in (None, '')})
    freq = frequences(rows)
    lignes, ll_modele, ll_ref, ok, surprises, avec_absences = [], [], [], 0, [], []
    for ligue, dom, ext, d, res, hg, ag in joues:
        prevu = None
        for e in journal:
            if e['ligue'] == ligue and e['domicile'] == dom and e['exterieur'] == ext and e['date'] == d.isoformat():
                prevu = e
        if prevu is None:
            for e in entrees_grilles:
                if e.get('ligue') == ligue and e['domicile'] == dom and e['exterieur'] == ext:
                    if resultat_de(idx, ligue, dom, ext, dt.date.fromisoformat(e['cloture'][:10])) is not None:
                        prevu = e
        verdict = '—'
        if prevu and 'proba' in prevu:
            p = {c: prevu['proba'][ETIQ[c]] for c in ORDRE}
            ll_modele.append(-math.log(max(p[res], 1e-9)))
            ll_ref.append(-math.log(freq[res]))
            juste = prevu['pronostic'] == ETIQ[res]
            ok += juste
            verdict = '✓' if juste else '✗'
            if p[res] < SEUIL_SURPRISE:
                surprises.append((ligue, dom, ext, p[res]))
            if prevu.get('malus', {}).get('domicile') or prevu.get('malus', {}).get('exterieur'):
                avec_absences.append((ligue, dom, ext, prevu['malus']))
            prevu_txt = '%s (%s)' % (prevu['pronostic'], ' · '.join(
                '%s %d %%' % (ETIQ[c], round(p[c] * 100)) for c in ORDRE))
        else:
            prevu_txt = 'pas de prévision enregistrée'
        lignes.append('| %s | %s – %s | %d – %d (%s) | %s | %s |' % (
            ligue, dom, ext, hg, ag, {'H': 'victoire domicile', 'D': 'nul', 'A': 'victoire extérieur'}[res],
            prevu_txt, verdict))
    n_pred = len(ll_modele)
    md = ['# Matchs du %s' % date_fr(veille), '',
          'Matchs joués la veille dans nos 16 championnats : **%d**, dont **%d** avec une prévision enregistrée avant le '
          'match.' % (len(joues), n_pred), '']
    if joues:
        md += ['| Championnat | Match | Résultat | Prévu | Verdict |', '|---|---|---|---|---|'] + lignes + ['']
    if n_pred:
        md += ['## Bilan du jour', '',
               '- Précision : **%d / %d** (%d %%).' % (ok, n_pred, round(100 * ok / n_pred)),
               '- Log-loss du modèle : **%.3f** ; référence constante (fréquences de la saison) : **%.3f**.' % (
                   sum(ll_modele) / n_pred, sum(ll_ref) / n_pred), '']
        if surprises:
            md += ['## Résultats surprenants', '']
            md += ['- %s : %s – %s, résultat jugé à %d %%.' % (l, d_, e_, round(p * 100))
                   for l, d_, e_, p in surprises]
            md += ['']
        if avec_absences:
            md += ['## Absences prises en compte', '']
            md += ['- %s : %s – %s (malus Elo domicile %d, extérieur %d).' % (
                l, d_, e_, m['domicile'], m['exterieur']) for l, d_, e_, m in avec_absences]
            md += ['']
    else:
        md += ['Aucune prévision enregistrée pour ces matchs : rien à comparer.', '']
    md += ['---', 'Une prévision n’est comparée que si elle a été enregistrée avant le match. Un match de quelques '
           'jours ne mesure pas la qualité du modèle : seul le total sur la saison le fait (bilan).', '']
    RAPPORTS.mkdir(parents=True, exist_ok=True)
    (RAPPORTS / ('jour-%s.md' % veille.isoformat())).write_text('\n'.join(md), encoding='utf-8')
    print('rapport du %s : %d matchs joués, %d avec prévision' % (veille.isoformat(), len(joues), n_pred))


CSS = """
:root { --fond:#f6f7f9; --carte:#fff; --texte:#1d2330; --discret:#6b7385; --bord:#e3e6ec;
  --ok:#1f8a4c; --ko:#c2412d; --attente:#8a92a3; --b1:#2f6fdb; --bn:#9aa3b5; --b2:#e0883a; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --fond:#12151c; --carte:#1b202b; --texte:#e8ebf2;
  --discret:#9aa3b5; --bord:#2a3140; --ok:#3fbf73; --ko:#f0705a; --attente:#7d8699; --b1:#5b8fea; --bn:#6d7587; --b2:#f0a05a; } }
:root[data-theme="dark"] { --fond:#12151c; --carte:#1b202b; --texte:#e8ebf2; --discret:#9aa3b5; --bord:#2a3140;
  --ok:#3fbf73; --ko:#f0705a; --attente:#7d8699; --b1:#5b8fea; --bn:#6d7587; --b2:#f0a05a; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--fond); color: var(--texte); font: 15px/1.45 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 17px; margin: 28px 0 4px; }
.sous, .discret { color: var(--discret); font-size: 13px; }
.resume { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 18px 0 6px; }
.tuile { background: var(--carte); border: 1px solid var(--bord); border-radius: 10px; padding: 12px 14px; }
.tuile strong { display: block; font-size: 22px; } .tuile span { color: var(--discret); font-size: 12px; }
.matchs { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; margin-top: 8px; }
.match { background: var(--carte); border: 1px solid var(--bord); border-left: 5px solid var(--attente); border-radius: 10px; padding: 10px 12px; }
.match.ok { border-left-color: var(--ok); } .match.ko { border-left-color: var(--ko); }
.tete { display: flex; justify-content: space-between; color: var(--discret); font-size: 12px; }
.equipes { font-weight: 650; margin: 4px 0 6px; }
.equipes .vs { color: var(--discret); font-weight: 400; margin: 0 6px; }
.prono { font-size: 13px; } .prono strong { font-size: 15px; }
.barre { display: flex; height: 6px; border-radius: 3px; overflow: hidden; margin: 5px 0 6px; background: var(--bord); }
.barre i { display: block; height: 100%; } .b1 { background: var(--b1); } .bn { background: var(--bn); } .b2 { background: var(--b2); }
.resultat { font-size: 13px; color: var(--discret); } .resultat b { color: var(--texte); }
.non-prevu { opacity: .75; }
"""


def page_grilles(entrees, idx, maintenant, noms_ligues):
    """Visuel : grilles suivies, pronostics, résultats et précision (rapports/grilles.html)."""
    groupes = {}
    for e in entrees:
        groupes.setdefault((e['format'], e['numero']), []).append(e)
    total = ok = attente = 0
    vus = set()
    cartes = []
    for (fmt, numero), liste in sorted(groupes.items(), key=lambda kv: (-kv[0][1], kv[0][0])):
        liste.sort(key=lambda e: e['n'])
        blocs = []
        for e in liste:
            if 'non_prevu' in e:
                blocs.append('<article class="match non-prevu"><div class="tete"><span>%d</span><span>hors suivi</span>'
                             '</div><div class="equipes">%s<span class="vs">–</span>%s</div><div class="resultat">%s'
                             '</div></article>' % (e['n'], html.escape(e['domicile']), html.escape(e['exterieur']),
                                                  html.escape(e['non_prevu'])))
                continue
            res = resultat_de(idx, e['ligue'], e['domicile'], e['exterieur'], dt.date.fromisoformat(e['cloture'][:10]))
            p = {c: e['proba'][ETIQ[c]] for c in ORDRE}
            barre = ''.join('<i class="%s" style="width:%.1f%%"></i>' % (cl, p[c] * 100)
                            for c, cl in (('H', 'b1'), ('D', 'bn'), ('A', 'b2')))
            if res is None:
                classe, pied = 'attente', '<b>à venir</b>'
                attente += 1
            else:
                d, r, hg, ag = res
                juste = e['pronostic'] == ETIQ[r]
                cle = (e['ligue'], e['domicile'], e['exterieur'], d)
                if cle not in vus:
                    vus.add(cle)
                    total += 1
                    ok += juste
                classe = 'ok' if juste else 'ko'
                pied = '<b>%d – %d</b> · %s' % (hg, ag, '✓ prévu' if juste else '✗ manqué')
            blocs.append('<article class="match %s"><div class="tete"><span>%d</span><span>%s</span></div>'
                         '<div class="equipes">%s<span class="vs">–</span>%s</div>'
                         '<div class="prono">Pronostic <strong>%s</strong> · 1 %d %% · N %d %% · 2 %d %%'
                         '<div class="barre">%s</div></div><div class="resultat">%s</div></article>' % (
                             classe, e['n'], html.escape(noms_ligues.get(e['ligue'], e['ligue'])),
                             html.escape(e['domicile']),
                             html.escape(e['exterieur']), e['pronostic'], round(p['H'] * 100), round(p['D'] * 100),
                             round(p['A'] * 100), barre, pied))
        date_c = dt.datetime.fromisoformat(liste[0]['cloture']).strftime('%d/%m/%Y à %H h %M')
        cartes.append('<h2>Loto Foot %d · grille N°%d</h2><p class="discret">Clôture : %s</p>'
                      '<div class="matchs">%s</div>' % (fmt, numero, date_c, ''.join(blocs)))
    precision = '%d / %d (%d %%)' % (ok, total, round(100 * ok / total)) if total else 'pas encore de match joué'
    corps = ('<main><h1>Précision des grilles Loto Foot</h1>'
             '<p class="sous">Mis à jour le %s. Pronostic = issue la plus probable du modèle, enregistrée avant la clôture.'
             '</p><section class="resume"><div class="tuile"><strong>%s</strong><span>précision sur les matchs joués</span>'
             '</div><div class="tuile"><strong>%d</strong><span>matchs joués</span></div>'
             '<div class="tuile"><strong>%d</strong><span>matchs à venir</span></div></section>%s</main>') % (
        maintenant.strftime('%d/%m/%Y à %H h %M UTC'), precision, total, attente, ''.join(cartes))
    RAPPORTS.mkdir(parents=True, exist_ok=True)
    (RAPPORTS / 'grilles.html').write_text(
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Lotofoot · grilles</title><style>%s</style></head><body>%s</body></html>' % (CSS, corps),
        encoding='utf-8')
    print('visuel des grilles : %d matchs joués, précision %s, %d à venir' % (total, precision, attente))


def principal():
    maintenant = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    aujourdhui = maintenant.date()
    donnees = json.loads((DONNEES / 'donnees_publiees.json').read_text(encoding='utf-8'))
    grilles = charger_grilles()
    nouvelles = enregistrer_grilles(donnees, grilles, maintenant.isoformat())
    print('grilles : %d matchs nouvellement enregistrés' % len(nouvelles))
    rows = []
    try:
        sys.path.insert(0, str(RACINE / 'src'))
        from load import load_all
        rows = load_all() if (DONNEES / 'raw').exists() else []
    except Exception as e:  # sans données de résultats, seule la mise en page des grilles est mise à jour
        print('résultats indisponibles :', type(e).__name__)
    entrees = charger_jsonl(JOURNAL_GRILLES)
    if rows:
        idx = index_resultats(rows)
        rapport_du_jour(rows, charger_jsonl(DONNEES / 'journal' / 'predictions.jsonl'), entrees, aujourdhui)
    else:
        idx = {}
        print('pas de données de résultats : rapport du jour non produit')
    noms_ligues = {t['ligue']: t.get('ligue_nom', t['ligue']) for t in donnees['equipes']}
    page_grilles(entrees, idx, maintenant, noms_ligues)


if __name__ == '__main__':
    principal()
