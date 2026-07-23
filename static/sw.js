const CACHE_VERSION = 'ba-panel-v2';
const SHELL_CACHE = CACHE_VERSION + '-shell';
const PAGES_CACHE = CACHE_VERSION + '-pages';

const PRECACHE_URLS = [
  '/static/offline.html',
  '/static/js/dashboard-ui.js',
  '/static/js/pwa.js',
  '/static/css/dashboard.css',
  '/static/icons/icon.svg',
  '/static/icons/maskable.svg',
  '/static/manifest.json',
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(SHELL_CACHE).then(function (cache) {
      return cache.addAll(PRECACHE_URLS);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys
          .filter(function (key) {
            return key.startsWith('ba-panel-') && key !== SHELL_CACHE && key !== PAGES_CACHE;
          })
          .map(function (key) { return caches.delete(key); })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

function esNavegacionDashboard(request) {
  return request.mode === 'navigate' && request.url.includes('/dashboard/');
}

function esEstatico(request) {
  return request.url.includes('/static/');
}

self.addEventListener('fetch', function (event) {
  const request = event.request;
  if (request.method !== 'GET') return;

  if (esEstatico(request)) {
    event.respondWith(
      caches.match(request).then(function (cached) {
        var fetchPromise = fetch(request).then(function (response) {
          if (response && response.status === 200) {
            var clone = response.clone();
            caches.open(SHELL_CACHE).then(function (cache) {
              cache.put(request, clone);
            });
          }
          return response;
        }).catch(function () { return cached; });
        return cached || fetchPromise;
      })
    );
    return;
  }

  if (esNavegacionDashboard(request)) {
    event.respondWith(
      fetch(request)
        .then(function (response) {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(PAGES_CACHE).then(function (cache) {
              cache.put(request, clone);
            });
          }
          return response;
        })
        .catch(function () {
          return caches.match(request).then(function (cached) {
            return cached || caches.match('/static/offline.html');
          });
        })
    );
    return;
  }
});
