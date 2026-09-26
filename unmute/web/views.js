/* ================= Unmute views ================= */
"use strict";

/* ---------- auth ---------- */
VIEWS.auth = function (name) {
  S.curChat = null;
  const app = $("#app");
  if (name === "login") {
    app.innerHTML = authShell(t("login"), '<div class="fld"><label>' + t("username") + '</label><input class="inp" id="a-u" autocomplete="username" dir="ltr"></div>' +
      '<div class="fld"><label>' + t("password") + '</label><input class="inp" id="a-p" type="password" autocomplete="current-password" dir="ltr"></div>' +
      '<div id="a-err"></div>' +
      '<button class="btn block" id="a-go">' + t("login") + '</button>' +
      '<div class="row between" style="margin-top:10px"><label class="row" style="gap:6px;font-size:13px"><input type="checkbox" id="a-rm" checked> ' + t("remember") + '</label><button class="link" id="a-fg">' + t("forgot") + '</button></div>' +
      '<div class="auth-alt">' + t("no_account") + ' <button class="link" id="a-reg">' + t("register") + '</button></div>');
    $("#a-reg").onclick = () => location.hash = "#/register";
    $("#a-fg").onclick = () => location.hash = "#/forgot";
    const go = async () => {
      const u = $("#a-u").value.trim(), p = $("#a-p").value;
      if (u.length < 3 || !p) { $("#a-err").innerHTML = '<div class="frm-err">' + t("err_bad_creds") + "</div>"; return; }
      $("#a-go").disabled = true;
      try {
        const r = await POST("/api/auth/login", { username: u, password: p, remember: $("#a-rm").checked });
        if (!r.data.ok) throw r;
        saveToken(r.data.token, $("#a-rm").checked);
        S.me = r.data.user; S.settings = r.data.settings; applySettings(); wsConnect(); loadNotifs();
        toast(t("welcome")); location.hash = "#/chats";
      } catch (e) { $("#a-err").innerHTML = '<div class="frm-err">' + errMsg(e) + "</div>"; }
      $("#a-go").disabled = false;
    };
    $("#a-go").onclick = go;
    $("#a-p").onkeydown = e => { if (e.key === "Enter") go(); };
    setTimeout(() => $("#a-u").focus(), 60);
  }
  if (name === "register") {
    let avE = AV_EMOJI[0], avC = AV_COLORS[0];
    app.innerHTML = authShell(t("create_account"),
      '<div class="fld"><label>' + t("choose_avatar") + '</label><div class="av-pick" id="r-avs"></div><div class="clr-pick" id="r-clr"></div></div>' +
      '<div class="fld"><label>' + t("username") + '</label><input class="inp" id="r-u" dir="ltr" placeholder="ali_123"></div>' +
      '<div class="fld"><label>' + t("display_name") + '</label><input class="inp" id="r-d"></div>' +
      '<div class="fld"><label>' + t("password") + '</label><input class="inp" id="r-p" type="password" dir="ltr"></div>' +
      '<div class="fld"><label>' + t("password2") + '</label><input class="inp" id="r-p2" type="password" dir="ltr"></div>' +
      '<div class="fld"><label>' + t("email") + " (" + t("verify_title").split(" ")[0] + "✉️)" + '</label><input class="inp" id="r-e" dir="ltr" placeholder="you@mail.com"></div>' +
      '<div id="r-err"></div>' +
      '<button class="btn block" id="r-go">' + t("create_account") + '</button>' +
      '<div class="auth-alt">' + t("have_account") + ' <button class="link" id="r-lg">' + t("login") + '</button></div>');
    const paintAv = () => {
      $("#r-avs").innerHTML = AV_EMOJI.map(e => '<button style="background:' + avC + '" class="' + (e === avE ? "on" : "") + '" data-e="' + e + '">' + e + "</button>").join("");
      $$("#r-avs button").forEach(b => b.onclick = ev => { ev.preventDefault(); avE = b.dataset.e; paintAv(); });
    };
    $("#r-clr").innerHTML = AV_COLORS.map(c => '<button style="background:' + c + '" class="' + (c === avC ? "on" : "") + '" data-c="' + c + '"></button>').join("");
    $$("#r-clr button").forEach(b => b.onclick = ev => { ev.preventDefault(); avC = b.dataset.c; $$("#r-clr button").forEach(x => x.classList.toggle("on", x === b)); paintAv(); });
    paintAv();
    $("#r-lg").onclick = () => location.hash = "#/login";
    $("#r-go").onclick = async () => {
      const u = $("#r-u").value.trim(), d = $("#r-d").value.trim(), p = $("#r-p").value, p2 = $("#r-p2").value, e = $("#r-e").value.trim();
      const fail = m => { $("#r-err").innerHTML = '<div class="frm-err">' + m + "</div>"; };
      if (!/^[A-Za-z0-9_]{3,20}$/.test(u)) return fail(t("err_username"));
      if (!d) return fail(t("err_display"));
      if (p.length < 6) return fail(t("err_pass_short"));
      if (p !== p2) return fail(t("err_pass_match"));
      if (e && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e)) return fail(t("err_email"));
      $("#r-go").disabled = true;
      try {
        const r = await POST("/api/auth/register", { username: u, display_name: d, password: p, email: e || undefined, avatar: avE + "|" + avC, lang: LANG, remember: true });
        if (!r.data.ok) throw r;
        saveToken(r.data.token, true);
        S.me = r.data.user; S.settings = r.data.settings; applySettings(); wsConnect(); loadNotifs();
        toast(t("welcome")); location.hash = "#/chats";
      } catch (err) { fail(errMsg(err)); }
      $("#r-go").disabled = false;
    };
  }
  if (name === "forgot") {
    app.innerHTML = authShell(t("forgot_title"), '<p class="hint" style="margin-bottom:12px">' + t("forgot_hint") + '</p>' +
      '<div class="fld"><label>' + t("username") + " / " + t("email") + '</label><input class="inp" id="f-u" dir="ltr"></div><div id="f-msg"></div>' +
      '<button class="btn block" id="f-go">' + t("forgot_send") + '</button><div id="f-dev"></div>' +
      '<div class="auth-alt"><button class="link" id="f-bk">' + t("back_login") + '</button></div>');
    $("#f-bk").onclick = () => location.hash = "#/login";
    $("#f-go").onclick = async () => {
      try {
        const r = await POST("/api/auth/forgot", { username: $("#f-u").value.trim() });
        $("#f-msg").innerHTML = '<div class="frm-ok">' + (r.data.sent ? "✉️ OK" : "OK") + "</div>";
        try {
          const d = await GET("/api/dev/inbox");
          if (d.data.ok && d.data.inbox.length) {
            const codes = d.data.inbox.filter(x => x.kind === "reset").slice(-3);
            if (codes.length) $("#f-dev").innerHTML = '<p class="hint">' + t("dev_code_hint") + "</p>" + codes.map(c => '<button class="link" data-rst="' + esc(c.code) + '" dir="ltr">' + esc(c.code) + "</button>").join(" ");
            $$("#f-dev [data-rst]").forEach(b => b.onclick = () => location.hash = "#/reset/" + b.dataset.rst);
          }
        } catch (e) {}
      } catch (e) { $("#f-msg").innerHTML = '<div class="frm-err">' + errMsg(e) + "</div>"; }
    };
  }
  if (name === "reset") {
    const tok = S.route.arg || "";
    app.innerHTML = authShell(t("reset_title"),
      (tok ? "" : '<div class="fld"><label>Token</label><input class="inp" id="rs-t" dir="ltr"></div>') +
      '<div class="fld"><label>' + t("new_pass") + '</label><input class="inp" id="rs-p" type="password" dir="ltr"></div><div id="rs-msg"></div>' +
      '<button class="btn block" id="rs-go">' + t("reset_btn") + '</button>' +
      '<div class="auth-alt"><button class="link" id="rs-bk">' + t("back_login") + '</button></div>');
    $("#rs-bk").onclick = () => location.hash = "#/login";
    $("#rs-go").onclick = async () => {
      const p = $("#rs-p").value;
      if (p.length < 6) { $("#rs-msg").innerHTML = '<div class="frm-err">' + t("err_pass_short") + "</div>"; return; }
      try {
        const r = await POST("/api/auth/reset", { token: tok || $("#rs-t").value.trim(), password: p });
        if (!r.data.ok) throw r;
        $("#rs-msg").innerHTML = '<div class="frm-ok">' + t("pwd_changed") + "</div>";
        setTimeout(() => location.hash = "#/login", 1200);
      } catch (e) { $("#rs-msg").innerHTML = '<div class="frm-err">' + errMsg(e) + "</div>"; }
    };
  }
};
function authShell(title, inner) {
  return '<div class="auth-wrap"><div class="auth-card"><div class="logo"><img src="/logo.svg" alt="Unmute"><h1>' + t("app") + '</h1><div class="sub">' + t("tagline") + " · " + esc(title) + "</div></div>" + inner + "</div></div>";
}

