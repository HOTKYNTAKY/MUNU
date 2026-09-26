/* ================= Unmute chat ================= */
"use strict";
S.older = true; S.replyTo = null; S.editId = null; S.loadingMsgs = false;
let msgById = {}, showArchived = false, nearBottom = true, jumpCount = 0;

async function loadChats() {
  try {
    const r = await GET("/api/chats");
    if (r.data.ok) { S.chats = r.data.chats; S.chats.forEach(c => { S.onlineMap[c.peer.id] = !!c.peer.online; }); }
  } catch (e) {}
  paintPane(); updateBadge();
}
function chatById(id) { return S.chats.find(c => c.id === +id); }

/* ---------- pane ---------- */
async function renderChatsHome() {
  paintPane(); paintMainHome(); applyMobile("pane");
  await loadChats();
  if (S.route.name === "chats") { paintPane(); paintMainHome(); applyMobile("pane"); }
}
function paintPane() {
  const w = $("#pane-wrap"); if (!w) return;
  const list = S.chats.filter(c => showArchived ? c.archived : !c.archived);
  const archN = S.chats.filter(c => c.archived).length;
  w.innerHTML = '<aside class="pane" id="pane">' +
    '<div class="pane-head"><h2>' + t("chats") + '</h2>' +
    '<button class="icon-btn" id="pane-new" title="' + t("new_chat") + '" aria-label="' + t("new_chat") + '">✚</button></div>' +
    '<div class="srch"><span>🔍</span><input id="pane-q" placeholder="' + t("search") + '" aria-label="' + t("search") + '"></div>' +
    '<div class="chat-list" id="clist" role="list"></div>' +
    (archN && !showArchived ? '<div style="padding:8px 14px"><button class="link" id="arch-btn">📦 ' + t("archived") + " (" + archN + ")</button></div>" : "") +
    (showArchived ? '<div style="padding:8px 14px"><button class="link" id="arch-back">← ' + t("chats") + "</button></div>" : "") +
    "</aside>";
  $("#pane-new").onclick = () => { location.hash = "#/search"; };
  const ab = $("#arch-btn"); if (ab) ab.onclick = () => { showArchived = true; paintPane(); };
  const ab2 = $("#arch-back"); if (ab2) ab2.onclick = () => { showArchived = false; paintPane(); };
  $("#pane-q").oninput = debounce(e => paintChatItems(e.target.value.trim()), 200);
  paintChatItems("");
}
function paintChatItems(filter) {
  const el = $("#clist"); if (!el) return;
  let list = S.chats.filter(c => showArchived ? c.archived : !c.archived);
  if (filter) { const f = filter.toLowerCase(); list = list.filter(c => (c.peer.display_name + " " + c.peer.username).toLowerCase().includes(f)); }
  if (!list.length) {
    el.innerHTML = '<div class="empty"><div class="big">💬</div><h3>' + t("empty_chats") + "</h3><p>" + t("empty_chats_hint") + "</p></div>";
    return;
  }
  el.innerHTML = list.map(c => {
    const last = c.last ? lastPreview(c.last) : "";
    const tm = c.last ? chatTime(c.last.created_at) : "";
    return '<button class="ci' + (S.curChat === c.id ? " on" : "") + '" data-chat="' + c.id + '" role="listitem">' +
      avatarHTML(c.peer) +
      '<span class="tx"><span class="nm">' + esc(c.peer.display_name) + (c.pinned ? ' <span class="tag">📌</span>' : "") + (c.muted ? ' <span class="tag">🔇</span>' : "") + "</span>" +
      '<span class="lm">' + last + "</span></span>" +
      '<span class="mt"><span class="tm">' + tm + "</span>" + (c.unread ? '<span class="unread">' + (c.unread > 99 ? "99+" : c.unread) + "</span>" : "") + "</span></button>";
  }).join("");
  $$(".ci", el).forEach(b => {
    b.onclick = () => { location.hash = "#/chat/" + b.dataset.chat; };
    b.oncontextmenu = e => { e.preventDefault(); chatCtx(e.clientX, e.clientY, +b.dataset.chat); };
  });
}
function lastPreview(m) {
  if (!m || m.deleted_all) return "🚫 " + t("deleted_msg");
  let p = "";
  if (m.sender_id === (S.me && S.me.id)) p = (m.read ? "✓✓ " : (m.delivered ? "✓✓ " : "✓ ")) ;
  if (m.type === "image") return p + "🖼 " + t("photo");
  if (m.type === "video") return p + "🎬 " + t("video");
  if (m.type === "audio" || m.type === "voice") return p + "🎤 " + t("voice_msg");
  if (m.type === "file") return p + "📎 " + t("file");
  return p + esc((m.text || "").slice(0, 60));
}
function paintMainHome() {
  const m = $("#main"); if (!m) return;
  m.innerHTML = '<div class="empty" style="margin:auto"><div class="big"><img src="/logo.svg" width="72" height="72" style="border-radius:20px"></div><h3>' + t("welcome") + "</h3><p>" + t("empty_chats_hint") + "</p></div>";
}
function applyMobile(which) {
  const pane = $("#pane"), main = $("#main");
  if (!pane || !main) return;
  pane.classList.toggle("hidden-m", which !== "pane");
  main.classList.toggle("hidden-m", which !== "main");
}

