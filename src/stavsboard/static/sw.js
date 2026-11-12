// Stavsboard service worker: keeps the page itself (HTML, CSS, JS, fonts, icons) on the device
// so the installed app opens at once, even when the server can't be reached. It never touches
// /api: old numbers shown as if live would be lying, so the page says "can't reach" instead.
// Served from /sw.js (not /static/) so its scope covers the whole app.
"use strict";
const CACHE = "stavsboard-shell-v1";
const SHELL = [
  "./",
  "static/app.css",
  "static/app.js",
  "static/theme.js",
  "static/manifest.webmanifest",
  "static/fonts/schibsted-grotesk-var.woff2",
  "static/fonts/instrument-serif-400.woff2",
  "static/icons/icon-192.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key);
    await self.clients.claim();
  })());
});

// Network first, cache as fallback: online you always get the version the server runs now;
// offline you still get the page, which then shows that the server can't be reached.
self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  const scope = new URL(self.registration.scope);
  if (url.pathname.startsWith(`${scope.pathname}api/`)) return; // live data: browser handles it
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    try {
      const res = await fetch(req);
      if (res.ok) await cache.put(req.mode === "navigate" ? "./" : req, res.clone());
      return res;
    } catch (err) {
      const hit = await cache.match(req.mode === "navigate" ? "./" : req, { ignoreSearch: req.mode === "navigate" });
      if (hit) return hit;
      throw err;
    }
  })());
});
