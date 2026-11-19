const CACHE = 'frame-pwa-v1';
const OFFLINE = '/static/offline.html';
// Explicitly public assets only. Never add library pages, media or OIDC responses.
const PUBLIC_ASSETS = [OFFLINE, '/static/brand/frame-mark.svg',
  '/static/brand/icon-192.png', '/static/brand/icon-512.png',
  '/static/brand/icon-maskable-512.png', '/static/brand/apple-touch-icon.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(PUBLIC_ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key.startsWith('frame-pwa-') && key !== CACHE).map(key => caches.delete(key))
  )).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin ||
      ['/login', '/auth/callback', '/logout'].includes(url.pathname)) return;
  if (PUBLIC_ASSETS.includes(url.pathname) && !url.search) {
    event.respondWith(caches.open(CACHE).then(async cache => (await cache.match(request)) || fetch(request)));
  } else if (request.mode === 'navigate') {
    event.respondWith(fetch(request, {cache: 'no-store'}).catch(async () => {
      const cache = await caches.open(CACHE);
      const offline = await cache.match(OFFLINE);
      return offline || Response.error();
    }));
  }
});