/* ---------- main wrapper ---------- */
function mainView(html) {
  applyMobile("pane");
  const w = $("#pane-wrap"); if (w) w.innerHTML = "";
  $("#main").classList.remove("hidden-m");
  $("#main").innerHTML = '<div class="view">' + html + "</div>";
  return $("#main .view");
}

/* ---------- contacts ---------- */
VIEWS.contacts = async function () {
  const v = mainView("<h2 style='margin-bottom:12px'>👥 " + t("contacts") + "</h2><div class='srch' style='margin:0 0 12px'><span>🔍</span><input id='ct-q' placeholder='" + t("search") + "'></div><div id='ct-list'><div class='spinner'></div></div>");
  let all = [];
  const paint = f => {
    const el = $("#ct-list");
    const list = f ? all.filter(u => (u.display_name + " " + u.username).toLowerCase().includes(f.toLowerCase())) : all;
    if (!list.length) { el.innerHTML = '<div class="empty"><div class="big">👥</div><h3>' + t("no_results") + "</h3></div>"; return; }
    el.innerHTML = list.map(u => '<div class="card row"><span data-pf="' + esc(u.username) + '" style="cursor:pointer;display:contents">' + avatarHTML(u, "sm") + '<span style="flex:1"><b>' + esc(u.display_name) + '</b><br><small style="color:var(--fg2)" dir="ltr">@' + esc(u.username) + "</small></span></span>" +
      '<button class="btn sm ghost" data-msg="' + esc(u.username) + '">💬</button><button class="btn sm ghost" data-rm="' + esc(u.username) + '">🗑️</button></div>').join("");
    $$("[data-pf]", el).forEach(s => s.onclick = () => location.hash = "#/profile/" + s.dataset.pf);
    $$("[data-msg]", el).forEach(b => b.onclick = () => startDM(b.dataset.msg));
    $$("[data-rm]", el).forEach(b => b.onclick = async () => {
      await POST("/api/users/" + b.dataset.rm + "/contact", { add: false });
      toast(t("contact_removed")); VIEWS.contacts();
    });
  };
  $("#ct-q").oninput = debounce(e => paint(e.target.value.trim()), 200);
  try { const r = await GET("/api/contacts"); all = r.data.ok ? r.data.users : []; } catch (e) {}
  paint("");
};
async function startDM(username) {
  try {
    const r = await POST("/api/chats/dm", { username });
    if (!r.data.ok) throw r;
    await loadChats();
    location.hash = "#/chat/" + r.data.chat_id;
  } catch (e) { toast(errMsg(e), true); }
}

