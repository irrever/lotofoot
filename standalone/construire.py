"""Construit la version publique de Lotofoot à partir de standalone/app.html :
- site/ : dossier à héberger (HTTPS) ; l’application se met à jour à chaque ouverture avec connexion,
  et fonctionne hors ligne une fois ouverte (service worker) ;
- Lotofoot.html : fichier autonome hors ligne avec la grille de travail, construit seulement si
  data/grille_perso.json existe sur la machine. Ce fichier n’est pas publié.
"""
import json, pathlib, re, struct, subprocess, zipfile, zlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SA = ROOT / 'standalone'
SITE = SA / 'site'
SITE.mkdir(parents=True, exist_ok=True)
GRILLE_PERSONNELLE = ROOT / 'data' / 'grille_perso.json'


def dernier_bilan():
    """Dernier bilan d’observation (data/bilan), avec l’historique des bilans."""
    dossier = ROOT / 'data' / 'bilan'
    bilans = []
    for chemin in sorted(dossier.glob('bilan-*.json')):
        with open(chemin, encoding='utf-8') as f:
            bilans.append(json.load(f))
    if not bilans:
        return None
    dernier = max(bilans, key=lambda b: (b['meta']['saison'], b['meta']['date_donnees']))
    chemin_hist = dossier / 'historique.json'
    dernier['historique'] = json.load(open(chemin_hist, encoding='utf-8')) if chemin_hist.exists() else []
    return dernier


pub = json.load(open(ROOT / 'data/donnees_publiees.json', encoding='utf-8'))
donnees = {'version': pub['version'], 'derniere_date': pub['derniere_date'], 'equipes': pub['equipes'],
           'stats': pub['stats'], 'modele': pub['modele']}
donnees['bilan'] = dernier_bilan()
RESULTATS = ROOT / 'data/resultats.json'   # matchs de la veille et précision des grilles (src/rapport.py)
if RESULTATS.exists():
    donnees['resultats'] = json.load(open(RESULTATS, encoding='utf-8'))
embarque = None
if GRILLE_PERSONNELLE.exists():
    embarque = dict(donnees, grilles=[json.load(open(GRILLE_PERSONNELLE, encoding='utf-8'))])


