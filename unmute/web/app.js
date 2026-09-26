/* ================= Unmute core ================= */
"use strict";
const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clampN = (n, a, b) => Math.max(a, Math.min(b, n));
const debounce = (fn, ms) => { let tm; return (...a) => { clearTimeout(tm); tm = setTimeout(() => fn(...a), ms); }; };
const AV_EMOJI = ["\u{1F9D1}\u200D\u{1F680}","\u{1F98A}","\u{1F43B}","\u{1F43C}","\u{1F42F}","\u{1F438}","\u{1F981}","\u{1F428}","\u{1F984}","\u{1F433}","\u{1F338}","\u{1F319}","\u2B50","\u{1F525}","\u{1F340}","\u{1F388}","\u{1F3A7}","\u{1F3AF}","\u{1F9E0}","\u{1F916}"];
const AV_COLORS = ["#6d5ef1","#0ea5e9","#10b981","#f59e0b","#ef4444","#ec4899","#8b5cf6","#14b8a6"];
const ACCENTS = ["violet","blue","green","orange","red","pink"];
const REACTS = ["❤️","👍","👎","😂","😮","😢","🔥","👏"];

/* ---------- state ---------- */
const S = {
  token: localStorage.getItem("um_token") || "",
  me: null, settings: null, email: "", verified: false,
  chats: [], usersCache: {}, notifs: [], unreadTotal: 0,
  route: { name: "chats", arg: null }, ws: null, wsOk: false, wsRetry: 0,
  onlineMap: {}, typingMap: {}, curChat: null, msgs: [], pins: [],
  fwdSel: null, recentEmoji: JSON.parse(localStorage.getItem("um_emoji") || "[]"),
};
function saveToken(tok, remember) {
  S.token = tok || "";
  try { localStorage.removeItem("um_token"); sessionStorage.removeItem("um_token"); } catch (e) {}
  if (tok) { try { (remember === false ? sessionStorage : localStorage).setItem("um_token", tok); } catch (e) {} }
}
if (!S.token) S.token = sessionStorage.getItem("um_token") || "";

/* ---------- api ---------- */
async function api(method, path, body, opts) {
  opts = opts || {};
  const h = {};
  if (S.token) h["Authorization"] = "Bearer " + S.token;
  let bd = undefined;
  if (body !== undefined && !(body instanceof FormData)) { h["Content-Type"] = "application/json"; bd = JSON.stringify(body); }
  else if (body instanceof FormData) bd = body;
  let r;
  try {
    r = await fetch(path, { method, headers: h, body: bd, signal: opts.signal });
  } catch (e) { throw { net: true }; }
  let j = null;
  try { j = await r.json(); } catch (e) { throw { net: true, status: r.status }; }
  if (r.status === 401 && S.token && !opts.noAuth) { onUnauthorized(); throw { auth: true }; }
  return { status: r.status, data: j };
}
const GET = (p, o) => api("GET", p, undefined, o);
const POST = (p, b, o) => api("POST", p, b, o);
const PATCH = (p, b, o) => api("PATCH", p, b, o);
const DEL = (p, b, o) => api("DELETE", p, b, o);
function errMsg(e, dflt) {
  if (!e) return t(dflt || "err_net");
  if (e.net) return t("err_net");
  const code = (e && e.data && e.data.error) || e.error || "";
  const map = { username: "err_username", username_taken: "err_username_taken", pass_short: "err_pass_short", display: "err_display", email: "err_email", email_taken: "err_email_taken", bad_creds: "err_bad_creds", banned: "err_banned", suspended: "err_suspended", rate: "err_rate", blocked: "err_blocked", privacy: "err_privacy", empty: "err_empty", type: "err_file_type", too_big: "err_file_big", bad_code: "err_bad_code", bad_token: "err_bad_token", bad_old: "err_bad_old", self: "err_self", notfound: "err_notfound", not_member: "err_notfound", unauthorized: "need_login" };
  return t(map[code] || dflt || "err_net");
}
function mediaUrl(att) { return att.url + "?token=" + encodeURIComponent(S.token); }

