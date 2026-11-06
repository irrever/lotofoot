"""Pronosoft : repérage des pages de résultats du Loto Foot et des coupes d’Europe.

Lecture seule : robots.txt respecté, une page toutes les sept secondes. Le diagnostic n’affiche que les règles
d’accès, les adresses, la structure des pages et les équipes avec leurs scores ; il n’enregistre rien.

Usage : python3 src/pronosoft.py collecter   (relève les scores des grilles du Loto Foot, données/resultats/pronosoft.json)
        python3 src/pronosoft.py loto | decouverte   (affichage seul)
"""
import datetime as dt
import json
import pathlib
import re
import sys
import time
import urllib.request
import urllib.robotparser

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from footactu import Noeud, _chaine, arbre, descendants, texte, textes_avec_chemin  # noqa: E402

SITE = 'https://www.pronosoft.com'
UA = 'Lotofoot-analyse/1.0 (usage personnel, une lecture par jour)'
PAUSE = 7
PAGE_LOTO = '/fr/lotofoot/resultats-et-rapports.php'
SORTIE_LOTO = pathlib.Path(__file__).resolve().parent.parent / 'data' / 'resultats' / 'pronosoft.json'
SCORE_DANS_TEXTE = re.compile(r'\d{1,2}\s*[-–]\s*\d{1,2}')
LIBELLE_GRILLE = re.compile(r'Loto Foot (\d+) n(\d+)')


class Lecteur:
    def __init__(self, site):
        self.site = site
        self.robots = urllib.robotparser.RobotFileParser()
        self.robots.set_url(site + '/robots.txt')
        self.derniere = 0.0

    def brut(self, chemin):
        req = urllib.request.Request(self.site + chemin, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=60) as rep:
            return rep.read().decode('utf-8', errors='ignore')

    def lire(self, chemin):
        self.robots.read()
        if not self.robots.can_fetch(UA, self.site + chemin):
            raise PermissionError('interdit par robots.txt : ' + chemin)
        attente = PAUSE - (time.time() - self.derniere)
        if attente > 0:
            time.sleep(attente)
        self.derniere = time.time()
        return self.brut(chemin)


def chemins_de(html):
    """Adresses internes d’une page (sans domaine, paramètres ni ancre)."""
    out = set()
    for href in re.findall(r'href="([^"]+)"', html):
        href = re.sub(r'^https?://(www\.)?pronosoft\.com', '', href)
        if href.startswith('/') and not href.startswith('//'):
            out.add(href.split('?')[0].split('#')[0])
    return out


def decouverte(lecteur):
    robots = lecteur.brut('/robots.txt')
    print('robots.txt : règles d’accès (lignes utiles)')
    for ligne in robots.splitlines():
        ligne = ligne.strip()
        if ligne and ligne.lower().startswith(('user-agent', 'allow', 'disallow', 'sitemap', 'crawl-delay')):
            print('  ' + ligne[:120])
    accueil = lecteur.lire('/')
    liens = chemins_de(accueil)
    utiles = sorted(l for l in liens if re.search(r'loto|resultat|champion|europa|coupe|grille|pronostic', l.lower()))
    print('accueil : %d liens ; utiles (%d) : %s' % (len(liens), len(utiles), ', '.join(utiles[:80]) or 'aucun'))
    cibles = [l for l in utiles if re.search(r'resultat', l.lower())][:2]
    if not cibles:
        cibles = [l for l in utiles if re.search(r'loto', l.lower())][:1]
    for chemin in cibles:
        html = lecteur.lire(chemin)
        racine = arbre(html)
        print('== %s (%d caractères)' % (chemin, len(html)))
        tableaux = [n for n in descendants(racine) if n.tag == 'table']
        avec_score = [(t, ch) for t, ch in textes_avec_chemin(racine) if SCORE_DANS_TEXTE.search(t)]
        print('  tableaux : %d ; textes contenant un score : %d' % (len(tableaux), len(avec_score)))
        for t, ch in avec_score[:2]:
            print('  texte « %s »' % t.strip()[:70])
            print('    ancêtres : ' + ' > '.join(n.tag + ''.join('.' + c for c in sorted(n.classes))
                                                   for n in ch[-6:]))
        for i, t in enumerate(tableaux[:2], 1):
            lignes = [n for n in descendants(t) if n.tag == 'tr']
            entetes = [texte(n)[:20] for n in descendants(t) if n.tag == 'th']
            print('  tableau %d : %d lignes ; en-têtes : %s' % (i, len(lignes), ' | '.join(entetes[:10]) or 'aucun'))
            donnees = [tr for tr in lignes if any(isinstance(c, Noeud) and c.tag == 'td' for c in tr.enfants)]
            for k, tr in enumerate(donnees[:2], 1):
                print('    ligne %d' % k)
                _chaine(tr, '      ', [40])


