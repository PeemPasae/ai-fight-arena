"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STATUS = {
  done: "จบแล้ว", scheduled: "ในคิว", running: "กำลังแข่ง", invalid: "ไม่นับผล", error: "ผิดพลาด", cancelled: "ยกเลิก",
  queued_test: "รอเทสโหลด", testing: "กำลังเทส", ready: "พร้อม", failed: "โหลดไม่ผ่าน", banned: "แบน (ผิดกติกา)",
};
let S = { chars: [], players: [], matches: [], standings: [], now: {}, rules: {} };
let P = {}, C = {};
let mFilter = "all";
function setHTML(el, html) {
  if (el.__html === html) return false;
  el.__html = html; el.innerHTML = html; return true;
}

// ---------------------------------------------------------------- tabs
function showTab(name) {
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + name));
  const v = $("#video");
  if (name === "live") { if (!v.src.endsWith("/stream.mjpg")) v.src = "/stream.mjpg"; }
  else v.removeAttribute("src");                 // stop the video stream when not watching
  try { localStorage.setItem("tab", name); } catch (e) {}
  if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
}
$$("#tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));

// ---------------------------------------------------------------- state polling
async function refresh() {
  try {
    S = await (await fetch("/api/state")).json();
    P = Object.fromEntries(S.players.map((p) => [p.id, p]));
    C = Object.fromEntries(S.chars.map((c) => [c.id, c]));
    render();
  } catch (e) { /* server restarting */ }
}
const pn = (id) => (P[id] ? P[id].name : "(ลบแล้ว)");
const pc = (id) => (P[id] ? P[id].char_name : "");
const who = (id, cls) => `<span class="${cls}">${esc(pn(id))}</span> <span class="muted small">${esc(pc(id))}</span>`;

function render() {
  const pill = $("#nowPill");
  pill.textContent = S.now.match ? "● กำลังแข่ง" : S.now.title ? "● กำลังเทสตัวละคร" : "ว่าง";
  pill.classList.toggle("run", !!(S.now.match || S.now.title));
  renderSide(); renderStandings(); renderMatches(); renderPlayers(); renderRoster(); renderPick(); renderRules(); renderAdmin(); renderData();
}

function matchLine(m) {
  const w = m.wins ? ` <b>${m.wins[0]}-${m.wins[1]}</b>` : "";
  return `${who(m.p1, "p1c")}<span class="vs">vs</span>${who(m.p2, "p2c")}${w}`;
}
function renderSide() {
  const up = S.matches.filter((m) => m.status === "scheduled").slice(0, 6);
  setHTML($("#upNext"), up.length ? up.map((m) => `<li>${matchLine(m)}</li>`).join("") : `<li class="muted">ไม่มีคิว</li>`);
  const rec = S.matches.filter((m) => m.status === "done").sort((a, b) => (b.ended || 0) - (a.ended || 0)).slice(0, 6);
  setHTML($("#recent"), rec.length ? rec.map((m) => `<li>${matchLine(m)}</li>`).join("") : `<li class="muted">ยังไม่มีผล</li>`);
}

function renderStandings() {
  const rows = S.standings;
  setHTML($("#standings"), `<tr><th>#</th><th>ผู้เล่น</th><th>ตัวละคร</th><th class="num">แข่ง</th><th class="num">ชนะ</th>
    <th class="num">เสมอ</th><th class="num">แพ้</th><th class="num">ยก +/-</th>
    <th class="num" title="ผลรวมทุกยกของ (%เลือดที่เหลือของเรา − ของคู่แข่ง)">เลือด% +/-</th><th class="num">Elo</th>
    <th class="num">แต้ม</th><th>ฟอร์ม</th></tr>` +
    (rows.length ? rows.map((r) => `<tr><td class="rank">${r.rank}</td>
      <td><b>${esc(r.name)}</b>${r.bot ? '<span class="badge bot">BOT</span>' : ""}</td>
      <td>${esc(r.char_name)}</td><td class="num">${r.played}</td><td class="num">${r.w}</td><td class="num">${r.d}</td><td class="num">${r.l}</td>
      <td class="num">${r.rw - r.rl >= 0 ? "+" : ""}${r.rw - r.rl}</td><td class="num">${r.hp >= 0 ? "+" : ""}${r.hp}</td>
      <td class="num">${r.elo}</td><td class="num"><b>${r.pts}</b></td>
      <td class="form">${r.form.map((f) => `<span class="${f}">${f}</span>`).join("")}</td></tr>`).join("")
      : `<tr><td colspan="12" class="muted">ยังไม่มีผู้เล่น</td></tr>`));
}

function pctRounds(m) {
  return (m.rounds || []).map((r) => `${Math.round(100 * r.hp[0] / (r.hp_max?.[0] || 1))}%:${Math.round(100 * r.hp[1] / (r.hp_max?.[1] || 1))}%`).join(" · ");
}
function renderMatches() {
  let ms = [...S.matches].reverse();
  if (mFilter === "done") ms = ms.filter((m) => m.status === "done");
  if (mFilter === "scheduled") ms = ms.filter((m) => m.status === "scheduled" || m.status === "running");
  if (mFilter === "bad") ms = ms.filter((m) => ["invalid", "error", "cancelled"].includes(m.status));
  setHTML($("#matchList"), ms.length ? ms.map((m) => `<div class="card click" data-m="${esc(m.id)}">
      <div class="row"><span class="muted">${esc(m.id)}</span><span class="chip ${esc(m.status)}" style="margin-left:auto">${esc(STATUS[m.status] || m.status)}</span></div>
      <div class="score"><span class="p1c">${esc(pn(m.p1))}</span> ${m.wins ? `${m.wins[0]} - ${m.wins[1]}` : "vs"} <span class="p2c">${esc(pn(m.p2))}</span></div>
      <div class="s">${esc(pc(m.p1))} vs ${esc(pc(m.p2))}</div>
      <div class="s">${m.status === "done" ? `เลือดเหลือรายยก ${pctRounds(m)} · ${m.duration}s` : esc(m.note)}</div></div>`).join("")
    : `<div class="muted">ไม่มีแมตช์</div>`);
  $$("#matchList .card").forEach((c) => (c.onclick = () => openMatch(c.dataset.m)));
}
$$("#mFilter button").forEach((b) => (b.onclick = () => {
  mFilter = b.dataset.f; $$("#mFilter button").forEach((x) => x.classList.toggle("on", x === b)); renderMatches();
}));

function renderPlayers() {
  const rec = Object.fromEntries(S.standings.map((r) => [r.id, r]));
  setHTML($("#playerList"), S.players.length ? S.players.map((p) => {
    const r = rec[p.id] || {};
    return `<div class="card"><div class="row"><span class="t">${esc(p.name)}</span>
      ${p.bot === "approved" ? '<span class="badge bot">BOT</span>' : ""}<span class="chip ${esc(p.char_status)}" style="margin-left:auto">${esc(STATUS[p.char_status] || "")}</span></div>
      <div class="s">ตัวละคร: <b>${esc(p.char_name)}</b></div>
      <div class="s">${p.bot === "approved" ? "สู้ด้วยบอทของตัวเอง" : p.bot === "pending" ? "บอทรออนุมัติ (ใช้ AI ของเกมไปก่อน)" : "สู้ด้วย AI ของเกม"}${p.active ? "" : " · <b>พักการแข่ง</b>"}</div>
      <div class="s">สถิติ: ชนะ ${r.w || 0} · เสมอ ${r.d || 0} · แพ้ ${r.l || 0}</div></div>`;
  }).join("") : `<div class="muted">ยังไม่มีผู้เล่น — ไปที่แท็บ “สมัครเข้าแข่ง”</div>`);
}

function renderRoster() {
  setHTML($("#rosterList"), S.chars.length ? S.chars.map((c) => `<div class="card">
      <div class="row"><span class="t">${esc(c.char_name)}</span><span class="chip ${esc(c.status)}" style="margin-left:auto">${esc(STATUS[c.status] || c.status)}</span></div>
      ${c.credit ? `<div class="s">ผู้สร้างตัวละคร: ${esc(c.credit)}</div>` : ""}
      <div class="s">${c.reserved_by ? `ตัวประจำของ <b>${esc(c.reserved_by)}</b> (คนอื่นเลือกไม่ได้)` : c.used_by.length ? `ผู้เล่นที่ใช้: ${esc(c.used_by.join(", "))}` : "ยังไม่มีคนเลือก"}</div>
      ${c.uploaded_by ? `<div class="s">อัปโหลดโดย ${esc(c.uploaded_by)}</div>` : ""}
      ${c.note ? `<div class="s err">${esc(c.note)}</div>` : ""}</div>`).join("") : `<div class="muted">ยังไม่มีตัวละคร</div>`);
}

function renderData() {
  setHTML($("#allInfo"), `ตัวละคร ${S.chars.filter((c) => c.status === "ready").length} ตัว · log แมตช์ ${S.logs_total || 0} แมตช์`);
  const list = S.chars.filter((c) => c.status === "ready");
  setHTML($("#dataTable"), `<tr><th>ตัวละคร</th><th>ใช้โดย</th><th>รายการ state</th><th>ทุกอย่างของตัวนี้</th></tr>` +
    list.map((c) => {
      const base = "/api/export/" + encodeURIComponent(c.id);
      return `<tr><td><b>${esc(c.char_name)}</b>${c.credit ? `<div class="muted small">${esc(c.credit)}</div>` : ""}</td>
        <td>${esc(c.reserved_by || c.used_by.join(", ") || "-")}</td>
        <td class="row wrap"><a href="${base}/states.md">.md</a> · <a href="${base}/states.csv">.csv (Excel)</a> · <a href="${base}/states.json">.json</a></td>
        <td><a href="${base}.zip">⬇ zip</a> <span class="muted small">(log ${c.logs} แมตช์)</span></td></tr>`;
    }).join(""));
}

// ---------------------------------------------------------------- join
function renderPick() {
  const cur = ($("#pickGrid input:checked") || {}).value;
  const list = S.chars.filter((c) => c.status !== "failed" && c.status !== "banned");
  setHTML($("#pickGrid"), list.map((c) => {
    const off = !!c.reserved_by || c.status !== "ready";
    const why = c.reserved_by ? `ตัวประจำของ ${esc(c.reserved_by)}` : c.status !== "ready" ? esc(STATUS[c.status]) : c.used_by.length ? `ใช้อยู่ ${c.used_by.length} คน` : "ว่าง";
    return `<label class="pick${off ? " off" : ""}"><input type="radio" name="char_id" value="${esc(c.id)}" ${off ? "disabled" : ""} ${cur === c.id ? "checked" : ""}>
      <b>${esc(c.char_name)}</b><span>${why}</span></label>`;
  }).join("") || `<span class="muted">ยังไม่มีตัวให้เลือก — อัปโหลดตัวของคุณเอง</span>`);
}
$$("#modeSeg input").forEach((r) => (r.onchange = () => {
  const up = $("#modeSeg input:checked").value === "upload";
  $("#pickBox").hidden = up; $("#uploadBox").hidden = !up;
}));
$("#joinForm").onsubmit = (ev) => {
  ev.preventDefault();
  const f = ev.target, msg = $("#joinMsg"), bar = $("#upBar");
  const fd = new FormData(f);
  if (fd.get("mode") === "pick" && !fd.get("char_id")) { msg.innerHTML = `<p class="err">เลือกตัวละครก่อน</p>`; return; }
  if (fd.get("mode") === "pick") fd.delete("char_file");
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/join");
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) bar.style.width = (100 * e.loaded / e.total) + "%"; };
  xhr.onload = () => {
    let r = {}; try { r = JSON.parse(xhr.responseText); } catch (e) {}
    if (r.ok) {
      msg.innerHTML = `<p class="ok">สมัครแล้ว: <b>${esc(r.player.name)}</b> ใช้ ${esc(r.player.char_name)}${r.player.char_status !== "ready" ? " — ตัวละครกำลังรอเทสโหลด" : ""} · รอแอดมินจัดแมตช์ ดูได้ที่แท็บ “ถ่ายทอดสด”</p>`;
      f.reset(); $("#pickBox").hidden = false; $("#uploadBox").hidden = true; refresh();
    } else msg.innerHTML = `<p class="err">${esc(r.error || ("ผิดพลาด " + xhr.status))}</p>`;
    bar.style.width = "0";
  };
  xhr.onerror = () => { msg.innerHTML = `<p class="err">ส่งไม่สำเร็จ</p>`; bar.style.width = "0"; };
  msg.textContent = "กำลังส่ง…";
  xhr.send(fd);
};
function renderRules() {
  const r = S.rules;
  setHTML($("#rules"), `<h3 style="margin-top:0">วิธีเข้าแข่ง</h3><ol class="list">
    <li>ใส่ชื่อของคุณ</li><li>เลือกตัวละครที่มีอยู่ หรืออัปโหลดตัวของคุณเอง (.zip/.rar ไม่เกิน ${r.max_upload_mb} MB)</li>
    <li>แอดมินเป็นคนจัดว่าใครแข่งกับใคร แล้วดูการแข่งสด ๆ ได้ที่แท็บ “ถ่ายทอดสด”</li></ol>
    <h3>กติกา</h3><ul>
    <li>ชนะ ${r.rounds} ยกก่อนชนะแมตช์ · ด่าน <code>${esc(r.stage)}</code> · ทุกแมตช์รันบนเครื่องกลางเครื่องเดียว</li>
    <li>ไม่ส่งบอท = ตัวละครสู้ด้วย AI ของเกม level ${r.ai_level} (ใช้ AI ในตัวละครถ้ามี)</li>
    <li>ห้ามมีไฟล์ .exe/.dll/.bat ในไฟล์ที่ส่ง · ตัวที่ crash ตอนเทสโหลดจะใช้แข่งไม่ได้</li>
    <li><b>เลือดเท่ากันทุกตัว ${r.life}</b> (สนามปรับให้เอง ไม่ว่าในไฟล์ตัวละครจะตั้งไว้เท่าไหร่)</li>
    <li><b>ห้ามตัวโกง</b> ระบบเทสจับเองแล้วแบนอัตโนมัติ:<ul>
      <li>ยิงกระสุนค้างบนจอพร้อมกันเกิน ${r.proj_limit} ลูก (ตัวปกติไม่เกิน ~15 ลูก)</li>
      <li><b>ตีครั้งเดียวตาย</b>: ทำดาเมจเกิน ${r.ohko_burst} จากเลือด ${r.life} ภายใน 1 วินาที</li>
      <li><b>อมตะ</b>: ยืนเฉย ๆ ให้ KFM ตี ${r.fair_seconds} วินาทีแล้วเลือดลดไม่ถึง ${r.immortal_min} (รวมพวกฮีลเลือดตัวเองคืน)</li>
      <li>แอดมินกดแบนเองได้ถ้าเจอวิธีโกงแบบอื่น</li></ul></li></ul>
    <h3>ข้อกำหนดไฟล์ตัวละคร</h3><ul>
    <li>ไฟล์ <b>.zip หรือ .rar</b> เท่านั้น (ไม่รับ .7z) ไม่ตั้งรหัสผ่าน · 1 ไฟล์ = 1 ตัวละคร</li>
    <li>ข้างในต้องมีไฟล์ <code>.def</code> ของตัวละครที่มีหัวข้อ <code>[Info]</code> และ <code>[Files]</code> และไฟล์ที่ .def อ้างถึง (sprite .sff, anim .air, cmd, cns/st) <b>ต้องอยู่ครบ ชื่อตรงกัน</b></li>
    <li>ลบโปรแกรมที่ติดมาออกก่อน (.exe .dll .bat เช่นตัวติดตั้ง/Fighter Factory) ไม่งั้นระบบไม่รับ</li>
    <li>ต้องเล่นบน <b>Ikemen GO</b> ได้ ตัวสำหรับ MUGEN 1.0/1.1 ผ่านง่ายสุด ตัว WinMUGEN รุ่นเก่ามาก ๆ บางตัว crash</li>
    <li>ระบบจะเทสโหลดสู้กับ KFM 2 รอบ ราว 2 นาที ถ้าเกมปิดตัวเอง (crash) หรือผิดกติกาจะใช้แข่งไม่ได้ ดูเหตุผลได้ในแท็บ “ตัวละคร”</li>
    <li>ควรมี <b>AI ในตัว</b> (ตัวที่ไม่มี AI จะกดมั่ว ๆ ตาม AI พื้นฐานของเกม)</li>
    <li>ห้ามตัวโกง/ตัวบั๊ก (Hypernull, ตัวอมตะ, ตายด้วยการโดนตีไม่ได้)</li></ul>
    <h3>ส่งบอท (ไม่บังคับ)</h3><ul>
    <li>zip ที่มี <code>bot.py</code> รันด้วย <code>python bot.py --player 1|2 --game-dir &lt;engine&gt;</code></li>
    <li>อ่านสถานะเกมทุกเฟรมจาก <code>&lt;game-dir&gt;/general_bot_telemetry.json</code> แล้วกดปุ่มของ P1/P2 ตาม <code>save/config.ini</code></li>
    <li>บอทเป็นโค้ด จะใช้ได้ก็ต่อเมื่อแอดมินอ่านโค้ดแล้วกดอนุมัติ</li></ul>`);
}