/* ---------- chat window ---------- */
async function renderChatWrap() {
  paintPane();
  const id = +S.route.arg;
  const around = +(S.route.arg2 || 0);
  if (!id) { location.hash = "#/chats"; return; }
  if (!S.chats.length) await loadChats();
  let c = chatById(id);
  if (!c) { try { await loadChats(); c = chatById(id); } catch (e) {} }
  if (!c) { $("#main").innerHTML = '<div class="empty" style="margin:auto"><div class="big">🔍</div><h3>' + t("chat_not_found") + "</h3></div>"; applyMobile("main"); return; }
  await openChat(id, around);
  applyMobile("main");
}
async function openChat(id, around) {
  S.curChat = id; S.replyTo = null; S.editId = null; msgById = {}; jumpCount = 0; nearBottom = true;
  const c = chatById(id);
  paintChatItems(paneQ());
  const m = $("#main");
  m.innerHTML =
    '<div class="chat-head"><button class="icon-btn back-btn" id="ch-back" aria-label="' + t("back") + '">←</button>' +
    '<span id="ch-av">' + avatarHTML(c.peer) + '</span><div class="tx" id="ch-tx"><div class="nm">' + esc(c.peer.display_name) + '</div><div class="st" id="ch-st"></div></div>' +
    '<button class="icon-btn" id="ch-menu" aria-label="' + t("menu") + '">⋮</button></div>' +
    '<div class="pins-bar" id="pins-bar" style="display:none"></div>' +
    '<div class="msgs" id="msgs" tabindex="0" aria-label="messages"><div class="spinner"></div></div>' +
    '<button class="jump" id="jump" aria-label="' + t("jump_down") + '">↓</button>' +
    '<div id="rp-wrap"></div><div class="composer" id="composer"></div>';
  $("#ch-back").onclick = () => { location.hash = "#/chats"; };
  $("#ch-tx").onclick = () => { location.hash = "#/profile/" + c.peer.username; };
  $("#ch-menu").onclick = e => chatCtx(e.clientX, e.clientY, id);
  $("#jump").onclick = () => { const box = $("#msgs"); box.scrollTop = box.scrollHeight; jumpCount = 0; $("#jump").classList.remove("show"); markRead(); };
  paintHeadStatus(); paintComposer(); paintReplyBar();
  const box = $("#msgs");
  box.addEventListener("scroll", () => {
    nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
    $("#jump").classList.toggle("show", !nearBottom && jumpCount > 0);
    if (box.scrollTop < 60 && S.older && !S.loadingMsgs && S.msgs.length) loadOlder();
  });
  await loadMsgs(id, around, true);
  renderTyping();
}
function paintHeadStatus() {
  const c = chatById(S.curChat); if (!c) return;
  const st = $("#ch-st"); if (!st) return;
  const ty = S.typingMap[S.curChat];
  if (ty && Date.now() - ty.at < 4000) { st.textContent = t("typing"); st.className = "st typ"; return; }
  const on = S.onlineMap[c.peer.id];
  st.textContent = on ? t("online") : t("last_seen") + " " + lastSeenTx(c.peer.last_seen, false);
  st.className = "st";
  const av = $("#ch-av"); if (av) av.innerHTML = avatarHTML({ avatar: c.peer.avatar, online: on });
}
function renderTyping() { paintHeadStatus(); }
function paintPresence(uid, online) {
  S.onlineMap[uid] = online;
  S.chats.forEach(c => { if (c.peer.id === uid) c.peer.online = online; });
  if ($("#clist")) paintChatItems(paneQ());
  if (S.curChat) { const c = chatById(S.curChat); if (c && c.peer.id === uid) paintHeadStatus(); }
}
async function loadMsgs(id, around, first) {
  S.loadingMsgs = true;
  try {
    let url = "/api/chats/" + id + "/messages?limit=40" + (around ? "&around=" + around : "");
    const r = await GET(url);
    if (!r.data.ok) throw r;
    S.msgs = r.data.msgs; S.older = r.data.older; S.pins = r.data.pins || [];
    msgById = {}; S.msgs.forEach(x => msgById[x.id] = x);
    renderMsgs(); paintPins();
    const box = $("#msgs");
    if (around) {
      const idx = S.msgs.findIndex(x => x.id === around);
      requestAnimationFrame(() => {
        const el = box.querySelector('[data-mid="' + around + '"]');
        if (el) { el.scrollIntoView({ block: "center" }); el.classList.add("flash"); }
        else box.scrollTop = box.scrollHeight;
      });
    } else box.scrollTop = box.scrollHeight;
    markRead();
  } catch (e) {
    $("#msgs").innerHTML = '<div class="empty"><div class="big">⚠️</div><h3>' + errMsg(e) + '</h3><button class="btn sm" id="m-retry">' + t("retry") + "</button></div>";
    const b = $("#m-retry"); if (b) b.onclick = () => loadMsgs(id, around, first);
  }
  S.loadingMsgs = false;
}
async function loadOlder() {
  if (!S.msgs.length) return;
  S.loadingMsgs = true;
  const box = $("#msgs");
  const first = S.msgs[0].id, oldH = box.scrollHeight;
  try {
    const r = await GET("/api/chats/" + S.curChat + "/messages?limit=40&before=" + first);
    if (r.data.ok && r.data.msgs.length) {
      r.data.msgs.forEach(x => msgById[x.id] = x);
      S.msgs = r.data.msgs.concat(S.msgs);
      S.older = r.data.older;
      renderMsgs();
      box.scrollTop = box.scrollHeight - oldH;
    } else S.older = false;
  } catch (e) {}
  S.loadingMsgs = false;
}
function renderMsgs() {
  const box = $("#msgs"); if (!box) return;
  const stick = nearBottom;
  let html = S.older ? "" : '<div class="day-sep">' + t("end_of_history") + "</div>";
  let lastDay = "";
  S.msgs.forEach(m => {
    const dl = dayLabel(m.created_at);
    if (dl !== lastDay) { html += '<div class="day-sep">' + dl + "</div>"; lastDay = dl; }
    html += msgHTML(m);
  });
  box.innerHTML = html;
  bindMsgs(box);
  if (stick) box.scrollTop = box.scrollHeight;
  bindAudio(box);
}
function msgHTML(m) {
  if (m.deleted_all) return '<div class="msg peer deleted" data-mid="' + m.id + '"><div class="bub">🚫 ' + t("deleted_msg") + '<span class="meta">' + timeHM(m.created_at) + "</span></div></div>";
  const me = m.sender_id === (S.me && S.me.id);
  let inner = "";
  if (m.reply_to && msgById[m.reply_to]) {
    const rp = msgById[m.reply_to];
    const nm = rp.sender_id === (S.me && S.me.id) ? (S.me.display_name) : ((chatById(S.curChat) || {}).peer || {}).display_name || "";
    inner += '<div class="reply-box" data-goto="' + rp.id + '"><b>' + esc(nm) + "</b>" + esc((rp.text || "📎").slice(0, 80)) + "</div>";
  }
  if ((m.text || "").includes("\n↪ fwd")) inner += '<div class="fwd-mark">↪ ' + t("fwd_mark") + "</div>";
  const txt = (m.text || "").replace(/\n↪ fwd$/, "");
  (m.atts || []).forEach(a => { inner += attHTML(a, m); });
  if (txt) inner += '<div class="tx">' + mdLite(txt) + "</div>";
  const rx = m.reactions || {};
  const rks = Object.keys(rx);
  if (rks.length) inner += '<div class="rx-row">' + rks.map(e => '<span class="rx' + (rx[e].includes(S.me.id) ? " mine" : "") + '">' + esc(e) + " " + rx[e].length + "</span>").join("") + "</div>";
  inner += '<span class="meta">' + (m.edited ? t("edited") + " · " : "") + timeHM(m.created_at) + " " + ticksHTML(m) + "</span>";
  return '<div class="msg ' + (me ? "me" : "peer") + '" data-mid="' + m.id + '"><div class="bub">' + inner + "</div></div>";
}
function attHTML(a, m) {
  const url = mediaUrl(a);
  if (a.kind === "image") return '<div class="att"><img loading="lazy" src="' + url + '" alt="' + esc(a.filename) + '" data-gal="' + a.id + '"></div>';
  if (a.kind === "video") return '<div class="att"><video controls preload="metadata" src="' + url + '"></video></div>';
  if (a.kind === "audio" || (a.meta && a.meta.voice)) return audioHTML(a, url);
  const ic = a.filename.endsWith(".pdf") ? "📕" : (a.filename.endsWith(".zip") ? "🗜️" : "📄");
  return '<div class="att"><div class="file-row" data-dl="' + a.id + '"><span class="fi">' + ic + '</span><span><span class="fn">' + esc(a.filename) + "</span><br><span class=\"fs\">" + fmtSize(a.size) + " · " + t("download") + "</span></span></div></div>";
}
function audioHTML(a, url) {
  const meta = a.meta || {};
  const wf = Array.isArray(meta.waveform) && meta.waveform.length ? meta.waveform : null;
  const bars = wf ? wf.map(v => '<i style="height:' + clampN(Math.round(v * 26) + 3, 3, 28) + 'px"></i>').join("") : Array.from({ length: 24 }, () => '<i style="height:' + (4 + Math.round(Math.random() * 20)) + 'px"></i>').join("");
  return '<div class="att"><div class="audio-p"><button data-play="' + a.id + '" data-url="' + url + '" aria-label="play">▶</button><span class="wave">' + bars + '</span><span class="dur">' + fmtDur(meta.duration) + "</span></div></div>";
}
let curAudio = null, curBtn = null;
function bindAudio(root) {
  $$("[data-play]", root).forEach(b => b.onclick = e => {
    e.stopPropagation();
    if (curBtn === b && curAudio) { curAudio.paused ? curAudio.play() : curAudio.pause(); return; }
    if (curAudio) { curAudio.pause(); if (curBtn) curBtn.textContent = "▶"; }
    curAudio = new Audio(b.dataset.url); curBtn = b; b.textContent = "⏸";
    curAudio.onended = () => { b.textContent = "▶"; curAudio = null; curBtn = null; };
    curAudio.onpause = () => { b.textContent = "▶"; };
    curAudio.onplay = () => { b.textContent = "⏸"; };
    curAudio.play().catch(() => { b.textContent = "▶"; });
  });
  $$("[data-dl]", root).forEach(d => d.onclick = () => {
    const m = S.msgs.find(x => (x.atts || []).some(a => a.id === +d.dataset.dl));
    const a = m ? m.atts.find(x => x.id === +d.dataset.dl) : null;
    if (!a) return;
    const l = document.createElement("a");
    l.href = mediaUrl(a); l.download = a.filename; l.target = "_blank";
    document.body.appendChild(l); l.click(); l.remove();
  });
  $$("[data-gal]", root).forEach(im => im.onclick = () => openGallery(im.dataset.gal));
  $$("[data-goto]", root).forEach(g => g.onclick = e => {
    e.stopPropagation();
    const el = $('#msgs [data-mid="' + g.dataset.goto + '"]');
    if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1700); }
  });
}
function bindMsgs(box) {
  $$(".msg", box).forEach(el => {
    el.oncontextmenu = e => { e.preventDefault(); msgCtx(e.clientX, e.clientY, +el.dataset.mid); };
    let lp = null;
    el.addEventListener("touchstart", () => { lp = setTimeout(() => { const r = el.getBoundingClientRect(); msgCtx(r.left + 40, r.top + 20, +el.dataset.mid); }, 550); }, { passive: true });
    el.addEventListener("touchend", () => clearTimeout(lp));
  });
}
function paintPins() {
  const bar = $("#pins-bar"); if (!bar) return;
  if (!S.pins.length) { bar.style.display = "none"; return; }
  bar.style.display = "flex";
  const p = S.pins[S.pins.length - 1];
  const m = msgById[p.message_id];
  bar.innerHTML = "📌 <b>" + t("pinned_msgs") + " (" + S.pins.length + ")</b><span style='flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>" + esc(m ? (m.text || "📎").slice(0, 60) : "") + "</span>";
  bar.onclick = () => {
    if (!m) return;
    const el = $('#msgs [data-mid="' + m.id + '"]');
    if (el) { el.scrollIntoView({ block: "center", behavior: "smooth" }); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1700); }
  };
}