/* ---------- search ---------- */
VIEWS.search = function () {
  const v = mainView("<h2 style='margin-bottom:12px'>🔍 " + t("search") + "</h2><div class='srch' style='margin:0 0 12px'><span>🔍</span><input id='s-q' placeholder='" + t("search_hint") + "'></div><div id='s-res'><div class='empty'><div class='big'>🔍</div><p>" + t("search_hint") + "</p></div></div>");
  $("#s-q").oninput = debounce(async e => {
    const q = e.target.value.trim();
    if (q.length < 2) return;
    const el = $("#s-res");
    el.innerHTML = "<div class='spinner'></div>";
    try {
      const r = await GET("/api/search?q=" + encodeURIComponent(q));
      if (!r.data.ok) throw r;
      let h = "";
      if (r.data.users.length) {
        h += "<h3 style='margin:8px 0'>👤 " + t("search_users") + "</h3>";
        h += r.data.users.map(u => '<div class="ni" data-u="' + esc(u.username) + '">' + avatarHTML(u, "sm") + '<span class="tx"><b>' + esc(u.display_name) + '</b><br><small style="color:var(--fg2)" dir="ltr">@' + esc(u.username) + "</small></span></div>").join("");
      }
      if (r.data.messages.length) {
        h += "<h3 style='margin:12px 0 8px'>💬 " + t("search_msgs") + "</h3>";
        h += r.data.messages.map(m => '<div class="ni" data-c="' + m.chat_id + '" data-m="' + m.id + '">' + avatarHTML(m.peer, "sm") + '<span class="tx"><b>' + esc((m.sender || {}).display_name || "") + "</b> · " + esc(m.chat_title || ((m.peer || {}).display_name) || "") + "<br>" + esc(m.text) + '</span><span class="tm">' + chatTime(m.created_at) + "</span></div>").join("");
      }
      el.innerHTML = h || '<div class="empty"><div class="big">🔍</div><h3>' + t("no_results") + "</h3></div>";
      $$("[data-u]", el).forEach(x => x.onclick = () => location.hash = "#/profile/" + x.dataset.u);
      $$("[data-c]", el).forEach(x => x.onclick = () => location.hash = "#/chat/" + x.dataset.c + "/" + x.dataset.m);
    } catch (err) { el.innerHTML = '<div class="empty"><div class="big">⚠️</div><h3>' + errMsg(err) + "</h3></div>"; }
  }, 350);
  setTimeout(() => $("#s-q").focus(), 60);
};

/* ---------- notifications ---------- */
VIEWS.notifications = function () {
  mainView("<div class='row between' style='margin-bottom:12px'><h2>🔔 " + t("notifications") + "</h2><button class='btn sm ghost' id='nt-all'>" + t("mark_all_read") + "</button></div><div id='nt-list'></div>");
  $("#nt-all").onclick = async () => { await POST("/api/notifications/read", {}); S.notifs.forEach(n => n.read = 1); paintNotifs(); renderSideBadges(); };
  paintNotifs();
};
function paintNotifs() {
  const el = $("#nt-list"); if (!el) return;
  if (!S.notifs.length) { el.innerHTML = '<div class="empty"><div class="big">🔔</div><h3>' + t("no_notifs") + "</h3></div>"; return; }
  el.innerHTML = S.notifs.map(n => {
    let tx = "";
    if (n.kind === "message") tx = "<b>💬 @" + esc((n.payload || {}).from || "") + "</b><br>" + esc((n.payload || {}).preview || "");
    else if (n.kind === "group") tx = "<b>👥 " + esc((n.payload || {}).title || t("group")) + "</b><br>" + esc(t("added_to_group") + " — " + ((n.payload || {}).by_name || ("@" + ((n.payload || {}).by || ""))));
    else if (n.kind === "system") tx = "<b>📢 " + t("sys_msg") + "</b><br>" + esc((n.payload || {}).text || "");
    else tx = esc(n.kind);
    return '<div class="ni' + (n.read ? "" : " unread") + '" data-n="' + n.id + '"><span class="tx">' + tx + '</span><span class="tm">' + chatTime(n.created_at) + "</span></div>";
  }).join("");
  $$(".ni", el).forEach(x => x.onclick = async () => {
    const n = S.notifs.find(v => v.id === +x.dataset.n);
    if (n && (n.payload || {}).chat_id) location.hash = "#/chat/" + n.payload.chat_id;
  });
}