/* ---------- toast / modal / ctx ---------- */
function toast(msg, isErr) {
  const d = document.createElement("div");
  d.className = "toast" + (isErr ? " err" : "");
  d.textContent = msg;
  $("#toasts").appendChild(d);
  setTimeout(() => { d.style.opacity = "0"; d.style.transition = ".3s"; setTimeout(() => d.remove(), 320); }, 2600);
}
function modal(html) {
  const root = $("#modal-root");
  root.innerHTML = '<div class="overlay"><div class="modal" role="dialog" aria-modal="true">' + html + "</div></div>";
  const ov = root.firstElementChild;
  ov.addEventListener("mousedown", e => { if (e.target === ov) closeModal(); });
  const f = ov.querySelector("input,textarea,select,button"); if (f) setTimeout(() => f.focus(), 50);
  return ov;
}
function closeModal() { $("#modal-root").innerHTML = ""; }
function confirmDlg(text, okLabel, danger) {
  return new Promise(res => {
    const ov = modal('<h3>' + esc(text) + '</h3><div class="macts"><button class="btn ghost" id="cf-no">' + t("no") + '</button><button class="btn ' + (danger ? "danger" : "") + '" id="cf-yes">' + esc(okLabel || t("yes")) + "</button></div>");
    ov.querySelector("#cf-no").onclick = () => { closeModal(); res(false); };
    ov.querySelector("#cf-yes").onclick = () => { closeModal(); res(true); };
  });
}
function ctxMenu(x, y, items) {
  closeCtx();
  const root = $("#ctx-root");
  const d = document.createElement("div");
  d.className = "ctx"; d.setAttribute("role", "menu");
  d.innerHTML = items.map((it, i) => it.sep ? '<div class="sep"></div>' : '<button data-i="' + i + '" class="' + (it.danger ? "danger" : "") + '"><span>' + it.icon + '</span><span>' + esc(it.label) + "</span></button>").join("");
  root.appendChild(d);
  const r = d.getBoundingClientRect();
  d.style.left = clampN(x, 8, innerWidth - r.width - 8) + "px";
  d.style.top = clampN(y, 8, innerHeight - r.height - 8) + "px";
  d.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    const it = items[+b.dataset.i];
    closeCtx(); if (it.fn) it.fn();
  });
  setTimeout(() => document.addEventListener("mousedown", ctxOutside, { once: true }), 10);
}
function ctxOutside(e) { if (!e.target.closest(".ctx")) closeCtx(); else setTimeout(() => document.addEventListener("mousedown", ctxOutside, { once: true }), 10); }
function closeCtx() { $("#ctx-root").innerHTML = ""; }