/* ---------- composer ---------- */
function paintComposer() {
  const c = $("#composer"); if (!c) return;
  c.innerHTML = '<div class="box"><button class="cbtn" id="cp-emoji" aria-label="' + t("emoji") + '">😊</button>' +
    '<textarea id="cp-tx" rows="1" placeholder="' + t("type_msg") + '" aria-label="' + t("type_msg") + '"></textarea>' +
    '<button class="cbtn" id="cp-attach" aria-label="' + t("attach") + '">📎</button></div>' +
    '<button class="send-btn" id="cp-voice" aria-label="' + t("voice") + '">🎤</button>' +
    '<button class="send-btn" id="cp-send" style="display:none" aria-label="' + t("send") + '">➤</button>' +
    '<input type="file" id="cp-file" style="display:none">';
  const tx = $("#cp-tx");
  tx.addEventListener("input", () => {
    tx.style.height = "auto"; tx.style.height = Math.min(tx.scrollHeight, 130) + "px";
    const has = tx.value.trim().length > 0;
    $("#cp-send").style.display = has || S.editId ? "grid" : "none";
    $("#cp-voice").style.display = has || S.editId ? "none" : "grid";
    sendTyping();
  });
  tx.addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSend(); }
  });
  $("#cp-send").onclick = doSend;
  $("#cp-emoji").onclick = e => emojiPicker(e.clientX, e.clientY, em => { tx.value += em; tx.dispatchEvent(new Event("input")); tx.focus(); pushRecent(em); });
  $("#cp-attach").onclick = () => $("#cp-file").click();
  $("#cp-file").onchange = e => { if (e.target.files[0]) uploadAndSend(e.target.files[0]); e.target.value = ""; };
  bindVoiceBtn($("#cp-voice"));
  if (S.editId) { const m = msgById[S.editId]; if (m) { tx.value = m.text || ""; tx.dispatchEvent(new Event("input")); } }
}
function paintReplyBar() {
  const w = $("#rp-wrap"); if (!w) return;
  if (S.editId) { w.innerHTML = '<div class="reply-preview">✏️ ' + t("edit") + '<span style="flex:1"></span><button class="link" id="rp-x">✕</button></div>'; $("#rp-x").onclick = () => { S.editId = null; paintReplyBar(); paintComposer(); }; return; }
  if (!S.replyTo) { w.innerHTML = ""; return; }
  const m = msgById[S.replyTo];
  w.innerHTML = '<div class="reply-preview">↩️ <b>' + t("reply_to") + "</b> " + esc(m ? (m.text || "📎").slice(0, 60) : "") + '<span style="flex:1"></span><button class="link" id="rp-x">✕</button></div>';
  $("#rp-x").onclick = () => { S.replyTo = null; paintReplyBar(); };
}
let lastTypingSent = 0;
function sendTyping() { const n = Date.now(); if (S.curChat && n - lastTypingSent > 3000) { lastTypingSent = n; wsSend({ t: "typing", chat_id: S.curChat }); } }
function paneQ() { const q = $("#pane-q"); return q ? q.value.trim() : ""; }
async function doSend() {
  const tx = $("#cp-tx"); if (!tx) return;
  const text = tx.value.trim();
  if (!text) return;
  if (S.editId) {
    const id = S.editId;
    try {
      const r = await PATCH("/api/messages/" + id, { text });
      if (!r.data.ok) throw r;
      msgById[id] = r.data.msg;
      const i = S.msgs.findIndex(x => x.id === id); if (i > -1) S.msgs[i] = r.data.msg;
      renderMsgs(); S.editId = null; paintReplyBar(); paintComposer();
      const c = chatById(S.curChat); if (c && c.last && c.last.id === id) { c.last = r.data.msg; paintChatItems(paneQ()); }
    } catch (e) { toast(errMsg(e), true); }
    return;
  }
  tx.value = ""; tx.style.height = "auto";
  $("#cp-send").style.display = "none"; $("#cp-voice").style.display = "grid";
  const rp = S.replyTo; S.replyTo = null; paintReplyBar();
  const tmpId = "tmp" + Date.now();
  const tmp = { id: tmpId, chat_id: S.curChat, sender_id: S.me.id, type: "text", text, reply_to: rp, created_at: Date.now(), atts: [], reactions: [], _sending: true };
  S.msgs.push(tmp); msgById[tmpId] = tmp;
  appendMsgEl(tmp, true);
  try {
    const r = await POST("/api/chats/" + S.curChat + "/messages", { text, reply_to: rp });
    if (!r.data.ok) throw r;
    const i = S.msgs.findIndex(x => x.id === tmpId);
    if (i > -1) S.msgs[i] = r.data.msg;
    delete msgById[tmpId]; msgById[r.data.msg.id] = r.data.msg;
    renderMsgs();
    const c = chatById(S.curChat); if (c) { c.last = r.data.msg; paintChatItems(paneQ()); }
  } catch (e) {
    S.msgs = S.msgs.filter(x => x.id !== tmpId); delete msgById[tmpId];
    renderMsgs(); toast(errMsg(e), true);
  }
}
function appendMsgEl(m, stick) {
  const box = $("#msgs"); if (!box) return;
  const d = document.createElement("div");
  d.innerHTML = msgHTML(m);
  const el = d.firstElementChild;
  if (m._sending) el.classList.add("sending");
  box.appendChild(el); bindMsgs(box); bindAudio(box);
  if (stick || nearBottom) box.scrollTop = box.scrollHeight;
}
async function markRead() {
  if (!S.curChat || !S.msgs.length) return;
  const last = S.msgs[S.msgs.length - 1].id;
  if (typeof last !== "number") return;
  try {
    await POST("/api/chats/" + S.curChat + "/read", { last_id: last });
    const c = chatById(S.curChat); if (c) { c.unread = 0; paintChatItems(paneQ()); updateBadge(); }
  } catch (e) {}
}