// ---------------------------------------------------------------- admin
let TOKEN = ""; try { TOKEN = localStorage.getItem("adminTok") || ""; } catch (e) {}
async function admin(action, body = {}) {
  const r = await fetch("/api/admin/" + action, { method: "POST", headers: { "Content-Type": "application/json", "X-Admin-Token": TOKEN }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  setHTML($("#adminMsg"), j.ok ? `<span class="ok">${esc(j.msg)}</span>` : `<span class="err">${esc(j.error || r.status)}</span>`);
  if (j.ok) refresh();
  return j.ok;
}
function confirmClick(btn, fn) {                     // second click within 3 s confirms (no browser dialogs)
  if (btn.classList.contains("arm")) { btn.classList.remove("arm"); fn(); return; }
  btn.classList.add("arm"); const t = btn.textContent; btn.textContent = "กดอีกครั้งเพื่อยืนยัน";
  setTimeout(() => { btn.classList.remove("arm"); btn.textContent = t; }, 3000);
}
async function login() {
  TOKEN = $("#tok").value.trim() || TOKEN;
  if (await admin("check")) {
    $("#adminBody").hidden = false; $("#loginBox").hidden = true; $("#adminMsg").textContent = "";
    loadRejections(); setInterval(loadRejections, 15000);
    try { localStorage.setItem("adminTok", TOKEN); } catch (e) {}
    renderAdmin();
  }
}
$("#tokBtn").onclick = login;
$$("#adminBody button[data-a]").forEach((b) => (b.onclick = () => {
  const run = () => admin(b.dataset.a);
  b.classList.contains("danger") ? confirmClick(b, run) : run();
}));
async function loadRejections() {
  const r = await fetch("/api/admin/rejections", { method: "POST", headers: { "Content-Type": "application/json", "X-Admin-Token": TOKEN }, body: "{}" });
  const j = await r.json().catch(() => ({}));
  if (!j.ok) return;
  setHTML($("#adminRejects"), j.items.length ? j.items.map((x) => `<li><b>${esc(x.name || "-")}</b>
    <span class="muted small">${esc(new Date(x.t * 1000).toLocaleTimeString("th-TH"))} · ${esc(x.ip)}${x.file ? " · " + esc(x.file) : ""}</span>
    <div class="err small">${esc(x.error)}</div></li>`).join("") : `<li class="muted">ยังไม่มี</li>`);
}
$("#rejRefresh").onclick = loadRejections;
$("#mkGo").onclick = () => admin("create_match", { p1: $("#mkP1").value, p2: $("#mkP2").value,
  count: +$("#mkCount").value, swap: $("#mkSwap").checked });

function fillSelect(sel, fallbackIdx) {
  const cur = sel.value;
  const changed = setHTML(sel, S.players.map((p) => `<option value="${esc(p.id)}" ${p.char_status !== "ready" || !p.active ? "disabled" : ""}>
    ${esc(p.name)} — ${esc(p.char_name)}${p.bot === "approved" ? " (BOT)" : ""}${p.char_status !== "ready" ? " [ตัวละครยังไม่พร้อม]" : ""}${!p.active ? " [พัก]" : ""}</option>`).join(""));
  if (!changed) return;                          // untouched: an open dropdown stays open
  if (cur && P[cur]) sel.value = cur; else if (S.players[fallbackIdx]) sel.value = S.players[fallbackIdx].id;
}
function renderAdmin() {
  if ($("#adminBody").hidden) return;
  fillSelect($("#mkP1"), 0); fillSelect($("#mkP2"), 1);
  const q = S.matches.filter((m) => m.status === "scheduled" || m.status === "running");
  const done = S.matches.filter((m) => ["done", "invalid", "error", "cancelled"].includes(m.status)).slice(-5).reverse();
  setHTML($("#adminQueue"), (q.length ? q.map((m) => `<li><div class="qrow">${matchLine(m)} <span class="chip ${esc(m.status)}">${esc(STATUS[m.status])}</span>
      ${m.status === "scheduled" ? `<button data-x="cancel_match" data-id="${esc(m.id)}">ยกเลิก</button>` : ""}</div></li>`).join("") : `<li class="muted">คิวว่าง</li>`) +
    done.map((m) => `<li><div class="qrow muted">${matchLine(m)} <span class="chip ${esc(m.status)}">${esc(STATUS[m.status])}</span>
      <button data-x="rematch" data-id="${esc(m.id)}">แข่งซ้ำ</button></div></li>`).join(""));
  setHTML($("#adminPlayers"), `<tr><th>id</th><th>ชื่อ</th><th>ตัวละคร</th><th>บอท</th><th></th></tr>` +
    S.players.map((p) => `<tr><td>${esc(p.id)}</td><td><b>${esc(p.name)}</b> ${p.active ? "" : "(พัก)"}</td><td>${esc(p.char_name)}</td>
      <td>${p.bot ? (p.bot === "approved" ? "อนุมัติแล้ว" : "<b>รออนุมัติ</b>") : "-"}</td>
      <td class="row wrap">
        ${p.bot ? `<button data-x="approve_bot" data-id="${esc(p.id)}" data-v="${p.bot === "approved" ? 0 : 1}">${p.bot === "approved" ? "ถอนอนุมัติบอท" : "อนุมัติบอท"}</button>` : ""}
        <button data-x="toggle_active" data-id="${esc(p.id)}">${p.active ? "พัก" : "กลับมาแข่ง"}</button>
        <button data-x="delete_player" data-id="${esc(p.id)}" class="danger">ลบ</button></td></tr>`).join(""));
  setHTML($("#adminChars"), `<tr><th>id</th><th>ตัวละคร</th><th>สถานะ</th><th>ใช้โดย</th><th></th></tr>` +
    S.chars.map((c) => `<tr><td>${esc(c.id)}</td><td><b>${esc(c.char_name)}</b><div class="muted small">${esc(c.credit)}</div></td>
      <td><span class="chip ${esc(c.status)}">${esc(STATUS[c.status] || c.status)}</span><div class="muted small">${esc(c.note)}</div></td>
      <td>${c.reserved_by ? `จองโดย ${esc(c.reserved_by)}` : esc(c.used_by.join(", ") || "-")}</td>
      <td class="row wrap"><button data-x="retest_char" data-id="${esc(c.id)}">เทสใหม่</button>
        ${c.status !== "banned" && !c.reserved_by ? `<button data-x="ban_char" data-id="${esc(c.id)}" class="danger">แบน</button>` : ""}
        <button data-x="delete_char" data-id="${esc(c.id)}" class="danger">ลบ</button></td></tr>`).join(""));
  $$("#adminQueue button, #adminPlayers button, #adminChars button").forEach((b) => (b.onclick = () => {
    const run = () => admin(b.dataset.x, { id: b.dataset.id, approved: b.dataset.v === "1" });
    b.classList.contains("danger") ? confirmClick(b, run) : run();
  }));
}

// ---------------------------------------------------------------- match detail
async function openMatch(id) {
  const m = await (await fetch("/api/match/" + encodeURIComponent(id))).json();
  const rounds = (m.rounds || []).map((r, i) => `<li>ยก ${i + 1}: เลือดเหลือ ${Math.round(100 * r.hp[0] / (r.hp_max?.[0] || 1))}% / ${Math.round(100 * r.hp[1] / (r.hp_max?.[1] || 1))}% → ${r.winner === 1 ? `<span class="p1c">${esc(pn(m.p1))}</span>` : r.winner === 2 ? `<span class="p2c">${esc(pn(m.p2))}</span>` : "เสมอ"}</li>`).join("");
  setHTML($("#modalBody"), `<h2>${matchLine(m)}</h2><p class="muted">${esc(m.id)} · ${esc(STATUS[m.status] || m.status)} ${m.note ? "· " + esc(m.note) : ""}</p>
    <ol class="list">${rounds || "<li class='muted'>ไม่มีข้อมูลยก</li>"}</ol><h3>% เลือดตลอดแมตช์</h3><canvas id="hpChart" width="1560" height="520"></canvas>
    <p class="muted"><span class="p1c">━ ${esc(pn(m.p1))} (P1)</span> &nbsp; <span class="p2c">━ ${esc(pn(m.p2))} (P2)</span> · เส้นแนวตั้ง = เริ่มยกใหม่</p>`);
  $("#modal").hidden = false;
  drawHp($("#hpChart"), m.timeline || []);
}
function drawHp(cv, tl) {
  const g = cv.getContext("2d"), W = cv.width, H = cv.height, pad = 40;
  g.clearRect(0, 0, W, H);
  if (!tl.length) { g.fillStyle = "#888"; g.font = "28px sans-serif"; g.fillText("ไม่มีข้อมูล", pad, H / 2); return; }
  const t0 = tl[0][0], t1 = tl[tl.length - 1][0] || 1;
  const mx = { 2: Math.max(...tl.map((r) => r[2]), 1), 3: Math.max(...tl.map((r) => r[3]), 1) };   // each side's full life
  const X = (t) => pad + (W - 2 * pad) * (t - t0) / Math.max(1e-6, t1 - t0), Y = (v, k) => H - pad - (H - 2 * pad) * v / mx[k];
  g.strokeStyle = "#8884"; g.lineWidth = 2;
  for (let i = 1; i < tl.length; i++) if (tl[i][1] !== tl[i - 1][1]) { g.beginPath(); g.moveTo(X(tl[i][0]), pad / 2); g.lineTo(X(tl[i][0]), H - pad); g.stroke(); }
  const css = getComputedStyle(document.documentElement);
  [[2, css.getPropertyValue("--p1")], [3, css.getPropertyValue("--p2")]].forEach(([k, col]) => {
    g.strokeStyle = col.trim(); g.lineWidth = 4; g.beginPath();
    tl.forEach((r, i) => { const x = X(r[0]), y = Y(r[k], k); if (i === 0 || r[1] !== tl[i - 1][1]) g.moveTo(x, y); else g.lineTo(x, y); });
    g.stroke();
  });
}
$("#modalX").onclick = () => ($("#modal").hidden = true);
$("#modal").onclick = (e) => { if (e.target.id === "modal") $("#modal").hidden = true; };

// ---------------------------------------------------------------- live HUD
function setSide(k, p, wins, need) {
  const pct = p.hp_max ? Math.max(0, Math.min(100, 100 * (p.hp || 0) / p.hp_max)) : 0;
  $("#hp" + k).style.width = pct + "%";
  $("#pw" + k).style.width = Math.min(100, (p.power || 0) / 30) + "%";
  $("#w" + k).innerHTML = Array.from({ length: need }, (_, i) => `<span class="${i < wins ? "won" : ""}"></span>`).join("");
}
function onLive(L) {
  const names = L.names || [];
  $("#n1").textContent = names[0] || L.players[0].name || "—";
  $("#n2").textContent = names[1] || L.players[1].name || "—";
  const need = S.rules.rounds || 2;
  setSide(1, L.players[0], L.wins[0], need); setSide(2, L.players[1], L.wins[1], need);
  const fighting = L.phase === "fight" || L.phase === "between";
  $("#roundLbl").textContent = L.phase === "idle" ? "รอแมตช์" : L.phase === "loading" ? "กำลังโหลด…" : L.test ? "เทสโหลด" : `ROUND ${L.round_no || 1}`;
  $("#clock").textContent = fighting && L.elapsed ? `${Math.floor(L.elapsed / 60)}:${String(Math.floor(L.elapsed % 60)).padStart(2, "0")}` : "";
  let banner = "";
  if (L.round_state >= 3 && L.players[0].hp !== null && !L.test) {
    const a = L.players[0].hp / (L.players[0].hp_max || 1), b = L.players[1].hp / (L.players[1].hp_max || 1);
    banner = L.players[0].hp > 0 && L.players[1].hp <= 0 ? `${names[0] || "P1"} ชนะยกนี้` : L.players[1].hp > 0 && L.players[0].hp <= 0 ? `${names[1] || "P2"} ชนะยกนี้`
      : a > b ? `${names[0] || "P1"} ชนะยกนี้` : b > a ? `${names[1] || "P2"} ชนะยกนี้` : "เสมอ";
  }
  $("#banner").textContent = banner;
  setHTML($("#nowBox"), L.title ? `<b>${esc(L.title)}</b><div class="muted">${L.match ? esc(L.match) : ""}</div>` : `<span class="muted">ยังไม่มีแมตช์</span>`);
}
function connectLive() {
  const es = new EventSource("/api/live");
  es.onmessage = (ev) => { try { onLive(JSON.parse(ev.data)); } catch (e) {} };
  es.onerror = () => { es.close(); setTimeout(connectLive, 2000); };
}

// ---------------------------------------------------------------- start
let first = "live"; try { first = location.hash.slice(1) || localStorage.getItem("tab") || "live"; } catch (e) {}
if (!$("#tab-" + first)) first = "live";
showTab(first);
window.addEventListener("hashchange", () => { const t = location.hash.slice(1); if ($("#tab-" + t)) showTab(t); });
if (TOKEN) { $("#tok").value = TOKEN; login(); }
refresh(); setInterval(refresh, 3000); connectLive();
