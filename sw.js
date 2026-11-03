// Lotofoot : cache hors ligne.
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
