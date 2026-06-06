// Funda PWA service worker
const CACHE = 'funda-shortlist-v3';
const ASSETS = ['./', 'index.html', 'manifest.json', 'icon.svg', 'favicon.svg', 'apple-touch-icon.png', 'icon-512.png'];
self.addEventListener('install', e => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
});
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim())
));
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  e.respondWith(
    fetch(e.request).then(resp => {
      if (resp.ok) {
        const clone = resp.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone)).catch(()=>{});
      }
      return resp;
    }).catch(() => caches.match(e.request).then(r => r || caches.match('index.html')))
  );
});
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data ? e.data.json() : {}; } catch(_) {
    data = { title: 'Nieuwe Funda woningen', body: e.data ? e.data.text() : '' };
  }
  const title = data.title || 'Nieuwe Funda woningen';
  const options = {
    body: data.body || 'Open de shortlist voor de nieuwste matches.',
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