/* ---------- profile ---------- */
VIEWS.profile = async function () {
  const uname = S.route.arg;
  const v = mainView("<div class='spinner'></div>");
  let r;
  try { r = await GET("/api/users/" + encodeURIComponent(uname)); if (!r.data.ok) throw r; }
  catch (e) { v.innerHTML = '<div class="empty"><div class="big">👤</div><h3>' + t("user_not_found") + "</h3></div>"; return; }
  const u = r.data.user;
  const mine = u.id === S.me.id;
  const cover = u.cover || u.avatar.color;
  v.innerHTML = '<div class="cover" style="background:linear-gradient(135deg,' + esc(cover) + ',var(--bg3))"></div>' +
    '<div class="card"><div class="pf-head"><div class="av" style="background:' + esc((u.avatar || {}).color || "#6d5ef1") + ';width:88px;height:88px;font-size:44px;border:4px solid var(--bg2)">' + esc((u.avatar || {}).emoji || "🧑") + ((u.avatar || {}).img ? '<img src="' + esc(u.avatar.img) + "?token=" + encodeURIComponent(S.token) + '" alt="" onerror="this.remove()">' : "") + "</div>" +
    '<div><h2>' + esc(u.display_name) + "</h2><div dir='ltr' style='color:var(--fg2)'>@" + esc(u.username) + "</div>" +
    '<div style="font-size:12.5px;color:' + (u.online ? "var(--ok)" : "var(--fg3)") + '">' + (u.online ? "🟢 " + t("online") : "⚪ " + t("last_seen") + " " + lastSeenTx(u.last_seen, false)) + "</div></div></div>" +
    (u.bio ? "<p style='margin:8px 0'>" + esc(u.bio) + "</p>" : "") +
    '<div class="hint">📅 ' + t("member_since") + " " + new Date(u.created_at).toLocaleDateString(LANG === "fa" ? "fa-IR" : "en-US") + (u.role === "admin" ? ' · 🛡️ ' + t("role_admin") : "") + "</div>" +
    '<div class="pf-actions" id="pf-acts"></div></div>' +
    (mine ? '<div class="card"><h3>✉️ ' + t("email") + '</h3><div class="row between"><span dir="ltr">' + esc(S.email || "—") + '</span><span class="pill ' + (S.verified ? "ok" : "warn") + '">' + (S.verified ? t("verified") : t("not_verified")) + "</span></div>" + (S.verified ? "" : '<div class="row" style="margin-top:10px"><input class="inp" id="pf-code" placeholder="CODE" dir="ltr" style="max-width:140px"><button class="btn sm" id="pf-verify">' + t("verify_btn") + '</button></div><div id="pf-dev"></div>') + "</div>" : "");
  const acts = $("#pf-acts");
  if (mine) {
    acts.innerHTML = '<button class="btn sm" id="pf-edit">✏️ ' + t("edit_profile") + '</button><button class="btn sm ghost" id="pf-link">🔗 ' + t("profile_link") + "</button>";
    $("#pf-edit").onclick = () => editProfileDlg();
    $("#pf-link").onclick = () => { navigator.clipboard.writeText(location.origin + "/#/profile/" + u.username).then(() => toast(t("copied_link"))); };
    const vb = $("#pf-verify");
    if (vb) {
      vb.onclick = async () => {
        try { const vr = await POST("/api/me/verify", { code: $("#pf-code").value.trim() }); if (!vr.data.ok) throw vr; S.verified = true; toast(t("saved")); VIEWS.profile(); }
        catch (e) { toast(errMsg(e), true); }
      };
      try {
        const d = await GET("/api/dev/inbox");
        if (d.data.ok) {
          const codes = d.data.inbox.filter(x => x.kind === "verify").slice(-3);
          if (codes.length) $("#pf-dev").innerHTML = '<p class="hint">' + t("dev_code_hint") + " " + codes.map(c => "<b dir='ltr'>" + esc(c.code) + "</b>").join(" · ") + "</p>";
        }
      } catch (e) {}
    }
  } else {
    acts.innerHTML = '<button class="btn sm" id="pf-msg">💬 ' + t("send_message") + "</button>" +
      '<button class="btn sm ghost" id="pf-ct">' + (u.is_contact ? "➖ " + t("remove_contact") : "➕ " + t("add_contact")) + "</button>" +
      '<button class="btn sm ghost" id="pf-bl">' + (u.blocked ? t("unblock") : t("block")) + "</button>" +
      '<button class="btn sm ghost" id="pf-rp">🚩 ' + t("report") + "</button>";
    $("#pf-msg").onclick = () => startDM(u.username);
    $("#pf-ct").onclick = async () => {
      await POST("/api/users/" + u.username + "/contact", { add: !u.is_contact });
      toast(t(u.is_contact ? "contact_removed" : "contact_added")); VIEWS.profile();
    };
    $("#pf-bl").onclick = async () => {
      if (!u.blocked && !(await confirmDlg(t("confirm_delete"), t("block"), true))) return;
      await POST("/api/users/" + u.username + "/block", { block: !u.blocked });
      toast(t(u.blocked ? "unblocked_u" : "blocked_u")); VIEWS.profile();
    };
    $("#pf-rp").onclick = () => reportDlg(u.username);
  }
};
function compressAvatar(file) {
  // client-side optimize: cover-crop to 256x256 jpeg (~20-60KB)
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => {
      try {
        const S2 = 256, cv = document.createElement("canvas");
        cv.width = S2; cv.height = S2;
        const cx = cv.getContext("2d");
        const sc = Math.max(S2 / img.width, S2 / img.height);
        const w = img.width * sc, h = img.height * sc;
        cx.drawImage(img, (S2 - w) / 2, (S2 - h) / 2, w, h);
        URL.revokeObjectURL(img.src);
        cv.toBlob(b => b ? res(b) : rej(new Error("enc")), "image/jpeg", 0.82);
      } catch (e) { rej(e); }
    };
    img.onerror = rej;
    img.src = URL.createObjectURL(file);
  });
}
function editProfileDlg() {
  let avE = (S.me.avatar || {}).emoji || AV_EMOJI[0], avC = (S.me.avatar || {}).color || AV_COLORS[0];
  let newAvId = undefined; // set when a new photo is uploaded in this dialog
  const curImg = (S.me.avatar || {}).img;
  const ov = modal("<h3>✏️ " + t("edit_profile") + "</h3>" +
    '<div class="row" style="margin-bottom:12px"><span id="e-ph-prev">' + avatarHTML(S.me) + '</span><span style="flex:1"></span>' +
    '<button class="btn sm ghost" id="e-ph-up">📷 ' + t("photo_from_gallery") + "</button>" +
    (curImg ? '<button class="btn sm ghost" id="e-ph-del">' + t("remove_photo") + "</button>" : "") + "</div>" +
    '<input type="file" id="e-ph-file" accept="image/*" style="display:none">' +
    '<div class="av-pick" id="e-avs"></div><div class="clr-pick" id="e-clr"></div>' +
    '<div class="fld"><label>' + t("display_name") + '</label><input class="inp" id="e-d" value="' + esc(S.me.display_name) + '"></div>' +
    '<div class="fld"><label>' + t("bio") + '</label><textarea class="inp" id="e-b">' + esc(S.me.bio || "") + "</textarea></div>" +
    '<div class="macts"><button class="btn ghost" id="e-x">' + t("cancel") + '</button><button class="btn" id="e-ok">' + t("save") + "</button></div>");
  const paint = () => {
    $("#e-avs", ov).innerHTML = AV_EMOJI.map(e => '<button style="background:' + avC + '" class="' + (e === avE ? "on" : "") + '" data-e="' + e + '">' + e + "</button>").join("");
    $$("#e-avs button", ov).forEach(b => b.onclick = ev => { ev.preventDefault(); avE = b.dataset.e; paint(); });
  };
  $("#e-clr", ov).innerHTML = AV_COLORS.map(c => '<button style="background:' + c + '" class="' + (c === avC ? "on" : "") + '" data-c="' + c + '"></button>').join("");
  $$("#e-clr button", ov).forEach(b => b.onclick = ev => { ev.preventDefault(); avC = b.dataset.c; $$("#e-clr button", ov).forEach(x => x.classList.toggle("on", x === b)); paint(); });
  paint();
  $("#e-x", ov).onclick = closeModal;
  $("#e-ph-up", ov).onclick = () => $("#e-ph-file", ov).click();
  const delB = $("#e-ph-del", ov);
  if (delB) delB.onclick = () => { newAvId = 0; $("#e-ph-prev", ov).innerHTML = avatarHTML({ avatar: { emoji: avE, color: avC } }); delB.remove(); };
  $("#e-ph-file", ov).onchange = async e => {
    const f = e.target.files[0]; e.target.value = "";
    if (!f) return;
    if (!f.type.startsWith("image/")) { toast(t("err_file_type"), true); return; }
    const btn = $("#e-ph-up", ov); btn.disabled = true;
    try {
      const blob = await compressAvatar(f);
      const fd = new FormData();
      fd.append("file", blob, "avatar.jpg");
      fd.append("meta", JSON.stringify({ avatar: true }));
      const r = await POST("/api/upload", fd);
      if (!r.data.ok) throw r;
      newAvId = r.data.att.id;
      $("#e-ph-prev", ov).innerHTML = '<div class="av" style="background:' + esc(avC) + '"><img src="' + r.data.att.url + "?token=" + encodeURIComponent(S.token) + '" style="position:absolute;inset:0;width:100%;height:100%;border-radius:50%;object-fit:cover"></div>';
      toast(t("photo_updated"));
    } catch (err) { toast(errMsg(err), true); }
    btn.disabled = false;
  };
  $("#e-ok", ov).onclick = async () => {
    try {
      const patch = { display_name: $("#e-d", ov).value.trim(), bio: $("#e-b", ov).value.trim(), avatar: avE + "|" + avC };
      if (newAvId !== undefined) patch.avatar_img = newAvId;
      const r = await PATCH("/api/me", patch);
      if (!r.data.ok) throw r;
      S.me = r.data.user; closeModal(); renderSideBadges(); VIEWS.profile(); toast(t("saved"));
    } catch (e) { toast(errMsg(e), true); }
  };
}
function reportDlg(username) {
  const Rs = ["spam", "harassment", "fake", "inappropriate", "other"];
  const ov = modal("<h3>🚩 " + t("report") + " @" + esc(username) + "</h3>" +
    '<div class="fld"><label>' + t("report_reason") + '</label><select class="inp" id="rp-r">' + Rs.map(r => '<option value="' + r + '">' + t("r_" + r) + "</option>").join("") + "</select></div>" +
    '<div class="fld"><label>' + t("report_details") + '</label><textarea class="inp" id="rp-d"></textarea></div>' +
    '<div class="macts"><button class="btn ghost" id="rp-x">' + t("cancel") + '</button><button class="btn danger" id="rp-ok">' + t("report") + "</button></div>");
  $("#rp-x", ov).onclick = closeModal;
  $("#rp-ok", ov).onclick = async () => {
    try { await POST("/api/users/" + username + "/report", { reason: $("#rp-r", ov).value, details: $("#rp-d", ov).value.trim() }); closeModal(); toast(t("reported")); }
    catch (e) { toast(errMsg(e), true); }
  };
}

