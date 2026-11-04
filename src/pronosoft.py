"""Pronosoft : repérage des pages de résultats du Loto Foot et des coupes d’Europe.

Lecture seule : robots.txt respecté, une page toutes les sept secondes. Le diagnostic n’affiche que les règles
d’accès, les adresses, la structure des pages et les équipes avec leurs scores ; il n’enregistre rien.

Usage : python3 src/pronosoft.py decouverte
"""
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
SCORE_DANS_TEXTE = re.compile(r'\d{1,2}\s*[-–]\s*\d{1,2}')


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


if __name__ == '__main__':
    commande = sys.argv[1] if len(sys.argv) > 1 else 'decouverte'
    if commande == 'decouverte':
        decouverte(Lecteur(SITE))
    else:
        print(__doc__)
        sys.exit(2)