/* ---------- upload ---------- */
function uploadAndSend(file, meta) {
  const c = $("#composer"); if (!c) return;
  const prog = document.createElement("div");
  prog.className = "up-prog"; prog.innerHTML = "<i></i>";
  c.appendChild(prog);
  const bar = prog.firstElementChild;
  const fd = new FormData();
  fd.append("file", file, file.name);
  if (meta) fd.append("meta", JSON.stringify(meta));
  const x = new XMLHttpRequest();
  x.open("POST", "/api/upload");
  x.setRequestHeader("Authorization", "Bearer " + S.token);
  x.upload.onprogress = e => { if (e.lengthComputable) bar.style.width = Math.round(e.loaded / e.total * 100) + "%"; };
  x.onload = async () => {
    prog.remove();
    let j; try { j = JSON.parse(x.responseText); } catch (e) { toast(t("err_net"), true); return; }
    if (!j.ok) { toast(errMsg({ data: j }), true); return; }
    try {
      const r = await POST("/api/chats/" + S.curChat + "/messages", { text: "", atts: [j.att.id], reply_to: S.replyTo });
      S.replyTo = null; paintReplyBar();
      if (!r.data.ok) throw r;
      S.msgs.push(r.data.msg); msgById[r.data.msg.id] = r.data.msg;
      renderMsgs();
      const cc = chatById(S.curChat); if (cc) { cc.last = r.data.msg; paintChatItems(paneQ()); }
    } catch (e) { toast(errMsg(e), true); }
  };
  x.onerror = () => { prog.remove(); toast(t("err_net"), true); };
  x.send(fd);
}