def lire_loto(html):
    """Grilles de la page « Résultats et rapports » du Loto Foot : libellé, puis matchs avec leur score final."""
    grilles, titre = [], ''

    def marcher(n):
        nonlocal titre
        for e in n.enfants:
            if isinstance(e, Noeud):
                if e.tag == 'table':
                    matchs = []
                    for tr in descendants(e):
                        if tr.tag != 'tr':
                            continue
                        dom = ext = score = None
                        for c in descendants(tr):
                            if c.tag == 'td' and 'equipe1' in c.classes:
                                dom = texte(c)
                            elif c.tag == 'td' and 'equipe2' in c.classes:
                                ext = texte(c)
                            elif c.tag == 'span' and 'score-ft' in c.classes:
                                score = texte(c)
                        if dom and ext and score and re.match(r'^\d{1,2}-\d{1,2}$', score):
                            a, b = score.split('-')
                            matchs.append({'domicile': dom, 'exterieur': ext, 'score': score,
                                           'issue': '1' if int(a) > int(b) else ('N' if a == b else '2')})
                    if matchs:
                        grilles.append({'libelle': titre, 'matchs': matchs})
                else:
                    marcher(e)
            else:
                if re.search(r'loto|grille|n°|numéro', e, re.I) and len(e.strip()) < 120:
                    titre = ' '.join(e.split())

    marcher(arbre(html))
    return grilles


def fusionner_loto(existants, grilles, aujourdhui):
    """Ajoute les matchs lus aux relevés déjà enregistrés. Un match est identifié par ses équipes et son score ; sa date
    est celle de son premier relevé. Renvoie la liste triée et le nombre de matchs nouveaux."""
    par_cle = {(m['domicile'], m['exterieur'], m['score']): m for m in existants}
    nouveaux = 0
    for g in grilles:
        for m in g['matchs']:
            cle = (m['domicile'], m['exterieur'], m['score'])
            if cle not in par_cle:
                par_cle[cle] = {'domicile': m['domicile'], 'exterieur': m['exterieur'], 'score': m['score'],
                                'vu': aujourdhui, 'grilles': []}
                nouveaux += 1
            if g['libelle'] not in par_cle[cle]['grilles']:
                par_cle[cle]['grilles'].append(g['libelle'])
    return sorted(par_cle.values(), key=lambda m: (m['vu'], m['domicile'], m['exterieur'])), nouveaux


def grilles_par_numero(grilles, jour):
    """Grilles lues sur la page, par numéro (« 7-138 »). Chaque match garde sa position dans la grille : le résultat
    est retrouvé par le numéro de la grille et la position, pas par les noms des équipes."""
    par_numero = {}
    for g in grilles:
        m = LIBELLE_GRILLE.search(g['libelle'])
        if not m:
            continue
        par_numero['%s-%s' % (m.group(1), m.group(2))] = {
            'libelle': g['libelle'], 'maj': jour,
            'matchs': [{'domicile': x['domicile'], 'exterieur': x['exterieur'], 'score': x['score'],
                        'issue': x['issue']} for x in g['matchs']]}
    return par_numero


def fusionner_grilles(existantes, relevees):
    """Une grille relue remplace sa version précédente ; une grille absente de la page garde ses résultats."""
    return {**existantes, **relevees}


def collecter(lecteur, sortie=SORTIE_LOTO, aujourdhui=None):
    """Relève la page « Résultats et rapports » du Loto Foot et ajoute les scores au fichier de relevés."""
    jour = (aujourdhui or dt.datetime.now(dt.timezone.utc).date()).isoformat()
    grilles = lire_loto(lecteur.lire(PAGE_LOTO))
    existants = json.loads(sortie.read_text(encoding='utf-8'))['matchs'] if sortie.exists() else []
    matchs, nouveaux = fusionner_loto(existants, grilles, jour)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps({'maj': jour, 'source': 'Pronosoft, Loto Foot, résultats et rapports',
                                  'matchs': matchs}, ensure_ascii=False, indent=1), encoding='utf-8')
    # Résultats par grille : le fichier garde les grilles déjà relevées, même quand elles ont quitté la page
    grilles_sortie = sortie.with_name('grilles_pronosoft.json')
    anciennes = json.loads(grilles_sortie.read_text(encoding='utf-8'))['grilles'] if grilles_sortie.exists() else {}
    par_numero = fusionner_grilles(anciennes, grilles_par_numero(grilles, jour))
    grilles_sortie.write_text(json.dumps({'maj': jour, 'source': 'Pronosoft, Loto Foot, résultats et rapports',
                                          'grilles': par_numero}, ensure_ascii=False, indent=1), encoding='utf-8')
    print('Pronosoft : %d grilles lues, %d matchs enregistrés, %d nouveaux, %d grilles numérotées' % (
        len(grilles), len(matchs), nouveaux, len(par_numero)))
    return grilles


if __name__ == '__main__':
    commande = sys.argv[1] if len(sys.argv) > 1 else 'decouverte'
    if commande == 'decouverte':
        decouverte(Lecteur(SITE))
    elif commande == 'collecter':
        collecter(Lecteur(SITE))
    elif commande == 'loto':
        grilles = lire_loto(Lecteur(SITE).lire(PAGE_LOTO))
        print('grilles lues : %d' % len(grilles))
        for g in grilles:
            print('- %s : %d matchs' % (g['libelle'][:90], len(g['matchs'])))
            for m in g['matchs'][:2]:
                print('    %s – %s : %s (%s)' % (m['domicile'], m['exterieur'], m['score'], m['issue']))
    else:
        print(__doc__)
        sys.exit(2)
