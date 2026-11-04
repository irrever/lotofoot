"""Relève chaque jour sur foot-actu.com les joueurs blessés ou suspendus et les meilleurs buteurs et passeurs
de la saison, puis en tire un malus Elo par équipe.

Seuls des nombres et des indicateurs sont enregistrés (data/absences/du_jour.json) : aucun nom de joueur ni
texte de page n’est écrit dans le dépôt. Les noms ne servent qu’à rapprocher les listes pendant l’exécution.

Usage :
  python3 footactu.py chemins     recherche les adresses des pages de chaque championnat
  python3 footactu.py collecter   relève les pages et écrit le relevé du jour (usage par défaut)
"""
import datetime as dt
import difflib
import hashlib
import json
import pathlib
import re
import sys
import time
import unicodedata
import urllib.request
import urllib.robotparser
from html.parser import HTMLParser

RACINE = pathlib.Path(__file__).resolve().parent.parent
DONNEES = RACINE / 'data'
ABSENCES = DONNEES / 'absences'
CHEMINS = ABSENCES / 'chemins_footactu.json'
DU_JOUR = ABSENCES / 'du_jour.json'
DONNEES_PUBLIEES = DONNEES / 'donnees_publiees.json'
LIGUES = json.loads((DONNEES / 'ligues_api.json').read_text(encoding='utf-8'))

SITE = 'https://foot-actu.com'
UA = 'Lotofoot-analyse/1.0 (usage personnel, une lecture par jour)'
PAUSE = 7  # secondes entre deux pages
CLASSEMENTS = '/classements-championnats-football-etrangers'
# Pages vérifiées à la main (Ligue 1 et Premier League)
CONNUS = {
    'F1': {'blessures': '/ligue-1/blessures-suspensions',
           'buteurs': '/ligue-1/classement-meilleur-buteur-ligue-1',
           'passeurs': '/ligue-1/classement-meilleur-passeur-ligue-1'},
    'E0': {'blessures': '/premier-league/blessures-suspensions-premier-league',
           'buteurs': '/premier-league/classement-buteurs-premier-league',
           'passeurs': '/premier-league/classement-passeurs-premier-league'},
}

# Malus Elo appliqué à une équipe qui a des absents (points Elo, valeurs négatives)
MALUS_BUTEUR = -10      # meilleur buteur absent
MALUS_PASSEUR = -5      # meilleur passeur absent, s’il n’est pas aussi le meilleur buteur
MALUS_AUTRE = -2        # par autre absent
MALUS_AUTRES_MAX = -10  # plafond des autres absents
MALUS_MAX = -20         # plafond du malus total
REGLES = {'buteur': MALUS_BUTEUR, 'passeur': MALUS_PASSEUR, 'autre': MALUS_AUTRE,
          'autres_max': MALUS_AUTRES_MAX, 'max': MALUS_MAX}

# Clubs du site -> noms des données (le reste est rapproché automatiquement)
ALIAS = {
    'RC Lens': 'Lens', 'Olympique Lyonnais': 'Lyon', 'OGC Nice': 'Nice', 'Paris Saint-Germain': 'Paris SG',
    'AJ Auxerre': 'Auxerre', 'Lille OSC': 'Lille', 'Stade Brestois': 'Brest', 'Estac': 'Troyes',
    'SCO Angers': 'Angers', 'Olympique de Marseille': 'Marseille', 'Toulouse Football Club': 'Toulouse',
    'Le Havre Athletic Club': 'Le Havre', 'Paris FC': 'Paris FC',
    'PSG': 'Paris SG', 'Stade Rennais': 'Rennes', 'Manchester City': 'Man City',
    'Manchester United': 'Man United', 'Nottingham Forest': "Nott'm Forest",
}
MOTS_VIDES = {'fc', 'cf', 'afc', 'ac', 'as', 'rc', 'ogc', 'osc', 'sc', 'sco', 'aj', 'us', 'ss', 'sv', 'vfb', 'vfl',
              'bv', 'rb', 'the', 'club', 'football', 'athletic', 'de', 'la', 'le', 'of', 'calcio', 'ssc', 'cd', 'rcd',
              'sd', 'fk', 'sk', 'nk'}
VIDES = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'path', 'source', 'wbr'}


# ---------- Lecture des pages

class Noeud:
    __slots__ = ('tag', 'classes', 'enfants')

    def __init__(self, tag, classes):
        self.tag = tag
        self.classes = classes
        self.enfants = []