/* ---------- format helpers ---------- */
function avatarHTML(u, cls) {
  const a = (u && u.avatar) || { emoji: "🧑", color: "#6d5ef1" };
  const on = u && u.online ? '<span class="on"></span>' : "";
  const img = a.img ? '<img src="' + esc(a.img) + "?token=" + encodeURIComponent(S.token) + '" alt="" loading="lazy" onerror="this.remove()">' : "";
  return '<div class="av ' + (cls || "") + '" style="background:' + esc(a.color) + '">' + esc(a.emoji) + img + on + "</div>";
}
function timeHM(ts) {
  const d = new Date(ts); const h = d.getHours(), m = d.getMinutes();
  return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
}
function dayLabel(ts) {
  const d = new Date(ts), now = new Date();
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (day === today) return t("today");
  if (day === today - 864e5) return t("yesterday");
  return d.toLocaleDateString(LANG === "fa" ? "fa-IR" : "en-US");
}
function chatTime(ts) {
  const d = new Date(ts), now = new Date();
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  if (day === today) return timeHM(ts);
  if (day > today - 6 * 864e5) return d.toLocaleDateString(LANG === "fa" ? "fa-IR" : "en-US", { weekday: "short" });
  return d.toLocaleDateString(LANG === "fa" ? "fa-IR" : "en-US", { day: "numeric", month: "short" });
}
function lastSeenTx(ts, online) {
  if (online) return t("online");
  if (!ts) return t("offline");
  const m = Math.floor((Date.now() - ts) / 60000);
  if (m < 1) return t("just_now");
  if (m < 60) return m + " " + t("min_ago");
  const h = Math.floor(m / 60);
  if (h < 24) return h + " " + t("hour_ago");
  return Math.floor(h / 24) + " " + t("day_ago");
}
function fmtSize(n) {
  if (n > 1048576) return (n / 1048576).toFixed(1) + " MB";
  if (n > 1024) return Math.round(n / 1024) + " KB";
  return n + " B";
}
function fmtDur(s) { s = Math.round(s || 0); return Math.floor(s / 60) + ":" + (s % 60 < 10 ? "0" : "") + (s % 60); }
function mdLite(s) {
  let h = esc(s);
  h = h.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`(.+?)`/g, "<code>$1</code>").replace(/\n/g, "<br>");
  h = h.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
  h = h.replace(/(^|[\s(>])(@[A-Za-z0-9_]{1,30})/g, '$1<span class="mention" data-mention="$2">$2</span>');
  return h;
}
function ticksHTML(m) {
  if (!m || m.sender_id !== (S.me && S.me.id)) return "";
  if (m.read) return '<span style="color:#5eead4">✓✓</span>';
  if (m.delivered) return "<span>✓✓</span>";
  return "<span>✓</span>";
}

/* ---------- sound + browser notifications ---------- */
let AC = null;
function beep() {
  try {
    if (!S.settings || !S.settings.notif_sound) return;
    AC = AC || new (window.AudioContext || window.webkitAudioContext)();
    const o = AC.createOscillator(), g = AC.createGain();
    o.connect(g); g.connect(AC.destination);
    o.frequency.value = 880; g.gain.value = 0.08;
    o.start(); o.stop(AC.currentTime + 0.12);
    setTimeout(() => { const o2 = AC.createOscillator(), g2 = AC.createGain(); o2.connect(g2); g2.connect(AC.destination); o2.frequency.value = 660; g2.gain.value = 0.08; o2.start(); o2.stop(AC.currentTime + 0.14); }, 130);
  } catch (e) {}
}
function browserNotify(title, body, onclick) {
  try {
    if (!S.settings || !S.settings.notif_browser) return;
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const n = new Notification(title, { body, icon: "/logo.svg", tag: "um" });
    if (onclick) n.onclick = () => { window.focus(); onclick(); n.close(); };
  } catch (e) {}
}
async function ensureBrowserPerm() {
  try {
    if ("Notification" in window && Notification.permission === "default") await Notification.requestPermission();
  } catch (e) {}
}
function updateBadge() {
  const n = S.chats.reduce((a, c) => a + (c.muted ? 0 : (c.unread || 0)), 0);
  S.unreadTotal = n;
  document.title = (n ? "(" + n + ") " : "") + "Unmute";
  try { if ("setAppBadge" in navigator) (n ? navigator.setAppBadge(n) : navigator.clearAppBadge()); } catch (e) {}
  const b = $("#nav-badge"); if (b) { b.style.display = n ? "grid" : "none"; b.textContent = n > 99 ? "99+" : n; }
}