/* ---------- voice ---------- */
let MR = null, MRChunks = [], MRStart = 0, MRAnalyser = null, MRPeaks = [], MRTimer = null, MRStream = null;
let pendingStop = false;
function bindVoiceBtn(btn) {
  btn.addEventListener("pointerdown", e => {
    e.preventDefault();
    pendingStop = false;
    startRec();
    const up = () => {
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", up);
      if (MR && MR.state !== "inactive") stopRec(false);
      else pendingStop = true;
    };
    document.addEventListener("pointerup", up);
    document.addEventListener("pointercancel", up);
  });
  btn.addEventListener("contextmenu", e => e.preventDefault());
}
async function startRec() {
  if (!navigator.mediaDevices || !window.MediaRecorder) { toast(t("mic_no"), true); return; }
  try { MRStream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
  catch (e) { toast(t("mic_denied"), true); return; }
  MRChunks = []; MRPeaks = []; MRStart = Date.now();
  try {
    const ACx = new (window.AudioContext || window.webkitAudioContext)();
    const src = ACx.createMediaStreamSource(MRStream);
    MRAnalyser = ACx.createAnalyser(); MRAnalyser.fftSize = 256;
    src.connect(MRAnalyser);
    const buf = new Uint8Array(MRAnalyser.frequencyBinCount);
    MRTimer = setInterval(() => {
      MRAnalyser.getByteFrequencyData(buf);
      let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i];
      MRPeaks.push(clampN(s / buf.length / 128, 0.05, 1));
      const el = $("#rec-tm"); if (el) el.textContent = fmtDur((Date.now() - MRStart) / 1000);
      const wv = $("#rec-wave"); if (wv) { const tail = MRPeaks.slice(-32); wv.innerHTML = tail.map(v => '<i style="height:' + Math.round(v * 26 + 3) + 'px"></i>').join(""); }
    }, 120);
    MRStream._ac = ACx;
  } catch (e) {}
  MR = new MediaRecorder(MRStream);
  MR.ondataavailable = e => { if (e.data.size) MRChunks.push(e.data); };
  MR.onstop = onRecStop;
  MR.start();
  const cp = $("#composer");
  cp.dataset.rec = "1";
  cp.innerHTML = '<div class="rec-bar"><span style="color:var(--danger)">🔴</span><span class="tm" id="rec-tm">0:00</span><span class="wave" id="rec-wave"></span><span style="font-size:12px;color:var(--fg2)">' + t("release_send") + '</span><button class="btn sm danger" id="rec-cancel">' + t("cancel") + "</button></div>";
  $("#rec-cancel").onclick = () => stopRec(true);
}
function stopRec(cancel) {
  if (!MR || MR.state === "inactive") { if (cancel) cancelRecUI(); return; }
  MR._cancel = cancel;
  try { MR.stop(); } catch (e) {}
  if (MRTimer) clearInterval(MRTimer);
  if (MRStream) { MRStream.getTracks().forEach(x => x.stop()); if (MRStream._ac) MRStream._ac.close().catch(() => {}); }
}
function cancelRecUI() { MR = null; paintComposer(); }
function onRecStop() {
  const cancel = MR._cancel;
  const dur = (Date.now() - MRStart) / 1000;
  MR = null;
  if (cancel || dur < 0.6 || !MRChunks.length) { paintComposer(); return; }
  const blob = new Blob(MRChunks, { type: MRChunks[0].type || "audio/webm" });
  const url = URL.createObjectURL(blob);
  const wf = [];
  const n = MRPeaks.length || 1;
  for (let i = 0; i < 32; i++) wf.push(MRPeaks[Math.floor(i * n / 32)] || 0.1);
  const cp = $("#composer");
  cp.innerHTML = '<div class="rec-bar"><button class="icon-btn" id="pv-play">▶</button><span class="wave">' + wf.map(v => '<i style="height:' + Math.round(v * 26 + 3) + 'px"></i>').join("") + '</span><span class="tm">' + fmtDur(dur) + '</span><button class="btn sm ghost" id="pv-del">' + t("delete") + '</button><button class="btn sm" id="pv-send">' + t("send") + "</button></div>";
  let au = null;
  $("#pv-play").onclick = e => {
    if (!au) { au = new Audio(url); au.onended = () => e.target.textContent = "▶"; }
    if (au.paused) { au.play(); e.target.textContent = "⏸"; } else { au.pause(); e.target.textContent = "▶"; }
  };
  $("#pv-del").onclick = () => { if (au) au.pause(); URL.revokeObjectURL(url); paintComposer(); };
  $("#pv-send").onclick = () => {
    if (au) au.pause();
    const ext = (blob.type.includes("mp4") || blob.type.includes("m4a")) ? "m4a" : (blob.type.includes("ogg") ? "ogg" : (blob.type.includes("wav") ? "wav" : "webm"));
    const f = new File([blob], "voice." + ext, { type: blob.type || "audio/webm" });
    paintComposer();
    uploadAndSend(f, { voice: true, duration: Math.round(dur), waveform: wf.map(v => +v.toFixed(2)) });
    URL.revokeObjectURL(url);
  };
}

