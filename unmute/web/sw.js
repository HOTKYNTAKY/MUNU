/* Unmute service worker — HTML network-first (updates propagate fast), assets cached, API network-only */
const V = "um3";
const SHELL = ["/", "/index.html", "/style.css?v=2", "/app.js", "/views.js", "/chat.js", "/i18n.js", "/logo.svg", "/manifest.webmanifest"];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (u.pathname.startsWith("/api/") || u.pathname === "/ws") return; // network only
  if (e.request.method !== "GET") return;
  const isHTML = u.pathname === "/" || u.pathname === "/index.html" || e.request.mode === "navigate";
  e.respondWith(
    caches.open(V).then(async ch => {
      if (isHTML) {
        try {
          const r = await fetch(e.request);
          if (r.ok) ch.put(e.request, r.clone());
          return r;
        } catch (err) {
          return await ch.match(e.request, { ignoreSearch: u.pathname === "/" });
        }
      }
      const hit = await ch.match(e.request);
      const net = fetch(e.request).then(r => {
        if (r.ok) ch.put(e.request, r.clone());
        return r;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