/* ---------- websocket ---------- */
function wsConnect() {
  if (!S.token || S.ws) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  let ws;
  try { ws = new WebSocket(proto + "://" + location.host + "/ws?token=" + encodeURIComponent(S.token)); } catch (e) { return wsRetry(); }
  S.ws = ws;
  ws.onopen = () => {
    S.wsOk = true; S.wsRetry = 0; $("#connbar").classList.remove("show");
    const iv = setInterval(() => { if (ws.readyState === 1) ws.send(JSON.stringify({ t: "ping" })); else clearInterval(iv); }, 30000);
  };
  ws.onmessage = ev => {
    let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
    onWS(m);
  };
  ws.onclose = () => {
    const was = S.wsOk;
    S.ws = null; S.wsOk = false;
    if (S.token) {
      $("#connbar").textContent = t("conn_lost"); $("#connbar").classList.add("show");
      wsRetry();
    }
    if (was) renderSideBadges();
  };
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
}
function wsRetry() {
  S.wsRetry++;
  setTimeout(wsConnect, clampN(S.wsRetry * 1500, 1500, 15000));
}
function wsSend(o) { try { if (S.ws && S.ws.readyState === 1) S.ws.send(JSON.stringify(o)); } catch (e) {} }
function onWS(m) {
  if (!m || !m.t) return;
  if (m.t === "msg" || m.msg) { onWSMsg(m.msg || m); }
  else if (m.t === "react" || m.t === "pin" || m.t === "deleted_all" || m.t === "deleted_me") { onWSMsg(m); }
  else if (m.t === "notify") { onWSNotify(m); }
  else if (m.t === "typing") {
    S.typingMap[m.chat_id] = { uid: m.uid, name: m.name, at: Date.now() };
    if (S.curChat === m.chat_id && typeof renderTyping === "function") renderTyping();
    setTimeout(() => { if (Date.now() - (S.typingMap[m.chat_id] || {}).at > 4000) { delete S.typingMap[m.chat_id]; if (S.curChat === m.chat_id && typeof renderTyping === "function") renderTyping(); } }, 4200);
  }
  else if (m.t === "presence") {
    if (m.uid) { S.onlineMap[m.uid] = !!m.online; paintPresence(m.uid, m.online); }
    if (m.user) { S.usersCache[m.user.username] = m.user; }
  }
  else if (m.t === "read") { onWSRead(m); }
  else if (m.t === "chats_changed") {
    if (typeof loadChats === "function") loadChats().then(() => {
      if (S.curChat && typeof paintHeadStatus === "function") paintHeadStatus();
      if (S.gmemberChat && typeof loadChatMembers === "function") loadChatMembers(S.gmemberChat);
    }).catch(() => {});
  }
}
function onUnauthorized() {
  saveToken(""); S.me = null;
  try { if (S.ws) S.ws.close(); } catch (e) {}
  S.ws = null;
  location.hash = "#/login";
}

/* ---------- theme / settings apply ---------- */
function applySettings() {
  const s = S.settings || {};
  let th = s.theme || "system";
  if (th === "system") th = (matchMedia("(prefers-color-scheme: light)").matches) ? "light" : "dark";
  document.documentElement.dataset.theme = th;
  document.documentElement.dataset.accent = s.accent || "violet";
  document.documentElement.dataset.fs = s.font_size || "md";
  if (s.lang && s.lang !== LANG) { setLang(s.lang); rerender(); }
}
function applyLang() { setLang(LANG); }

/* ---------- shell ---------- */
function shellHTML() {
  return '<div class="app-shell">' +
    '<nav class="side" aria-label="main">' +
    '<div class="brand"><img src="/logo.svg" alt="Unmute"></div>' +
    navBtn("chats", "💬", "chats", "nav-badge") + navBtn("contacts", "👥", "contacts") +
    navBtn("search", "🔍", "search") + navBtn("notifications", "🔔", "notifications", "nav-badge-n") +
    '<div class="sp"></div>' +
    (S.me && S.me.role === "admin" ? navBtn("admin", "🛡️", "admin") : "") +
    navBtn("settings", "⚙️", "settings") +
    '<button class="me-dot" id="nav-me" aria-label="profile"></button>' +
    "</nav>" +
    '<div id="pane-wrap" style="display:contents"></div>' +
    '<main class="main" id="main"></main>' +
    "</div>";
}
function navBtn(name, icon, label, bdg) {
  return '<button class="nav-btn" data-nav="' + name + '" aria-label="' + label + '">' + icon + "<small>" + esc(t(label)) + "</small>" + (bdg ? '<span class="bdg" id="' + bdg + '" style="display:none"></span>' : "") + "</button>";
}
function renderSideBadges() {
  $$(".nav-btn").forEach(b => b.classList.toggle("on", b.dataset.nav === S.route.name || (S.route.name === "chat" && b.dataset.nav === "chats")));
  const me = $("#nav-me");
  if (me && S.me) { me.style.background = (S.me.avatar || {}).color || "#6d5ef1"; me.textContent = (S.me.avatar || {}).emoji || "🧑"; }
  updateBadge();
  const nn = S.notifs.filter(n => !n.read).length;
  const nb = $("#nav-badge-n"); if (nb) { nb.style.display = nn ? "grid" : "none"; nb.textContent = nn > 99 ? "99+" : nn; }
}