/* ---------- emoji picker ---------- */
const EMOJI_GRID = "😀😁😂🤣😊😍😘😎🤔😐😴🤯😭😡👍👎👏🙏💪🔥❤️💔⭐🎉🎂⚽🚀🌙☀️🌈🍕☕🐱🐶🌹🍀🎧📚💡❓❗💯".split(/([\uD800-\uDBFF][\uDC00-\uDFFF])/).filter(Boolean);
function emojiPicker(x, y, cb) {
  closeCtx();
  const root = $("#ctx-root");
  const d = document.createElement("div");
  d.className = "ctx"; d.style.minWidth = "260px"; d.style.maxWidth = "300px";
  const recent = S.recentEmoji.slice(0, 12);
  d.innerHTML = (recent.length ? '<div style="padding:4px 10px;font-size:11px;color:var(--fg3)">' + t("recent_emoji") + '</div><div class="emoji-bar" style="flex-wrap:wrap">' + recent.map(e => "<button>" + e + "</button>").join("") + "</div>" : "") +
    '<div class="emoji-bar" style="flex-wrap:wrap;max-height:220px;overflow-y:auto">' + EMOJI_GRID.map(e => "<button>" + e + "</button>").join("") + "</div>";
  root.appendChild(d);
  const r = d.getBoundingClientRect();
  d.style.left = clampN(x - 130, 8, innerWidth - r.width - 8) + "px";
  d.style.top = clampN(y - r.height - 10, 8, innerHeight - r.height - 8) + "px";
  d.addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return; closeCtx(); cb(b.textContent); });
  setTimeout(() => document.addEventListener("mousedown", ctxOutside, { once: true }), 10);
}
function pushRecent(em) {
  S.recentEmoji = [em].concat(S.recentEmoji.filter(x => x !== em)).slice(0, 24);
  localStorage.setItem("um_emoji", JSON.stringify(S.recentEmoji));
}