/* ---------- settings ---------- */
VIEWS.settings = async function () {
  const v = mainView("<h2 style='margin-bottom:12px'>⚙️ " + t("settings") + "</h2><div class='spinner'></div>");
  let ss = [];
  try { const r = await GET("/api/sessions"); if (r.data.ok) ss = r.data.sessions; } catch (e) {}
  const s = S.settings;
  const privRow = (k, label) => '<div class="set-row"><span class="t">' + label + '</span><select class="inp" style="width:auto" data-priv="' + k + '">' + ["everyone", "contacts", "nobody"].map(o => '<option value="' + o + '"' + (s[k] === o ? " selected" : "") + ">" + t(o === "contacts" ? "contacts_only" : o) + "</option>").join("") + "</select></div>";
  const swRow = (k, label) => '<div class="set-row"><span class="t">' + label + '</span><label class="sw"><input type="checkbox" data-sw="' + k + '"' + (s[k] ? " checked" : "") + "><i></i></label></div>";
  v.innerHTML = "<h2 style='margin-bottom:12px'>⚙️ " + t("settings") + "</h2>" +
    '<div class="card"><h3>👤 ' + t("account") + "</h3>" +
    '<div class="set-row"><span class="t">@' + esc(S.me.username) + '</span><button class="btn sm ghost" id="st-un">' + t("change_username") + "</button></div>" +
    '<div class="set-row"><span class="t">' + esc(S.email || t("email")) + '</span><button class="btn sm ghost" id="st-em">' + t("change_email") + "</button></div>" +
    '<div class="set-row"><span class="t">••••••</span><button class="btn sm ghost" id="st-pw">' + t("change_password") + "</button></div>" +
    '<div class="set-row"><span class="t">' + t("logout") + '</span><button class="btn sm ghost" id="st-lo">' + t("logout") + "</button></div>" +
    '<div class="set-row"><span class="t" style="color:var(--danger)">' + t("delete_account") + '</span><button class="btn sm danger" id="st-del">' + t("delete") + "</button></div></div>" +
    '<div class="card"><h3>🎨 ' + t("appearance") + "</h3>" +
    '<div class="set-row"><span class="t">' + t("theme") + '</span><div class="seg" id="st-th">' + ["dark", "light", "system"].map(o => '<button data-v="' + o + '" class="' + (s.theme === o ? "on" : "") + '">' + t(o) + "</button>").join("") + "</div></div>" +
    '<div class="set-row"><span class="t">' + t("accent") + '</span><div class="accent-row">' + ACCENTS.map(a => '<span class="accent-dot' + (s.accent === a ? " on" : "") + '" data-a="' + a + '" style="background:var(--accent)" data-ac="' + a + '"></span>').join("") + "</div></div>" +
    '<div class="set-row"><span class="t">' + t("font_size") + '</span><div class="seg" id="st-fs">' + ["sm", "md", "lg"].map(o => '<button data-v="' + o + '" class="' + (s.font_size === o ? "on" : "") + '">' + t(o === "sm" ? "small" : (o === "md" ? "medium" : "large")) + "</button>").join("") + "</div></div></div>" +
    '<div class="card"><h3>🔔 ' + t("notifications") + "</h3>" + swRow("notif_msg", t("notif_msg")) + swRow("notif_sound", t("notif_sound")) + swRow("notif_browser", t("notif_browser")) + "</div>" +
    '<div class="card"><h3>🔒 ' + t("privacy") + "</h3>" + privRow("priv_msg", t("priv_msg")) + privRow("priv_profile", t("priv_profile")) + privRow("priv_photo", t("priv_photo")) + privRow("priv_lastseen", t("priv_lastseen")) + privRow("priv_online", t("priv_online")) + "</div>" +
    '<div class="card"><h3>🌍 ' + t("language") + '</h3><div class="seg" id="st-lg"><button data-v="fa" class="' + (LANG === "fa" ? "on" : "") + '">فارسی</button><button data-v="en" class="' + (LANG === "en" ? "on" : "") + '">English</button></div></div>' +
    '<div class="card"><h3>📱 ' + t("sessions") + '</h3><div id="st-ss">' + ss.map(x => '<div class="set-row"><span><span class="t">' + esc((x.ua || t("unknown_device")).slice(0, 60)) + "</span><br><span class='d' dir='ltr'>" + esc(x.ip || "") + " · " + lastSeenTx(x.last_active, false) + (x.current ? ' · <b style="color:var(--accent)">' + t("current") + "</b>" : "") + '</span></span>' + (x.current ? "" : '<button class="btn sm ghost" data-rv="' + esc(x.token) + '">' + t("revoke") + "</button>") + "</div>").join("") + '</div><button class="btn sm ghost" id="st-rvall" style="margin-top:8px">' + t("revoke_all") + "</button></div>";
  // paint accent dots real colors
  const accColors = { violet: "#6d5ef1", blue: "#0ea5e9", green: "#10b981", orange: "#f59e0b", red: "#ef4444", pink: "#ec4899" };
  $$("[data-ac]", v).forEach(d => d.style.background = accColors[d.dataset.ac]);
  const save = async patch => {
    try { const r = await PATCH("/api/settings", patch); if (!r.data.ok) throw r; S.settings = r.data.settings; applySettings(); }
    catch (e) { toast(errMsg(e), true); }
  };
  $$("#st-th button", v).forEach(b => b.onclick = () => { $$("#st-th button", v).forEach(x => x.classList.toggle("on", x === b)); save({ theme: b.dataset.v }); });
  $$("#st-fs button", v).forEach(b => b.onclick = () => { $$("#st-fs button", v).forEach(x => x.classList.toggle("on", x === b)); save({ font_size: b.dataset.v }); });
  $$("[data-ac]", v).forEach(d => d.onclick = () => { $$("[data-ac]", v).forEach(x => x.classList.toggle("on", x === d)); save({ accent: d.dataset.ac }); });
  $$("[data-sw]", v).forEach(sw => sw.onchange = async () => {
    const k = sw.dataset.sw;
    if (k === "notif_browser" && sw.checked) await ensureBrowserPerm();
    save({ [k]: sw.checked });
  });
  $$("[data-priv]", v).forEach(sel => sel.onchange = () => save({ [sel.dataset.priv]: sel.value }));
  $$("#st-lg button", v).forEach(b => b.onclick = async () => { setLang(b.dataset.v); await save({ lang: b.dataset.v }); toast(t("lang_changed")); $("#app").innerHTML = ""; S.chats = []; S.curChat = null; router(); });
  $("#st-un", v).onclick = () => promptDlg(t("change_username"), t("username"), S.me.username, async val => {
    if (!/^[A-Za-z0-9_]{3,20}$/.test(val)) { toast(t("err_username"), true); return false; }
    try { const r = await POST("/api/me/username", { username: val }); if (!r.data.ok) throw r; S.me.username = val; VIEWS.settings(); toast(t("saved")); return true; }
    catch (e) { toast(errMsg(e), true); return false; }
  });
  $("#st-em", v).onclick = () => promptDlg(t("change_email"), t("email"), S.email || "", async val => {
    try { const r = await POST("/api/me/email", { email: val }); if (!r.data.ok) throw r; S.email = val; S.verified = false; VIEWS.settings(); toast(t("saved")); return true; }
    catch (e) { toast(errMsg(e), true); return false; }
  });
  $("#st-pw").onclick = () => {
    const ov = modal("<h3>🔑 " + t("change_password") + "</h3>" +
      '<div class="fld"><label>' + t("old_pass") + '</label><input class="inp" id="pw-o" type="password"></div>' +
      '<div class="fld"><label>' + t("new_pass") + '</label><input class="inp" id="pw-n" type="password"></div>' +
      '<div class="macts"><button class="btn ghost" id="pw-x">' + t("cancel") + '</button><button class="btn" id="pw-ok">' + t("save") + "</button></div>");
    $("#pw-x", ov).onclick = closeModal;
    $("#pw-ok", ov).onclick = async () => {
      try {
        const r = await POST("/api/me/password", { old: $("#pw-o", ov).value, new: $("#pw-n", ov).value });
        if (!r.data.ok) throw r; closeModal(); toast(t("pwd_changed"));
      } catch (e) { toast(errMsg(e), true); }
    };
  };
  $("#st-lo").onclick = async () => {
    if (!(await confirmDlg(t("confirm_logout"), t("logout")))) return;
    try { await POST("/api/auth/logout", {}); } catch (e) {}
    onUnauthorized();
  };
  $("#st-del").onclick = async () => {
    if (!(await confirmDlg(t("confirm_del_account"), t("delete"), true))) return;
    try { await DEL("/api/me", {}); } catch (e) {}
    onUnauthorized();
  };
  $$("[data-rv]", v).forEach(b => b.onclick = async () => { await DEL("/api/sessions", { prefix: b.dataset.rv }); VIEWS.settings(); });
  $("#st-rvall", v).onclick = async () => { await DEL("/api/sessions", { all: true }); VIEWS.settings(); toast(t("saved")); };
};
function promptDlg(title, label, val, onOk) {
  const ov = modal("<h3>" + esc(title) + "</h3>" +
    '<div class="fld"><label>' + esc(label) + '</label><input class="inp" id="pd-v" value="' + esc(val) + '" dir="auto"></div>' +
    '<div class="macts"><button class="btn ghost" id="pd-x">' + t("cancel") + '</button><button class="btn" id="pd-ok">' + t("save") + "</button></div>");
  $("#pd-x", ov).onclick = closeModal;
  $("#pd-ok", ov).onclick = async () => { if (await onOk($("#pd-v", ov).value.trim())) closeModal(); };
}