/* ---------- router ---------- */
function parseHash() {
  const h = (location.hash || "#/chats").slice(2);
  const parts = h.split("/");
  return { name: parts[0] || "chats", arg: decodeURIComponent(parts[1] || ""), arg2: decodeURIComponent(parts[2] || "") };
}
async function router() {
  closeCtx(); closeModal();
  S.route = parseHash();
  const pub = ["login", "register", "forgot", "reset"];
  if (!S.token && !pub.includes(S.route.name)) { location.hash = "#/login"; return; }
  if (S.token && !S.me) {
    try {
      const r = await GET("/api/me");
      if (r.data.ok) { S.me = r.data.user; S.settings = r.data.settings; S.email = r.data.email; S.verified = r.data.verified; applySettings(); wsConnect(); loadNotifs(); }
      else { onUnauthorized(); return; }
    } catch (e) { if (e.auth) return; }
  }
  renderSideBadges();
  const n = S.route.name;
  if (n === "login" || n === "register" || n === "forgot" || n === "reset") return VIEWS.auth(n);
  if (!S.me) { location.hash = "#/login"; return; }
  if (!$("#pane-wrap")) $("#app").innerHTML = shellHTML();
  bindNav();
  renderSideBadges();
  if (n === "chat") return renderChatWrap();
  S.curChat = null;
  if (n === "chats") return renderChatsHome();
  if (n === "contacts") return VIEWS.contacts();
  if (n === "search") return VIEWS.search();
  if (n === "notifications") return VIEWS.notifications();
  if (n === "settings") return VIEWS.settings();
  if (n === "profile") return VIEWS.profile();
  if (n === "join") return VIEWS.join();
  if (n === "admin") return VIEWS.admin();
  location.hash = "#/chats";
}
function bindNav() {
  $$(".nav-btn").forEach(b => b.onclick = () => { location.hash = "#/" + b.dataset.nav; });
  const me = $("#nav-me"); if (me) me.onclick = () => { location.hash = "#/profile/" + S.me.username; };
}
function rerender() { router(); }

async function loadNotifs() {
  try {
    const r = await GET("/api/notifications");
    if (r.data.ok) { S.notifs = r.data.notifications; renderSideBadges(); }
  } catch (e) {}
}

/* ---------- boot / pwa ---------- */
function boot() {
  applyLang();
  setLang(LANG);
  window.addEventListener("hashchange", router);
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { closeModal(); closeCtx(); if (typeof closeGallery === "function") closeGallery(); }
  });
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", applySettings);
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").then(reg => {
      reg.addEventListener("updatefound", () => {
        const w = reg.installing;
        w.addEventListener("statechange", () => {
          if (w.state === "installed" && navigator.serviceWorker.controller) {
            $("#updbar-tx").textContent = t("new_version_msg");
            $("#updbar-btn").textContent = t("reload");
            $("#updbar-btn").onclick = () => w.postMessage && location.reload();
            $("#updbar").classList.add("show");
          }
        });
      });
    }).catch(() => {});
  }
  router();
}
const VIEWS = {};
