"""Repère la structure des pages foot-actu.com. N'affiche jamais de texte : seulement les balises, les classes
et la longueur des textes, ainsi que des adresses de liens. Une lecture par page, espacée de sept secondes."""
import html.parser
import time
import urllib.request
import urllib.robotparser

UA = 'Lotofoot-analyse/1.0 (usage personnel, une lecture par jour)'
SITE = 'https://foot-actu.com'
VIDES = {'img', 'br', 'input', 'path', 'meta', 'link', 'hr', 'source', 'svg'}


def lire(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as rep:
        return rep.read().decode('utf-8', errors='ignore')


class Squelette(html.parser.HTMLParser):
    """Affiche les premières lignes (balises tr) : balises, classes, longueurs de texte, jamais le texte."""

    def __init__(self, classe_cible, max_lignes):
        super().__init__(convert_charrefs=True)
        self.classe_cible, self.max_lignes = classe_cible, max_lignes
        self.lignes, self.dans, self.niveau, self.sortie = 0, False, 0, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classe = a.get('class') or ''
        if not self.dans and tag == 'tr' and self.classe_cible in classe and self.lignes < self.max_lignes:
            self.lignes += 1
            self.dans, self.niveau = True, 0
            self.sortie.append('--- ligne %d' % self.lignes)
        if self.dans:
            self.sortie.append('  ' * self.niveau + tag + ('.' + '.'.join(classe.split()[:4]) if classe else ''))
            if tag not in VIDES:
                self.niveau += 1

    def handle_endtag(self, tag):
        if self.dans and tag not in VIDES:
            self.niveau -= 1
            if tag == 'tr' and self.niveau == 0:
                self.dans = False

    def handle_data(self, data):
        if self.dans and data.strip():
            self.sortie.append('  ' * self.niveau + '[texte de %d caractères]' % len(data.strip()))


rp = urllib.robotparser.RobotFileParser()
rp.set_url(SITE + '/robots.txt')
rp.read()
pages = [
    ('/ligue-1/blessures-suspensions', 'border-t', 2),
    ('/ligue-1/classement-meilleur-buteur-ligue-1', '', 2),
    ('/premier-league', '', 0),
    ('/classements-championnats-football-etrangers', '', 0),
]
for chemin, classe, nb in pages:
    if not rp.can_fetch(UA, SITE + chemin):
        print('interdit par robots.txt : %s' % chemin)
        continue
    time.sleep(7)
    texte = lire(SITE + chemin)
    print('\n== %s (%d caractères)' % (chemin, len(texte)))
    if nb:
        s = Squelette(classe, nb)
        s.feed(texte)
        print('\n'.join(s.sortie[:160]))
    liens = sorted({l.split('"')[0] for l in texte.split('href="')[1:]})
    utiles = [l for l in liens if l.startswith('/') and any(m in l for m in ('blessure', 'buteur', 'passeur', 'classement', 'premier', 'liga', 'serie', 'bundes', 'ligue'))]
    print('adresses utiles :')
    for l in utiles[:80]:
        print('  ', l)