def js_json(o):
    # Le JSON est placé dans une balise <script type="application/json"> : on neutralise "</".
    return json.dumps(o, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')


PWA_HEAD = ('<link rel="manifest" href="manifest.webmanifest">\n'
            '<meta name="theme-color" content="#f2f4f1">\n'
            '<link rel="icon" href="icone-192.png">\n'
            '<link rel="apple-touch-icon" href="icone-192.png">\n'
            '<meta name="apple-mobile-web-app-capable" content="yes">')
PWA_SCRIPT = ("<script>if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {"
              " window.addEventListener('load', function () { navigator.serviceWorker.register('sw.js').catch(function () {}); }); }"
              "</script>")

SW = """// Lotofoot : cache hors ligne.
// À chaque ouverture, l’application essaie d’abord le réseau (versions à jour) ;
// sans connexion, la copie gardée sur l’appareil prend le relais.
var CACHE = 'lotofoot-v2';
var FICHIERS = ['./', './index.html', './donnees.json', './manifest.webmanifest', './icone-192.png', './icone-512.png'];
self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(FICHIERS); })
    .then(function () { return self.skipWaiting(); }));
});
self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (cles) {
    return Promise.all(cles.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  e.respondWith(fetch(req).then(function (rep) {
    if (rep && rep.ok) {
      var copie = rep.clone();
      caches.open(CACHE).then(function (c) { c.put(req, copie); });
    }
    return rep;
  }).catch(function () {
    return caches.match(req).then(function (r) { return r || caches.match('./index.html'); });
  }));
});
"""

MANIFEST = {
    'name': 'Lotofoot Analyse', 'short_name': 'Lotofoot', 'lang': 'fr',
    'start_url': './index.html', 'scope': './', 'display': 'standalone',
    'background_color': '#f2f4f1', 'theme_color': '#f2f4f1',
    'icons': [{'src': 'icone-192.png', 'sizes': '192x192', 'type': 'image/png'},
              {'src': 'icone-512.png', 'sizes': '512x512', 'type': 'image/png'}],
}


def icone(taille):
    vert, blanc = (0x1d, 0x6a, 0x48), (255, 255, 255)
    cx = cy = taille / 2
    rayon = taille * 0.36

    def pixel(x, y):
        dx, dy = x + 0.5 - cx, y + 0.5 - cy
        if dx * dx + dy * dy > rayon * rayon:
            return bytes(vert)
        u, v = (x + 0.5) / taille, (y + 0.5) / taille
        # Une lettre « L » en vert, dans le disque blanc
        if (0.40 <= u <= 0.50 and 0.30 <= v <= 0.70) or (0.40 <= u <= 0.66 and 0.60 <= v <= 0.70):
            return bytes(vert)
        return bytes(blanc)

    brut = bytearray()
    for y in range(taille):
        brut.append(0)
        for x in range(taille):
            brut.extend(pixel(x, y))

    def bloc(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)

    return (b'\x89PNG\r\n\x1a\n' + bloc(b'IHDR', struct.pack('>IIBBBBB', taille, taille, 8, 2, 0, 0, 0)) +
            bloc(b'IDAT', zlib.compress(bytes(brut), 9)) + bloc(b'IEND', b''))


tpl = (SA / 'app.html').read_text(encoding='utf-8')


def rendu(pwa):
    # Version publique (site) : sans grille de travail ; la version autonome embarque la grille
    t = tpl.replace('__DONNEES__', js_json(dict(donnees, grilles=[]) if pwa else embarque))
    t = t.replace('__PWA_HEAD__', PWA_HEAD if pwa else '').replace('__PWA_SCRIPT__', PWA_SCRIPT if pwa else '')
    assert '__PWA' not in t and '__DONNEES__' not in t, 'marqueur non remplacé'
    return t


if embarque is not None:
    (SA / 'Lotofoot.html').write_text(rendu(False), encoding='utf-8')
(SITE / 'index.html').write_text(rendu(True), encoding='utf-8')
assert 'N°153' not in (SITE / 'index.html').read_text(encoding='utf-8'), 'grille de travail présente dans la version publique'
(SITE / 'donnees.json').write_text(json.dumps(donnees, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
(SITE / 'sw.js').write_text(SW, encoding='utf-8')
(SITE / 'manifest.webmanifest').write_text(json.dumps(MANIFEST, ensure_ascii=False, indent=1), encoding='utf-8')
(SITE / 'icone-192.png').write_bytes(icone(192))
(SITE / 'icone-512.png').write_bytes(icone(512))

with zipfile.ZipFile(SA / 'lotofoot-site.zip', 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted(SITE.iterdir()):
        z.write(f, f.name)

# Vérification de la syntaxe JavaScript des pages et du service worker : une erreur arrête la construction
verif = SA / 'tests'
verif.mkdir(parents=True, exist_ok=True)
pages = (['Lotofoot.html'] if embarque is not None else []) + ['site/index.html']
for nom in pages:
    html = (SA / nom).read_text(encoding='utf-8')
    principal = max(re.findall(r'<script>(.*?)</script>', html, re.S), key=len)
    p = verif / 'verif_page.js'
    p.write_text(principal, encoding='utf-8')
    r = subprocess.run(['node', '--check', str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    print(nom, '| syntaxe : OK')
r = subprocess.run(['node', '--check', str(SITE / 'sw.js')], capture_output=True, text=True)
assert r.returncode == 0, r.stderr
print('sw.js | syntaxe : OK')
fichiers = ([SA / 'Lotofoot.html'] if embarque is not None else []) + [SITE / 'index.html', SITE / 'donnees.json', SA / 'lotofoot-site.zip']
for f in fichiers:
    print(f.name, round(f.stat().st_size / 1024), 'Ko')
