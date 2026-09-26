/* Unmute service worker — offline shell, cache-first static, network-only API */
const V = "um1";
const SHELL = ["/", "/index.html", "/style.css", "/app.js", "/views.js", "/chat.js", "/i18n.js", "/logo.svg", "/manifest.webmanifest"];
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
  e.respondWith(
    caches.match(e.request, { ignoreSearch: u.pathname === "/" }).then(hit => {
      const net = fetch(e.request).then(r => {
        if (r.ok) { const c = r.clone(); caches.open(V).then(ch => ch.put(e.request, c)); }
        return r;
      }).catch(() => hit);
      return hit || net;
    })
  );
});
