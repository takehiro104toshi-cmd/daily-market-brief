'use strict';
// P11-A3 ／ A4 — shell-only service worker. Precaches the committed shell assets and nothing else, failing closed.
// /api/*, /health and /version are never handled and never cached. No push, sync, periodic sync or messages.
const SHELL_CACHE = 'p11-shell-2729564d0ff5';
const PRECACHE = ['/app/', '/app/index.html', '/app/app.js', '/app/app.css', '/app/manifest.webmanifest',
  '/app/icon-192.png', '/app/icon-512.png'];
const NETWORK_ONLY_PREFIXES = ['/api/', '/health', '/version'];

function precacheOne(cache, path) {
  return fetch(new Request(path, { cache: 'reload', credentials: 'omit', redirect: 'error' })).then(function (response) {
    // only a plain same-origin 200 is kept: no redirect, no opaque/error response, no partial content
    if (response.status !== 200 || response.type !== 'basic' || response.redirected) {
      throw new Error('shell asset unavailable');
    }
    return cache.put(path, response);
  });
}

self.addEventListener('install', function (event) {
  event.waitUntil(caches.open(SHELL_CACHE)
    .then(function (cache) { return Promise.all(PRECACHE.map(function (path) { return precacheOne(cache, path); })); })
    .catch(function (error) { // fail closed: a partial shell cache is never left behind
      return caches.delete(SHELL_CACHE).then(function () { throw error; });
    })
    .then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys()
    .then(function (names) { // only prior P11 shell namespaces are removed; other caches are never touched
      return Promise.all(names
        .filter(function (name) { return name.indexOf('p11-shell-') === 0 && name !== SHELL_CACHE; })
        .map(function (name) { return caches.delete(name); }));
    })
    .then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (event) {
  const request = event.request;
  if (request.method !== 'GET') { return; }
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || url.search !== '') { return; }
  if (NETWORK_ONLY_PREFIXES.some(function (prefix) { return url.pathname.indexOf(prefix) === 0; })) { return; }
  if (PRECACHE.indexOf(url.pathname) === -1) { return; }
  event.respondWith(caches.open(SHELL_CACHE)
    .then(function (cache) { return cache.match(url.pathname); })
    .then(function (hit) { return hit || fetch(request); })); // a miss goes to the network and is not stored
});
