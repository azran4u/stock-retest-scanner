// Network-first service worker: always fresh when online, cached copy when offline.
const CACHE = 'srs-app-v2';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  e.respondWith(
    // pages / html / the worker itself: always revalidate (GitHub Pages sends max-age=600); hashed assets: normal
    fetch(req, req.mode === 'navigate' || /\.(html|webmanifest)$|\/$/.test(new URL(req.url).pathname) ? { cache: 'no-cache' } : undefined).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req).then((r) => r || Response.error()))
  );
});