/* ---------- context menus ---------- */
function msgCtx(x, y, mid) {
  const m = msgById[mid]; if (!m || m.deleted_all || typeof mid !== "number") return;
  const mine = m.sender_id === S.me.id;
  const pinned = S.pins.some(p => p.message_id === mid);
  const items = [];
  items.push({ icon: "↩️", label: t("reply"), fn: () => { S.replyTo = mid; S.editId = null; paintReplyBar(); paintComposer(); const tx = $("#cp-tx"); if (tx) tx.focus(); } });
  items.push({ icon: "📋", label: t("copy"), fn: () => { navigator.clipboard.writeText(m.text || "").then(() => toast(t("msg_copied"))); } });
  if (mine && m.type === "text") items.push({ icon: "✏️", label: t("edit"), fn: () => { S.editId = mid; S.replyTo = null; paintReplyBar(); paintComposer(); } });
  items.push({ icon: "↪️", label: t("forward"), fn: () => forwardDlg(mid) });
  items.push({ icon: pinned ? "📌" : "📍", label: pinned ? t("unpin") : t("pin"), fn: () => pinMsg(mid, !pinned) });
  items.push({ sep: true });
  items.push({ icon: mine ? "🗑️" : "🚫", label: t("delete_me"), fn: () => delMsg(mid, "me") });
  if (mine) items.push({ icon: "🔥", label: t("delete_all"), danger: true, fn: async () => { if (await confirmDlg(t("confirm_delete"), t("delete"), true)) delMsg(mid, "all"); } });
  // quick reacts on top
  const root = $("#ctx-root");
  closeCtx();
  const d = document.createElement("div");
  d.className = "ctx";
  d.innerHTML = '<div class="emoji-bar">' + REACTS.slice(0, 6).map(e => "<button>" + e + "</button>").join("") + "</div><div class='sep'></div>" +
    items.map((it, i) => it.sep ? '<div class="sep"></div>' : '<button data-i="' + i + '" class="' + (it.danger ? "danger" : "") + '"><span>' + it.icon + '</span><span>' + esc(it.label) + "</span></button>").join("");
  root.appendChild(d);
  const r = d.getBoundingClientRect();
  d.style.left = clampN(x, 8, innerWidth - r.width - 8) + "px";
  d.style.top = clampN(y, 8, innerHeight - r.height - 8) + "px";
  d.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.i === undefined) { const em = b.textContent; closeCtx(); reactMsg(mid, em); return; }
    const it = items[+b.dataset.i]; closeCtx(); if (it.fn) it.fn();
  });
  setTimeout(() => document.addEventListener("mousedown", ctxOutside, { once: true }), 10);
}
async function reactMsg(mid, em) {
  try { const r = await POST("/api/messages/" + mid + "/react", { emoji: em }); if (r.data.ok && msgById[mid]) { msgById[mid].reactions = r.data.reactions; const i = S.msgs.findIndex(x => x.id === mid); if (i > -1) S.msgs[i].reactions = r.data.reactions; renderMsgs(); } }
  catch (e) { toast(errMsg(e), true); }
}
async function pinMsg(mid, pin) {
  try {
    const r = await POST("/api/messages/" + mid + "/pin", { pin });
    if (r.data.ok) {
      if (pin) S.pins.push({ message_id: mid }); else S.pins = S.pins.filter(p => p.message_id !== mid);
      paintPins(); toast(t(pin ? "pinned_done" : "unpinned_done"));
    }
  } catch (e) { toast(errMsg(e), true); }
}
async function delMsg(mid, scope) {
  try {
    const r = await DEL("/api/messages/" + mid + "?scope=" + scope);
    if (!r.data.ok) throw r;
    if (scope === "all") { msgById[mid] = { id: mid, deleted_all: true, created_at: (msgById[mid] || {}).created_at || Date.now(), sender_id: S.me.id, chat_id: S.curChat }; const i = S.msgs.findIndex(x => x.id === mid); if (i > -1) S.msgs[i] = msgById[mid]; }
    else { delete msgById[mid]; S.msgs = S.msgs.filter(x => x.id !== mid); }
    renderMsgs(); toast(t("msg_deleted"));
  } catch (e) { toast(errMsg(e), true); }
}
function forwardDlg(mid) {
  const avail = S.chats.filter(c => !c.archived);
  if (!avail.length) { toast(t("no_chats_yet"), true); return; }
  const ov = modal("<h3>" + t("fwd_to") + "</h3>" + avail.map(c => '<button class="ci" data-fc="' + c.id + '">' + avatarHTML(c.peer, "sm") + '<span class="tx"><span class="nm">' + esc(c.peer.display_name) + "</span></span></button>").join(""));
  ov.addEventListener("click", async e => {
    const b = e.target.closest("[data-fc]"); if (!b) return;
    closeModal();
    try { const r = await POST("/api/messages/" + mid + "/forward", { chat_id: +b.dataset.fc }); if (r.data.ok) { toast(t("fwd_done")); loadChats(); } else throw r; }
    catch (err) { toast(errMsg(err), true); }
  });
}
function chatCtx(x, y, id) {
  const c = chatById(id); if (!c) return;
  const items = [
    { icon: c.pinned ? "📌" : "📍", label: c.pinned ? t("unpin_chat") : t("pin_chat"), fn: () => chatMeta(id, { pinned: !c.pinned }) },
    { icon: c.muted ? "🔔" : "🔇", label: c.muted ? t("unmute") : t("mute"), fn: () => chatMeta(id, { muted: !c.muted }) },
    { icon: "📦", label: c.archived ? t("unarchive") : t("archive"), fn: () => chatMeta(id, { archived: !c.archived }) },
    { icon: "✓✓", label: c.unread ? t("mark_read") : t("mark_unread"), fn: () => { if (c.unread) markReadChat(id); else markUnreadChat(id); } },
    { icon: "👤", label: t("view_profile"), fn: () => { location.hash = "#/profile/" + c.peer.username; } },
    { sep: true },
    { icon: "🗑️", label: t("delete_chat"), danger: true, fn: async () => { if (await confirmDlg(t("confirm_delete"), t("delete"), true)) chatMeta(id, { deleted: true }); } },
  ];
  ctxMenu(x, y, items);
}
async function chatMeta(id, patch) {
  try {
    const r = await POST("/api/chats/" + id + "/meta", patch);
    if (!r.data.ok) throw r;
    if (patch.deleted) { S.chats = S.chats.filter(c => c.id !== id); if (S.curChat === id) location.hash = "#/chats"; }
    else { const c = chatById(id); if (c) Object.assign(c, { pinned: patch.pinned !== undefined ? patch.pinned : c.pinned, muted: patch.muted !== undefined ? patch.muted : c.muted, archived: patch.archived !== undefined ? patch.archived : c.archived }); }
    paintPane(); if (S.curChat) paintChatItems(paneQ());
  } catch (e) { toast(errMsg(e), true); }
}
async function markReadChat(id) {
  try { await POST("/api/chats/" + id + "/read", {}); const c = chatById(id); if (c) c.unread = 0; paintChatItems(paneQ()); updateBadge(); }
  catch (e) {}
}
async function markUnreadChat(id) {
  try {
    const r = await GET("/api/chats/" + id + "/messages?limit=1");
    const last = r.data.ok && r.data.msgs.length ? r.data.msgs[r.data.msgs.length - 1].id : 1;
    await POST("/api/chats/" + id + "/read", { last_id: Math.max(0, (typeof last === "number" ? last : 1) - 1) });
    const c = chatById(id); if (c) c.unread = 1;
    paintChatItems(paneQ()); updateBadge();
  } catch (e) {}
}

