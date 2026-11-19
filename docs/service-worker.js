// Woningrapport: service worker. Afgeleid uit de bestanden door funda_rapport.py; niet met de hand wijzigen.
const CACHE = 'funda-shortlist-37374a263e';
// Statische bestanden met hun versie: de eerste 10 hextekens van de sha256 van de inhoud.
const VERSIES = {
  'app.css': '9ac584e38c',
  'app.js': 'ceda2ee84b',
  'leaflet/leaflet.css': 'a783710282',
  'leaflet/leaflet.js': 'db49d009c8',
  'push.js': 'e9cffc8527',
  'slot.css': 'e758187e81',
  'slot.js': '57996ff0d4'
};
const LOS = ['./', 'index.html', 'manifest.json', 'icon.svg', 'favicon.svg', 'apple-touch-icon.png', 'icon-512.png'];
const BASIS = new URL('./', self.location).pathname;
const sleutel = p => p + '?v=' + VERSIES[p];
async function klopt(resp, versie) {
  const som = new Uint8Array(await crypto.subtle.digest('SHA-256', await resp.clone().arrayBuffer()));
  return Array.from(som.slice(0, versie.length / 2), b => b.toString(16).padStart(2, '0')).join('') === versie;
}
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(async c => {
    await c.addAll(LOS);
    // Een bestand waarvan de inhoud niet bij de versie past (update nog onderweg) blijft uit de cache.
    await Promise.all(Object.keys(VERSIES).map(async p => {
      const resp = await fetch(sleutel(p));
      if (resp.ok && await klopt(resp, VERSIES[p])) await c.put(sleutel(p), resp);
    }));
  }));
});
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim())
));
async function antwoord(req, url) {
  const c = await caches.open(CACHE);
  const p = url.pathname.startsWith(BASIS) ? url.pathname.slice(BASIS.length) : '';
  const vast = Object.prototype.hasOwnProperty.call(VERSIES, p);
  const huidig = vast && url.searchParams.get('v') === VERSIES[p];
  if (huidig) {
    const r = await c.match(sleutel(p));
    if (r) return r;
  }
  try {
    const resp = await fetch(req);
    if (resp.ok && resp.type === 'basic') {
      if (!vast) c.put(req, resp.clone()).catch(()=>{});
      else if (huidig && await klopt(resp, VERSIES[p])) c.put(sleutel(p), resp.clone()).catch(()=>{});
    }
    return resp;
  } catch (_) {
    const r = await c.match(vast ? sleutel(p) : req) || (req.mode === 'navigate' ? await c.match('index.html') : null);
    return r || Response.error();
  }
}
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  e.respondWith(antwoord(e.request, url));
});
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch(_) {
    data = { title: 'Nieuwe woningen', body: e.data ? e.data.text() : '' };
  }
  const title = data.title || 'Nieuwe woningen';
  const options = {
    body: data.body || 'Open het rapport voor de nieuwste woningen.',
    icon: 'icon-512.png',
    badge: 'apple-touch-icon.png',
    data: { url: data.url || './' },
    tag: data.tag || 'funda-new-listings',
    renotify: true
  };
  e.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const target = e.notification.data && e.notification.data.url ? e.notification.data.url : './';
  e.waitUntil((async () => {
    const allClients = await clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of allClients) {
      if ('focus' in client) return client.focus();
    }
    if (clients.openWindow) return clients.openWindow(target);
  })());
});