/* ---------- admin ---------- */
VIEWS.admin = async function () {
  if (!S.me || S.me.role !== "admin") { location.hash = "#/chats"; return; }
  const tab = S.route.arg || "stats";
  const v = mainView("<h2 style='margin-bottom:12px'>🛡️ " + t("admin") + "</h2>" +
    '<div class="seg" id="ad-tabs" style="margin-bottom:14px">' + ["stats", "users", "reports", "broadcast"].map(x => '<button data-t="' + x + '" class="' + (tab === x ? "on" : "") + '">' + t(x === "broadcast" ? "broadcast" : x) + "</button>").join("") + "</div><div id='ad-body'><div class='spinner'></div></div>");
  $$("#ad-tabs button", v).forEach(b => b.onclick = () => location.hash = "#/admin/" + b.dataset.t);
  const body = $("#ad-body");
  if (tab === "stats") {
    try {
      const r = await GET("/api/admin/stats");
      const st = r.data.stats;
      const max = Math.max(1, ...st.series.map(d => Math.max(d.regs, d.msgs)));
      body.innerHTML = '<div class="stat-grid"><div class="stat"><div class="n">' + st.users + '</div><div class="l">' + t("total_users") + '</div></div><div class="stat"><div class="n">' + st.messages + '</div><div class="l">' + t("total_msgs") + '</div></div><div class="stat"><div class="n">' + st.online + '</div><div class="l">' + t("online_now") + '</div></div><div class="stat"><div class="n">' + st.regs_day + '</div><div class="l">' + t("regs_day") + '</div></div></div>' +
        '<div class="card"><h3>📊 ' + t("stats_14d") + '</h3><div class="chart">' + st.series.map(d => '<div class="b"><i class="m" style="height:' + Math.round(d.msgs / max * 70) + 'px"></i><i class="r" style="height:' + Math.round(d.regs / max * 70) + 'px"></i></div>').join("") + "</div><p class='hint'>🟣 " + t("regs_day") + " · 🟢 " + t("total_msgs") + "</p></div>";
    } catch (e) { body.innerHTML = '<div class="frm-err">' + errMsg(e) + "</div>"; }
  }
  if (tab === "users") {
    body.innerHTML = '<div class="srch" style="margin:0 0 12px"><span>🔍</span><input id="au-q" placeholder="' + t("adm_users_hint") + '"></div><div id="au-list"></div>';
    const paint = async q => {
      const el = $("#au-list"); el.innerHTML = "<div class='spinner'></div>";
      try {
        const r = await GET("/api/admin/users?q=" + encodeURIComponent(q || ""));
        el.innerHTML = '<div class="card" style="overflow-x:auto"><table class="tbl"><tr><th>' + t("username") + "</th><th>" + t("status") + "</th><th>" + t("actions") + "</th></tr>" +
          r.data.users.map(u => "<tr><td><b dir='ltr'>@" + esc(u.username) + "</b><br><small>" + esc(u.display_name) + "</small></td>" +
            '<td><span class="pill ' + (u.status === "active" ? "ok" : "bad") + '">' + t("status_" + u.status) + "</span>" + (u.role === "admin" ? ' <span class="pill">🛡️</span>' : "") + "</td>" +
            '<td style="white-space:nowrap">' +
            (u.status === "banned" ? '<button class="btn sm ghost" data-act="unban" data-id="' + u.id + '">' + t("unban") + "</button> " : '<button class="btn sm ghost" data-act="ban" data-id="' + u.id + '">' + t("ban") + "</button> ") +
            '<button class="btn sm ghost" data-act="suspend" data-id="' + u.id + '">' + t("suspend") + "</button> " +
            '<button class="btn sm danger" data-act="delete" data-id="' + u.id + '">' + t("delete") + "</button></td></tr>").join("") + "</table></div>";
        $$("[data-act]", el).forEach(b => b.onclick = async () => {
          if ((b.dataset.act === "delete" || b.dataset.act === "ban") && !(await confirmDlg(t("confirm_delete"), t("yes"), true))) return;
          try { const rr = await POST("/api/admin/users/" + b.dataset.id + "/action", { act: b.dataset.act }); if (!rr.data.ok) throw rr; toast(t("adm_act_done")); paint($("#au-q").value.trim()); }
          catch (e) { toast(errMsg(e), true); }
        });
      } catch (e) { el.innerHTML = '<div class="frm-err">' + errMsg(e) + "</div>"; }
    };
    $("#au-q").oninput = debounce(e => paint(e.target.value.trim()), 350);
    paint("");
  }
  if (tab === "reports") {
    try {
      const r = await GET("/api/admin/reports");
      const rs = r.data.reports;
      body.innerHTML = rs.length ? '<div class="card" style="overflow-x:auto"><table class="tbl"><tr><th>' + t("reporter") + "</th><th>" + t("target") + "</th><th>" + t("report_reason") + "</th><th>" + t("status") + "</th><th></th></tr>" +
        rs.map(x => "<tr><td dir='ltr'>@" + esc(x.reporter) + "</td><td dir='ltr'>@" + esc(x.target || "?") + "</td><td>" + t("r_" + x.reason) + (x.details ? "<br><small>" + esc(x.details) + "</small>" : "") + "</td><td>" + (x.status === "open" ? '<span class="pill warn">' + t("open_reports") + "</span>" : '<span class="pill ok">' + t("closed_reports") + "</span>") + "</td><td>" + (x.status === "open" ? '<button class="btn sm ghost" data-rs="' + x.id + '">' + t("resolve") + "</button>" : "") + "</td></tr>").join("") + "</table></div>"
        : '<div class="empty"><div class="big">🎉</div><h3>' + t("adm_no_reports") + "</h3></div>";
      $$("[data-rs]", body).forEach(b => b.onclick = async () => { await POST("/api/admin/reports/" + b.dataset.rs + "/resolve", {}); VIEWS.admin(); });
    } catch (e) { body.innerHTML = '<div class="frm-err">' + errMsg(e) + "</div>"; }
  }
  if (tab === "broadcast") {
    body.innerHTML = '<div class="card"><h3>📢 ' + t("broadcast") + "</h3><p class='hint' style='margin-bottom:10px'>" + t("bc_hint") + '</p><textarea class="inp" id="bc-t" placeholder="' + t("bc_ph") + '"></textarea><button class="btn" id="bc-go" style="margin-top:10px">' + t("send") + "</button></div>";
    $("#bc-go").onclick = async () => {
      const tx = $("#bc-t").value.trim(); if (!tx) return;
      try { const r = await POST("/api/admin/broadcast", { text: tx }); if (!r.data.ok) throw r; toast(t("bc_sent") + " (" + r.data.count + ")"); $("#bc-t").value = ""; }
      catch (e) { toast(errMsg(e), true); }
    };
  }
};
