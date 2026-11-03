"""Repère la structure de foot-actu.com pour la lecture automatique. N'affiche jamais le texte des pages :
seulement les règles du fichier robots.txt, les noms de balises et de classes, et les adresses de liens."""
import html.parser
import time
import urllib.request
import urllib.robotparser

UA = 'Lotofoot-analyse/1.0 (usage personnel, une lecture par jour)'
SITE = 'https://foot-actu.com'
PAGES = ['/ligue-1/blessures-suspensions']


def lire(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as rep:
        return rep.read().decode('utf-8', errors='ignore')


class Squelette(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.combos = {}
        self.liens = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get('class') or '').split()
        cle = tag + ('.' + '.'.join(classes[:2]) if classes else '')
        self.combos[cle] = self.combos.get(cle, 0) + 1
        if tag == 'a' and a.get('href'):
            self.liens.add(a['href'])


rp = urllib.robotparser.RobotFileParser()
rp.set_url(SITE + '/robots.txt')
rp.read()
print('robots.txt lu')
for page in PAGES:
    print('autorisé pour %s : %s' % (page, rp.can_fetch(UA, SITE + page)))

for page in PAGES:
    time.sleep(7)
    texte = lire(SITE + page)
    s = Squelette()
    s.feed(texte)
    print('\n== %s : %d caractères' % (page, len(texte)))
    print('balises et classes les plus fréquentes :')
    for cle, n in sorted(s.combos.items(), key=lambda x: -x[1])[:60]:
        print('  %-45s %d' % (cle, n))
    print('adresses de liens contenant un mot utile :')
    for lien in sorted(s.liens):
        if any(mot in lien for mot in ('classement', 'blessure', 'buteur', 'passeur', 'ligue', 'liga', 'bundes', 'serie', 'premier', 'championnat')):
            print('  ', lien)
