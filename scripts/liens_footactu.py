"""Relève les chemins des pages de foot-actu.com (blessures et classements de chaque championnat).
N'affiche que des adresses, jamais le texte des pages. Une lecture par page, espacée de sept secondes."""
import re
import time
import urllib.request
import urllib.robotparser

UA = 'Lotofoot-analyse/1.0 (usage personnel, une lecture par jour)'
SITE = 'https://foot-actu.com'
PAGES = ['/classements-championnats-football-etrangers', '/premier-league', '/ligue-1']

rp = urllib.robotparser.RobotFileParser()
rp.set_url(SITE + '/robots.txt')
rp.read()
chemins = set()
for page in PAGES:
    if not rp.can_fetch(UA, SITE + page):
        print('interdit par robots.txt : %s' % page)
        continue
    time.sleep(7)
    req = urllib.request.Request(SITE + page, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as rep:
        texte = rep.read().decode('utf-8', errors='ignore')
    for href in re.findall(r'href="([^"]+)"', texte):
        href = href.replace('https://www.foot-actu.com', '').replace('https://foot-actu.com', '')
        if href.startswith('/') and not href.startswith('//'):
            chemins.add(href.split('?')[0].split('#')[0])
print('%d chemins trouvés' % len(chemins))
for c in sorted(chemins):
    if any(m in c for m in ('blessure', 'buteur', 'passeur', 'classement', 'premier', 'liga', 'serie', 'bundes', 'ligue', 'championnat')):
        print(c)