/* ---------- gallery ---------- */
function openGallery(attId) {
  const imgs = [];
  S.msgs.forEach(m => (m.atts || []).forEach(a => { if (a.kind === "image") imgs.push(a); }));
  let i = imgs.findIndex(a => a.id === +attId); if (i < 0) i = 0;
  const root = $("#gal-root");
  const paint = () => {
    const a = imgs[i];
    root.innerHTML = '<div class="gallery"><div class="g-head"><button class="icon-btn" id="g-x">✕</button><span style="flex:1">' + esc(a.filename) + ' (' + (i + 1) + "/" + imgs.length + ')</span><a class="icon-btn" style="text-decoration:none" href="' + mediaUrl(a) + '" download="' + esc(a.filename) + '" target="_blank">⬇</a></div>' +
      '<div class="g-body"><img src="' + mediaUrl(a) + '"></div>' +
      '<div class="g-foot">' + (imgs.length > 1 ? '<button class="btn ghost" id="g-p">→</button><button class="btn ghost" id="g-n">←</button>' : "") + "</div></div>";
    $("#g-x").onclick = closeGallery;
    const p = $("#g-p"), n = $("#g-n");
    if (p) p.onclick = () => { i = (i - 1 + imgs.length) % imgs.length; paint(); };
    if (n) n.onclick = () => { i = (i + 1) % imgs.length; paint(); };
  };
  paint();
  const g = root.querySelector(".gallery");
  g.tabIndex = 0; g.focus();
  g.addEventListener("keydown", e => {
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") { i = (i + 1) % imgs.length; paint(); root.querySelector(".gallery").focus(); }
    if (e.key === "ArrowRight" || e.key === "ArrowUp") { i = (i - 1 + imgs.length) % imgs.length; paint(); root.querySelector(".gallery").focus(); }
  });
}
function closeGallery() { $("#gal-root").innerHTML = ""; }

/* ---------- WS handlers ---------- */
function onWSMsg(m) {
  if (!m) return;
  if (m.t === "react" && m.chat_id) {
    if (msgById[m.id]) { msgById[m.id].reactions = m.reactions; const i = S.msgs.findIndex(x => x.id === m.id); if (i > -1) S.msgs[i].reactions = m.reactions; if (S.curChat === m.chat_id) renderMsgs(); }
    return;
  }
  if (m.t === "pin" && m.chat_id) {
    if (S.curChat === m.chat_id) { S.pins = (m.pins || []).map(id => ({ message_id: id })); paintPins(); }
    return;
  }
  if (m.t === "deleted_all" && m.chat_id) {
    const ph = { id: m.id, deleted_all: true, created_at: Date.now(), sender_id: 0, chat_id: m.chat_id };
    msgById[m.id] = ph;
    const i = S.msgs.findIndex(x => x.id === m.id); if (i > -1) S.msgs[i] = ph;
    if (S.curChat === m.chat_id) renderMsgs();
    return;
  }
  if (m.t === "deleted_me") return;
  if (!m.chat_id || !m.id) return;
  if (msgById[m.id]) { // update (edit / state)
    const old = msgById[m.id];
    msgById[m.id] = Object.assign({}, old, m);
    const i = S.msgs.findIndex(x => x.id === m.id); if (i > -1) S.msgs[i] = msgById[m.id];
    if (S.curChat === m.chat_id) renderMsgs();
    return;
  }
  msgById[m.id] = m;
  const c = chatById(m.chat_id);
  if (c) {
    c.last = m;
    if (S.curChat === m.chat_id) {
      S.msgs.push(m);
      const stick = nearBottom;
      appendMsgEl(m, stick);
      if (!stick) { jumpCount++; $("#jump").classList.add("show"); }
      else markRead();
      paintChatItems(paneQ());
    } else {
      if (m.sender_id !== S.me.id) { c.unread = (c.unread || 0) + 1; updateBadge(); }
      paintChatItems(paneQ());
    }
  } else loadChats();
  if (m.sender_id !== S.me.id && S.curChat !== m.chat_id) {
    beep();
    const cc = chatById(m.chat_id);
    if (cc && !cc.muted) browserNotify(cc.peer.display_name, (m.text || "📎").slice(0, 100), () => { location.hash = "#/chat/" + m.chat_id; });
  } else if (m.sender_id !== S.me.id && S.curChat === m.chat_id && !nearBottom) beep();
}
function onWSNotify(m) {
  S.notifs.unshift({ id: Date.now(), kind: m.kind, payload: m.payload, read: 0, created_at: Date.now() });
  renderSideBadges();
  if (m.kind === "system") { beep(); browserNotify(t("sys_msg"), (m.payload.text || "").slice(0, 120), () => { location.hash = "#/notifications"; }); }
  if (S.route.name === "notifications" && typeof paintNotifs === "function") paintNotifs();
}
function onWSRead(m) {
  if (S.curChat !== m.chat_id) return;
  let changed = false;
  S.msgs.forEach(x => {
    if (typeof x.id === "number" && x.id <= m.up_to && x.sender_id === S.me.id && !x.read) {
      x.read = true; x.delivered = true; changed = true;
      if (msgById[x.id]) { msgById[x.id].read = true; msgById[x.id].delivered = true; }
    }
  });
  if (changed) renderMsgs();
}