class Arbre(HTMLParser):
    """Construit l’arbre des balises ; le contenu des scripts et des styles est ignoré."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.racine = Noeud('racine', set())
        self.pile = [self.racine]
        self.ignore = None

    def _noeud(self, tag, attrs):
        return Noeud(tag, set((dict(attrs).get('class') or '').split()))

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ignore = tag
            return
        n = self._noeud(tag, attrs)
        self.pile[-1].enfants.append(n)
        if tag not in VIDES:
            self.pile.append(n)

    def handle_startendtag(self, tag, attrs):
        self.pile[-1].enfants.append(self._noeud(tag, attrs))

    def handle_endtag(self, tag):
        if tag == self.ignore:
            self.ignore = None
            return
        for i in range(len(self.pile) - 1, 0, -1):
            if self.pile[i].tag == tag:
                del self.pile[i:]
                return

    def handle_data(self, data):
        if self.ignore is None:
            self.pile[-1].enfants.append(data)


def arbre(html):
    a = Arbre()
    a.feed(html)
    a.close()
    return a.racine


def descendants(n):
    for e in n.enfants:
        if isinstance(e, Noeud):
            yield e
            yield from descendants(e)


def texte(n):
    """Texte complet d’un élément, espaces réduits."""
    morceaux = []

    def rec(x):
        for e in x.enfants:
            if isinstance(e, str):
                morceaux.append(e)
            else:
                rec(e)
    rec(n)
    return ' '.join(''.join(morceaux).split())


def texte_direct(n):
    """Texte posé directement dans l’élément, sans celui des balises enfants."""
    return ' '.join(''.join(e for e in n.enfants if isinstance(e, str)).split())


def lire_blessures(html):
    """Par club : la liste des absents (une clé par joueur ; None si le nom n’est pas lisible)."""
    out = []
    for tr in descendants(arbre(html)):
        if tr.tag != 'tr' or 'border-t' not in tr.classes:
            continue
        club, absents = '', []
        for n in descendants(tr):
            if not club and n.tag == 'a' and 'font-semibold' in n.classes:
                club = texte(n)
            if n.tag == 'span' and {'inline-flex', 'gap-1', 'text-xs'} <= n.classes and \
                    any(c.tag == 'span' and 'opacity-60' in c.classes for c in descendants(n)):
                absents.append(cle_joueur(texte_direct(n)))
        if club:
            out.append((club, absents))
    return out


def lire_classement(html):
    """Lignes d’un classement de buteurs ou de passeurs : (joueur, club, valeur)."""
    out = []
    for tr in descendants(arbre(html)):
        if tr.tag != 'tr' or 'border-t' not in tr.classes:
            continue
        joueur = equipe = valeur = None
        for n in descendants(tr):
            if joueur is None and n.tag == 'td' and 'font-semibold' in n.classes:
                joueur = texte(n)
            if equipe is None and n.tag == 'span' and {'text-sm', 'font-medium'} <= n.classes:
                equipe = texte(n)
            if valeur is None and n.tag == 'span' and 'font-extrabold' in n.classes:
                valeur = texte(n)
        if joueur and equipe and valeur and valeur.isdigit():
            out.append((joueur, equipe, int(valeur)))
    return out


class Lecteur:
    """Lit les pages du site en respectant robots.txt et une pause entre deux pages."""

    def __init__(self):
        self.robots = urllib.robotparser.RobotFileParser()
        self.robots.set_url(SITE + '/robots.txt')
        self.robots.read()
        self.derniere = 0.0

    def page(self, chemin):
        if not self.robots.can_fetch(UA, SITE + chemin):
            raise PermissionError('interdit par robots.txt')
        attente = PAUSE - (time.time() - self.derniere)
        if attente > 0:
            time.sleep(attente)
        self.derniere = time.time()
        req = urllib.request.Request(SITE + chemin, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=60) as rep:
            return rep.read().decode('utf-8', errors='ignore')


def liens(html):
    """Adresses internes d’une page, sans domaine, paramètres ni ancre."""
    out = set()
    for href in re.findall(r'href="([^"]+)"', html):
        href = href.replace('https://www.foot-actu.com', '').replace('https://foot-actu.com', '')
        if href.startswith('/') and not href.startswith('//'):
            out.add(href.split('?')[0].split('#')[0])
    return out


def pages_de(lecteur, chemin_ligue):
    """Adresses des pages de blessures, de buteurs et de passeurs d’un championnat, prises dans sa rubrique.
    Renvoie aussi les liens qui parlent de ces pages, hors rubrique, pour le diagnostic."""
    rubrique = re.sub(r'-\d+$', '', chemin_ligue.rsplit('/', 1)[-1])
    liens_ligue = liens(lecteur.page(chemin_ligue))
    utiles = sorted(c for c in liens_ligue if re.search(r'blessure|suspen|buteur|passeur', c))
    pages = {}
    for type_, mot in (('blessures', 'blessure'), ('buteurs', 'buteur'), ('passeurs', 'passeur')):
        propres = sorted((c for c in liens_ligue
                          if mot in c.rsplit('/', 1)[-1] and rubrique in c.strip('/').split('/')), key=len)
        if propres:
            pages[type_] = propres[0]
    return pages, utiles


def decouvrir(lecteur):
    """Adresses des pages de chaque championnat, relevées sur les pages de navigation du site."""
    par_id = {int(v): k for k, v in LIGUES.items()}
    candidats = {}
    for chemin in liens(lecteur.page(CLASSEMENTS)):
        m = re.match(r'^/(?:[^/]+/)*[a-z0-9-]+-(\d+)$', chemin)
        if m and int(m.group(1)) in par_id:
            candidats.setdefault(par_id[int(m.group(1))], []).append(chemin)
    chemins = {}
    for code, liste in candidats.items():
        if code in CONNUS:
            continue
        chemin = sorted(liste, key=lambda c: (not c.startswith(CLASSEMENTS), len(c)))[0]
        try:
            pages, utiles = pages_de(lecteur, chemin)
        except Exception as e:
            print('  page du championnat %s indisponible : %s' % (code, type(e).__name__))
            continue
        print('  %s : page %s ; liens utiles : %s' % (code, chemin, ', '.join(utiles[:15]) or 'aucun'))
        if pages:
            chemins[code] = pages
    for code, pages in CONNUS.items():
        chemins[code] = pages
    return chemins


# ---------- Joueurs et équipes

def cle_joueur(nom):
    """(nom de famille, initiale du prénom) : « A. Exemple » et « Alassane Exemple » donnent la même clé."""
    s = unicodedata.normalize('NFKD', nom or '').encode('ascii', 'ignore').decode().lower()
    mots = re.findall(r'[a-z]+', s)
    if not mots:
        return None
    return (mots[-1], mots[0][0] if len(mots) > 1 else '')


def meme_joueur(a, b, initiales=None):
    """Deux clés désignent le même joueur : même nom de famille et initiales compatibles. Si une initiale manque,
    le nom de famille doit être unique dans l’équipe (initiales : nom de famille -> initiales connues)."""
    if a[0] != b[0]:
        return False
    if a[1] and b[1]:
        return a[1] == b[1]
    if initiales is None:
        return True
    return len(initiales.get(a[0], ())) <= 1


def trois_premiers(liste):
    """Joueurs classés aux trois premières places d’un classement, égalités comprises. liste : [(clé, valeur)]."""
    tries = sorted([(v, k) for k, v in liste if k and v > 0], key=lambda x: -x[0])
    if not tries:
        return []
    seuil = tries[min(2, len(tries) - 1)][0]
    return [k for v, k in tries if v >= seuil]


def cle_equipe(nom):
    s = unicodedata.normalize('NFKD', nom).encode('ascii', 'ignore').decode().lower().replace('&', ' and ')
    return ''.join(m for m in re.findall(r'[a-z0-9]+', s) if m not in MOTS_VIDES)


def rapprocher(club, noms):
    """Nom des données correspondant au club du site, ou None si le rapprochement n’est pas sûr."""
    if ALIAS.get(club) in noms:
        return ALIAS[club]
    k = cle_equipe(club)
    if not k or not noms:
        return None
    egaux = [n for n in noms if cle_equipe(n) == k]
    if len(egaux) == 1:
        return egaux[0]
    inclus = [n for n in noms if min(len(cle_equipe(n)), len(k)) >= 4 and (k in cle_equipe(n) or cle_equipe(n) in k)]
    if len(inclus) == 1:
        return inclus[0]
    proche = max(noms, key=lambda n: difflib.SequenceMatcher(None, k, cle_equipe(n)).ratio())
    return proche if difflib.SequenceMatcher(None, k, cle_equipe(proche)).ratio() >= 0.85 else None


def meilleurs(liste):
    """Joueurs en tête d’un classement, égalités comprises. liste : [(clé, valeur)]."""
    if not liste:
        return []
    haut = max(v for _, v in liste)
    if haut <= 0:
        return []
    return [k for k, v in liste if v == haut and k]


def bilan_equipe(absents, tetes_buteurs, tetes_passeurs, trois_buteurs=(), trois_passeurs=(), initiales=None):
    """Absents d’une équipe : meilleur buteur et passeur (malus), trois premiers (alertes), malus Elo."""
    def dans(k, liste):
        return any(meme_joueur(k, c, initiales) for c in liste)

    buteur = passeur = meme = False
    cles = 0
    for k in absents:
        if not k:
            continue
        b = dans(k, tetes_buteurs)
        p = dans(k, tetes_passeurs)
        if b or p:
            cles += 1
        buteur = buteur or b
        passeur = passeur or (p and not b)
        meme = meme or (b and p)
    buteurs_cles = sum(1 for k in absents if k and dans(k, trois_buteurs))
    passeurs_cles = sum(1 for k in absents if k and dans(k, trois_passeurs))
    autres = len(absents) - cles
    malus = (MALUS_BUTEUR if buteur else 0) + (MALUS_PASSEUR if passeur else 0)
    malus += max(MALUS_AUTRES_MAX, MALUS_AUTRE * autres)
    return {'absents': len(absents), 'buteur': buteur, 'passeur': passeur, 'meme_joueur': meme,
            'buteurs_cles': buteurs_cles, 'passeurs_cles': passeurs_cles, 'malus': max(MALUS_MAX, malus)}


# ---------- Relevé du jour

def collecter():
    lecteur = Lecteur()
    if CHEMINS.exists():
        chemins = json.loads(CHEMINS.read_text(encoding='utf-8'))
    else:
        chemins = decouvrir(lecteur)
        CHEMINS.parent.mkdir(parents=True, exist_ok=True)
        CHEMINS.write_text(json.dumps(chemins, ensure_ascii=False, indent=1), encoding='utf-8')
    equipes = {}
    for t in json.loads(DONNEES_PUBLIEES.read_text(encoding='utf-8'))['equipes']:
        equipes.setdefault(t['ligue'], set()).add(t['equipe'])
    releve = {'date': dt.date.today().isoformat(), 'source': 'foot-actu.com', 'regles': REGLES,
              'championnats': {}, 'suivi': {}}
    for code in sorted(chemins):
        if code not in equipes:
            continue
        noms = sorted(equipes[code])
        pages = chemins[code]
        suivi, absents, buteurs, passeurs, inconnus = {}, {}, {}, {}, set()
        rapproches = {}

        def nom_de(club):
            if club not in rapproches:
                rapproches[club] = rapprocher(club, noms)
            return rapproches[club]

        for type_ in ('blessures', 'buteurs', 'passeurs'):
            if type_ not in pages:
                continue
            try:
                html = lecteur.page(pages[type_])
            except Exception as e:
                suivi['erreur_' + type_] = type(e).__name__
                continue
            if type_ == 'blessures':
                lignes = lire_blessures(html)
                suivi['blessures_clubs'] = len(lignes)
                suivi['blessures_joueurs'] = sum(len(j) for _, j in lignes)
                for club, joueurs in lignes:
                    nom = nom_de(club)
                    if nom is None:
                        inconnus.add(club)
                    else:
                        absents.setdefault(nom, []).extend(joueurs)
            else:
                lignes = lire_classement(html)
                suivi[type_] = len(lignes)
                cible = buteurs if type_ == 'buteurs' else passeurs
                for joueur, club, valeur in lignes:
                    nom = nom_de(club)
                    if nom is None:
                        inconnus.add(club)
                    else:
                        cible.setdefault(nom, []).append((cle_joueur(joueur), valeur))
        resultat = {}
        for nom in noms:
            if nom in absents:
                pool = ([k for k in absents[nom] if k] + [k for k, _ in buteurs.get(nom, []) if k]
                        + [k for k, _ in passeurs.get(nom, []) if k])
                initiales = {}
                for surnom, initiale in pool:
                    if initiale:
                        initiales.setdefault(surnom, set()).add(initiale)
                resultat[nom] = bilan_equipe(absents[nom], meilleurs(buteurs.get(nom, [])),
                                             meilleurs(passeurs.get(nom, [])),
                                             trois_premiers(buteurs.get(nom, [])),
                                             trois_premiers(passeurs.get(nom, [])), initiales)
        if resultat:
            releve['championnats'][code] = resultat
        releve['suivi'][code] = suivi
        if inconnus:
            print('  %s, clubs non rapprochés : %s' % (code, ' ; '.join(sorted(inconnus))))
        print('%-4s %s | équipes avec absents : %d | buteur principal absent : %d | passeur principal absent : %d' % (
            code, ' ; '.join('%s %s' % (k, v) for k, v in suivi.items()) or 'aucune page',
            len(resultat), sum(1 for r in resultat.values() if r['buteur']),
            sum(1 for r in resultat.values() if r['passeur'])))
    DU_JOUR.parent.mkdir(parents=True, exist_ok=True)
    DU_JOUR.write_text(json.dumps(releve, ensure_ascii=False, indent=1), encoding='utf-8')
    print('Relevé du %s écrit : %d championnats lus, %d équipes avec absents.' % (
        releve['date'], len(releve['suivi']), sum(len(v) for v in releve['championnats'].values())))


def du_jour_frais():
    """Le relevé du jour ou de la veille ; au-delà, il n’est plus pris en compte."""
    if not DU_JOUR.exists():
        return None
    releve = json.loads(DU_JOUR.read_text(encoding='utf-8'))
    age = (dt.date.today() - dt.date.fromisoformat(releve['date'])).days
    return releve if 0 <= age <= 1 else None


def absences_par_equipe(releve):
    """{(ligue, équipe): {'nombre', 'buteur', 'passeur', 'malus'}} pour les équipes ayant au moins un absent."""
    out = {}
    if not releve:
        return out
    for code, equipes in releve.get('championnats', {}).items():
        for nom, a in equipes.items():
            out[(code, nom)] = {'nombre': a['absents'], 'buteur': a['buteur'], 'passeur': a['passeur'],
                                'meme': a.get('meme_joueur', False), 'buteurs_cles': a.get('buteurs_cles', 0),
                                'passeurs_cles': a.get('passeurs_cles', 0), 'malus': a['malus']}
    return out


# ---------- Diagnostic : organisation d’une page de classement (titres, tableaux), sans son contenu

def classements_suivis(accueil):
    """Adresse de la page de classement de chaque championnat suivi, relevée sur la page d’accueil des classements."""
    par_id = {int(v): k for k, v in LIGUES.items()}
    candidats = {}
    for chemin in liens(accueil):
        m = re.match(r'^/(?:[^/]+/)*[a-z0-9-]+-(\d+)$', chemin)
        if m and int(m.group(1)) in par_id:
            candidats.setdefault(par_id[int(m.group(1))], []).append(chemin)
    return {code: sorted(liste, key=lambda c: (not c.startswith(CLASSEMENTS), len(c)))[0]
            for code, liste in candidats.items()}


def _chaine(n, indent, budget):
    """Arbre des balises d’un élément ; le texte est remplacé par sa longueur."""
    for e in n.enfants:
        if budget[0] <= 0:
            return
        if isinstance(e, Noeud):
            budget[0] -= 1
            print('%s%s%s' % (indent, e.tag, ''.join('.' + c for c in sorted(e.classes))))
            _chaine(e, indent + '  ', budget)
        elif e.strip():
            budget[0] -= 1
            print('%s[texte de %d caractères]' % (indent, len(e.strip())))


MOTS_DIAG = r'classement|buteur|passeur|bless|suspen|absent|championnat|europe'


def diagnostic(lecteur, codes):
    accueil = lecteur.page(CLASSEMENTS)
    print('liens « europe » sur la page d’accueil :',
          ', '.join(sorted(c for c in liens(accueil) if 'europe' in c)) or 'aucun')
    trouves = classements_suivis(accueil)
    for code in codes:
        if code not in trouves:
            print('%s : page de classement introuvable' % code)
            continue
        html = lecteur.page(trouves[code])
        racine = arbre(html)
        print('== %s %s (%d caractères)' % (code, trouves[code], len(html)))
        print('  liens « europe » : ' + (', '.join(sorted(c for c in liens(html) if 'europe' in c)) or 'aucun'))
        titres = [texte(n)[:40] for n in descendants(racine)
                  if n.tag in ('h1', 'h2', 'h3', 'h4') and re.search(MOTS_DIAG, texte(n).lower())]
        print('  titres utiles : ' + (' | '.join(titres[:20]) or 'aucun'))
        boutons = [texte(n)[:30] for n in descendants(racine)
                   if n.tag == 'button' and re.search(MOTS_DIAG, texte(n).lower())]
        print('  boutons utiles : ' + (' | '.join(boutons[:20]) or 'aucun'))
        utiles = sorted(c for c in liens(html) if re.search(r'blesse|suspen|buteur|passeur|joueur|absent', c))
        print('  liens utiles : ' + (', '.join(utiles[:20]) or 'aucun'))
        tableaux = [n for n in descendants(racine) if n.tag == 'table']
        print('  tableaux : %d' % len(tableaux))
        montres = 0
        for i, t in enumerate(tableaux, 1):
            entetes = [texte(n)[:20] for n in descendants(t) if n.tag == 'th']
            lignes = [n for n in descendants(t) if n.tag == 'tr']
            motif = any(c.tag == 'span' and 'opacity-60' in c.classes for c in descendants(t))
            cle = bool(re.search(r'buteur|passeur|bless|suspen|absent', texte(t).lower()))
            print('  tableau %d : %d lignes ; en-têtes : %s ; motifs (opacity-60) : %s' % (
                i, len(lignes), ' | '.join(entetes[:10]) or 'aucun', 'oui' if motif else 'non'))
            if (motif or cle) and montres < 4:
                montres += 1
                donnees = [tr for tr in lignes if any(isinstance(c, Noeud) and c.tag == 'td' for c in tr.enfants)]
                for k, tr in enumerate(donnees[:2], 1):
                    print('    ligne %d' % k)
                    _chaine(tr, '      ', [40])


MOTS_BRUTS = ['blessé', 'blessure', 'suspendu', 'suspension', 'indisponible', 'absent', 'opacity-60',
              '__next_data__', 'application/json', 'role="tab"', 'aria-selected', 'data-tab']


def textes_avec_chemin(n, chemin=()):
    """Textes d’un arbre, avec le chemin des éléments qui les contiennent."""
    for e in n.enfants:
        if isinstance(e, Noeud):
            yield from textes_avec_chemin(e, chemin + (e,))
        else:
            yield e, chemin


def diagnostic_brut(lecteur, codes):
    """Où se trouvent les blessés et suspendus dans le HTML des pages de classement (sans le texte)."""
    accueil = lecteur.page(CLASSEMENTS)
    hors = sorted(c for c in liens(accueil) if not c.startswith(CLASSEMENTS))
    print('accueil : %d liens hors classements : %s' % (len(hors), ', '.join(hors[:60]) or 'aucun'))
    trouves = classements_suivis(accueil)
    for code in codes:
        if code not in trouves:
            print('%s : page de classement introuvable' % code)
            continue
        html = lecteur.page(trouves[code])
        bas = html.lower()
        print('== %s %s (%d caractères)' % (code, trouves[code], len(html)))
        print('  mots dans le HTML brut : ' + ' ; '.join('%s %d' % (m, bas.count(m)) for m in MOTS_BRUTS))
        scripts = re.findall(r'<script([^>]*)>(.*?)</script>', html, re.S | re.I)
        print('  balises script : %d' % len(scripts))
        for attrs, corps in scripts:
            ident = re.search(r'id="([^"]*)"', attrs)
            typ = re.search(r'type="([^"]*)"', attrs)
            bas_corps = corps.lower()
            hits = bas_corps.count('bless') + bas_corps.count('suspen')
            if hits or ident:
                print('    script id=%s type=%s longueur=%d mots blessés/suspendus=%d' % (
                    ident.group(1) if ident else '-', typ.group(1) if typ else '-', len(corps), hits))
        racine = arbre(html)
        touches = [(t, ch) for t, ch in textes_avec_chemin(racine)
                   if any(m in t.lower() for m in ('bless', 'suspen', 'indisponib'))]
        print('  textes du DOM contenant bless / suspen / indisponib : %d' % len(touches))
        for t, ch in touches[:3]:
            print('    ancêtres : ' + ' > '.join(n.tag + ''.join('.' + c for c in sorted(n.classes)) for n in ch[-6:]))
        pages = sorted(liens(html))
        print('  liens de la page : %d' % len(pages))
        print('    ' + ', '.join(pages[:80]))


def brut_chemin(lecteur, chemin):
    """Où se trouvent blessés et suspendus dans le HTML d’une page (sans le texte)."""
    html = lecteur.page(chemin)
    bas = html.lower()
    print('== %s (%d caractères)' % (chemin, len(html)))
    print('  mots dans le HTML brut : ' + ' ; '.join('%s %d' % (m, bas.count(m)) for m in MOTS_BRUTS))
    scripts = re.findall(r'<script([^>]*)>(.*?)</script>', html, re.S | re.I)
    print('  balises script : %d' % len(scripts))
    for attrs, corps in scripts:
        ident = re.search(r'id="([^"]*)"', attrs)
        typ = re.search(r'type="([^"]*)"', attrs)
        bas_corps = corps.lower()
        hits = bas_corps.count('bless') + bas_corps.count('suspen') + bas_corps.count('absent')
        if hits or ident:
            print('    script id=%s type=%s longueur=%d mots blessés/suspendus/absents=%d' % (
                ident.group(1) if ident else '-', typ.group(1) if typ else '-', len(corps), hits))
    racine = arbre(html)
    touches = [(t, ch) for t, ch in textes_avec_chemin(racine)
               if any(m in t.lower() for m in ('bless', 'suspen', 'indisponib', 'absent'))]
    print('  textes du DOM contenant bless / suspen / indisponib / absent : %d' % len(touches))
    for t, ch in touches[:4]:
        print('    ancêtres : ' + ' > '.join(n.tag + ''.join('.' + c for c in sorted(n.classes)) for n in ch[-6:]))
    tableaux = [n for n in descendants(racine) if n.tag == 'table']
    print('  tableaux : %d ; titres (h1-h4) : %d' % (len(tableaux), sum(1 for n in descendants(racine) if n.tag in ('h1', 'h2', 'h3', 'h4'))))
    pages = sorted(liens(html))
    print('  liens de la page : %d' % len(pages))


def diagnostic_plan(lecteur):
    """Adresses du site qui parlent de blessés, suspendus, buteurs, passeurs ou Europe, d’après le plan du site
    et les plans XML (adresses seulement)."""
    robots = lecteur.page('/robots.txt')
    print('robots.txt : ' + (' | '.join(l.strip() for l in robots.splitlines() if l.lower().startswith('sitemap'))
                             or 'aucune ligne Sitemap'))
    a_lire = ['/plan-de-site', '/sitemap.xml']
    lues, adresses = set(), set()
    while a_lire and len(lues) < 14:
        chemin = a_lire.pop(0)
        if chemin in lues:
            continue
        lues.add(chemin)
        try:
            html = lecteur.page(chemin)
        except Exception as e:
            print('%s : %s' % (chemin, type(e).__name__))
            continue
        locs = [re.sub(r'^https?://(www\.)?foot-actu\.com', '', u)
                for u in re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', html)]
        sous = [u for u in locs if u.endswith('.xml')]
        pages = set(liens(html)) | {u for u in locs if u.startswith('/') and not u.endswith('.xml')}
        print('%s : %d adresses ; plans XML enfants : %s' % (chemin, len(pages), ', '.join(sous) or 'aucun'))
        a_lire.extend(u for u in sous if u not in lues)
        adresses |= pages
    rubriques = {}
    for a in adresses:
        premier = a.strip('/').split('/')[0]
        rubriques[premier] = rubriques.get(premier, 0) + 1
    print('rubriques (nombre d’adresses) : ' + ', '.join('%s %d' % (k, v) for k, v in
                                                  sorted(rubriques.items(), key=lambda kv: -kv[1])[:40]))
    utiles = sorted(a for a in adresses if re.search(r'bless|suspen|buteur|passeur|europe', a.lower()))
    print('adresses utiles (%d) : %s' % (len(utiles), ', '.join(utiles[:200]) or 'aucune'))
    billets = sorted(a for a in adresses if a.strip('/').startswith('billet-'))
    clubs = sorted(a for a in adresses if a.startswith('/club/'))
    print('billets (%d) : %s' % (len(billets), ', '.join(billets[:30])))
    print('clubs (%d) : %s' % (len(clubs), ', '.join(clubs[:40])))
    for chemin in ([billets[0]] if billets else []) + ([clubs[0]] if clubs else []):
        try:
            brut_chemin(lecteur, chemin)
        except Exception as e:
            print('%s : %s' % (chemin, type(e).__name__))


# ---------- Diagnostic anonyme des alertes buteur et passeur (aucun nom n’est affiché)

def anonyme(cle):
    """Identifiant masqué d’un joueur (dérivé de son nom de famille et de son initiale)."""
    if not cle:
        return 'inconnu'
    base = hashlib.sha1((cle[0] + '|' + cle[1]).encode('utf-8')).hexdigest()[:6]
    return base + ('' if cle[1] else '(initiale absente)')


def diagnostic_alertes(lecteur):
    chemins = json.loads(CHEMINS.read_text(encoding='utf-8'))
    equipes = {}
    for t in json.loads(DONNEES_PUBLIEES.read_text(encoding='utf-8'))['equipes']:
        equipes.setdefault(t['ligue'], set()).add(t['equipe'])
    for code in sorted(chemins):
        if code not in equipes:
            continue
        noms = sorted(equipes[code])
        pages = chemins[code]
        absents, buteurs, passeurs, rapproches = {}, {}, {}, {}

        def nom_de(club):
            if club not in rapproches:
                rapproches[club] = rapprocher(club, noms)
            return rapproches[club]

        if 'blessures' in pages:
            for club, joueurs in lire_blessures(lecteur.page(pages['blessures'])):
                nom = nom_de(club)
                if nom:
                    absents.setdefault(nom, []).extend(joueurs)
        for type_, dest in (('buteurs', buteurs), ('passeurs', passeurs)):
            if type_ in pages:
                for joueur, club, valeur in lire_classement(lecteur.page(pages[type_])):
                    nom = nom_de(club)
                    if nom:
                        dest.setdefault(nom, []).append((cle_joueur(joueur), valeur))
        for nom in noms:
            if nom not in absents:
                continue
            tb = meilleurs(buteurs.get(nom, []))
            tp = meilleurs(passeurs.get(nom, []))
            concerne = False
            for k in absents[nom]:
                if not k:
                    continue
                dans_b = any(meme_joueur(k, c) for c in tb)
                dans_p = any(meme_joueur(k, c) for c in tp)
                if dans_b or dans_p:
                    concerne = True
                    print('  %s : absent %s | parmi les meilleurs buteurs : %s | parmi les meilleurs passeurs : %s' % (
                        nom, anonyme(k), dans_b, dans_p))
            if concerne:
                for libelle, liste in (('buteurs', buteurs.get(nom, [])), ('passeurs', passeurs.get(nom, []))):
                    tete = sorted(liste, key=lambda x: -x[1])[:4]
                    print('    %s (trois premiers) : %s' % (libelle, ' ; '.join(
                        '%s %d' % (anonyme(c), v) for c, v in tete)))


def diagnostic_coupes(lecteur):
    """Coupes d’Europe : adresses des pages de résultats et structure de leurs lignes (sans le texte des articles)."""
    trouvees = []
    for plan in ('/sitemap-champions-league.xml', '/sitemap-europa-league.xml'):
        try:
            xml = lecteur.page(plan)
        except Exception as e:
            print('%s : %s' % (plan, type(e).__name__))
            continue
        locs = [re.sub(r'^https?://(www\.)?foot-actu\.com', '', u) for u in re.findall(r'<loc>\s*([^<\s]+)\s*</loc>', xml)]
        utiles = sorted(u for u in locs if re.search(r'calendrier|resultat|journee|match|classement', u.lower()))
        print('%s : %d adresses ; utiles : %s' % (plan, len(locs), ', '.join(utiles[:60]) or 'aucune'))
        trouvees += utiles
    cibles = [u for u in trouvees if re.search(r'calendrier|resultat', u.lower())][:2]
    for chemin in cibles:
        html = lecteur.page(chemin)
        racine = arbre(html)
        print('== %s (%d caractères)' % (chemin, len(html)))
        titres = [texte(n)[:40] for n in descendants(racine)
                  if n.tag in ('h1', 'h2', 'h3', 'h4') and re.search(r'calendrier|résultat|journ|match|tour', texte(n).lower())]
        print('  titres utiles : ' + (' | '.join(titres[:15]) or 'aucun'))
        tableaux = [n for n in descendants(racine) if n.tag == 'table']
        print('  tableaux : %d' % len(tableaux))
        for i, t in enumerate(tableaux[:3], 1):
            lignes = [n for n in descendants(t) if n.tag == 'tr']
            entetes = [texte(n)[:20] for n in descendants(t) if n.tag == 'th']
            print('  tableau %d : %d lignes ; en-têtes : %s' % (i, len(lignes), ' | '.join(entetes[:10]) or 'aucun'))
            donnees = [tr for tr in lignes if any(isinstance(c, Noeud) and c.tag == 'td' for c in tr.enfants)]
            for k, tr in enumerate(donnees[:2], 1):
                print('    ligne %d' % k)
                _chaine(tr, '      ', [40])
        scores = re.findall(r'\b\d{1,2} ?[-–] ?\d{1,2}\b', html)
        print('  motifs « 2 - 1 » dans le HTML : %d' % len(scores))


SCORE_SEUL = re.compile(r'^\s*\d{1,2}\s*[-–]\s*\d{1,2}\s*$')
DATE_TEXTE = re.compile(r'(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)\s+\d{1,2}|\d{1,2}\s+(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)', re.I)


def _plan(n, indent, budget):
    """Contour d’un élément : balises, classes et longueur du texte (pas le texte lui-même, sauf libellés courts)."""
    for e in n.enfants:
        if budget[0] <= 0:
            return
        if isinstance(e, Noeud):
            budget[0] -= 1
            court = texte(e)
            libelle = ('  « %s »' % court) if (court and len(court) <= 30 and not e.enfants[0:0] and
                                              all(isinstance(x, str) for x in e.enfants)) else ''
            print('%s%s%s%s' % (indent, e.tag, ''.join('.' + c for c in sorted(e.classes)), libelle))
            _plan(e, indent + '  ', budget)


def diagnostic_cartes(lecteur, chemin):
    html = lecteur.page(chemin)
    racine = arbre(html)
    print('== %s (%d caractères)' % (chemin, len(html)))
    dates = [t_ for t_, _ in textes_avec_chemin(racine) if DATE_TEXTE.search(t_)]
    print('  libellés de date (%d) : %s' % (len(dates), ' | '.join(d_.strip()[:50] for d_ in dates[:6])))
    scores = [(t_, ch) for t_, ch in textes_avec_chemin(racine) if SCORE_SEUL.match(t_)]
    print('  scores isolés : %d' % len(scores))
    for k, (t_, ch) in enumerate(scores[:3], 1):
        print('  score %d, ancêtres (du plus proche) : %s' % (k, ' < '.join(
            n.tag + ''.join('.' + c for c in sorted(n.classes)) for n in reversed(ch[-6:]))))
    if scores:
        ch = scores[0][1]
        niveau = ch[-4] if len(ch) >= 4 else ch[-1]
        print('  contour de la carte (4 niveaux au-dessus du score) :')
        _plan(niveau, '    ', [60])


def main(argv):
    commande = argv[1] if len(argv) > 1 else 'collecter'
    if commande == 'chemins':
        chemins = decouvrir(Lecteur())
        ABSENCES.mkdir(parents=True, exist_ok=True)
        CHEMINS.write_text(json.dumps(chemins, ensure_ascii=False, indent=1), encoding='utf-8')
        for code in LIGUES:
            print('%-4s %s' % (code, ', '.join(sorted(chemins[code])) if code in chemins else 'aucune page trouvée'))
    elif commande == 'diagnostic':
        diagnostic_alertes(Lecteur())
    elif commande == 'cartes':
        lecteur = Lecteur()
        for chemin in ('/champions-league/resultats', '/europa-league/resultats'):
            diagnostic_cartes(lecteur, chemin)
    elif commande == 'coupes':
        diagnostic_coupes(Lecteur())
    elif commande == 'plan':
        diagnostic_plan(Lecteur())
    elif commande == 'brut':
        diagnostic_brut(Lecteur(), argv[2:] or ['I1', 'SP1', 'E1'])
    elif commande == 'structure':
        diagnostic(Lecteur(), argv[2:] or ['I1', 'SP1', 'E1'])
    elif commande == 'collecter':
        collecter()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
