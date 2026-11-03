"use strict";

/* Quản lý Mi Band 6 — giao diện web.
   Server trên máy tính giữ kết nối Bluetooth; trang này gọi REST API và nhận sự kiện qua WebSocket.
   Ngôn ngữ: chuỗi tiếng Việt là bản gốc; tiếng Anh lấy từ /static/i18n/en.json. */

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const pad = (n) => String(n).padStart(2, "0");
const DAY_BITS = [1, 2, 4, 8, 16, 32, 64];

/* ============================================================ ngôn ngữ */

const LANG = (() => {
  try {
    const saved = localStorage.getItem("mb6_lang");
    if (saved === "vi" || saved === "en") return saved;
  } catch { /* trình duyệt chặn localStorage */ }
  return (navigator.language || "vi").toLowerCase().startsWith("vi") ? "vi" : "en";
})();
const LOCALE = LANG === "en" ? "en-US" : "vi-VN";
let CATALOG = {};

/** Dịch một chuỗi gốc tiếng Việt; {tên} được thay bằng vars.tên. */
function t(source, vars) {
  let out = LANG === "en" ? CATALOG[source] ?? source : source;
  if (vars) out = out.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ""));
  return out;
}

/** Dịch toàn bộ chữ tĩnh trong trang (nút, nhãn, placeholder…) một lần lúc mở. */
function translateDom() {
  document.documentElement.lang = LANG;
  if (LANG === "vi") return;
  document.title = t(document.title);
  const skip = new Set(["SCRIPT", "STYLE", "PRE", "CODE", "TEXTAREA"]);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const p = node.parentElement;
      if (!p || skip.has(p.tagName) || p.closest("svg, #logView")) return NodeFilter.FILTER_REJECT;
      return node.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const raw = node.nodeValue;
    const key = raw.trim().replace(/\s+/g, " ");
    if (key in CATALOG) node.nodeValue = raw.replace(raw.trim(), () => CATALOG[key]);
  }
  $$("[data-i18n-value]").forEach((el) => { el.value = t(el.value); });
  for (const attr of ["placeholder", "aria-label", "title", "data-empty"]) {
    $$(`[${attr}]`).forEach((el) => {
      const v = el.getAttribute(attr);
      if (v in CATALOG) el.setAttribute(attr, CATALOG[v]);
    });
  }
}

async function loadLanguage() {
  if (LANG === "en") {
    try {
      CATALOG = await (await fetch("/static/i18n/en.json", { cache: "no-cache" })).json();
    } catch { CATALOG = {}; }
  }
  translateDom();
  $$(".lang button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === LANG)));
  document.documentElement.classList.remove("i18n-pending");
}

$$(".lang button").forEach((b) => b.addEventListener("click", async () => {
  if (b.dataset.lang === LANG) return;
  try { localStorage.setItem("mb6_lang", b.dataset.lang); } catch { /* bỏ qua */ }
  await api("/api/prefs", { lang: b.dataset.lang }).catch(() => {});
  location.reload();
}));

const weekdays = () => (LANG === "en" ? ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"] : ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]);
const fmtInt = (n) => (n == null ? "—" : Number(n).toLocaleString(LOCALE));
const fmtDec = (n, d = 2) => Number(n).toLocaleString(LOCALE, { minimumFractionDigits: d, maximumFractionDigits: d });

/* ============================================================ tiện ích */

let META = null;
let STATE = { connected: false, busy: false, settings: {}, profile: {}, saved_devices: [] };
let formsFilled = false;

async function api(path, data) {
  const opts = data === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  };
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error(t("Không liên lạc được với server trên máy tính."));
  }
  const json = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok || json.error) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}

let toastTimer;
function toast(msg, error = false) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.toggle("error", error);
  el.hidden = false;
  el.style.animation = "none";
  void el.offsetWidth;
  el.style.animation = "";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), error ? 7000 : 3800);
}

/** Chạy thao tác cho một nút: khóa nút khi chờ, báo kết quả bằng toast. */
async function run(btn, fn, okMsg) {
  if (btn) btn.disabled = true;
  try {
    const r = await fn();
    const msg = okMsg ?? r?.message;
    if (msg) toast(msg);
    return r;
  } catch (e) {
    toast(e.message, true);
    throw e;
  } finally {
    if (btn) btn.disabled = btn.hasAttribute("data-conn") ? !STATE.connected : false;
  }
}
const quiet = (p) => p.catch(() => {});

/* ============================================================ điều hướng */

const PAGES = ["overview", "settings", "alarms", "tools", "device"];
const SUBS = ["profile", "display", "apps", "health"];

function route() {
  const [page0, sub0] = (location.hash.slice(1) || "").split("/");
  const page = PAGES.includes(page0) ? page0 : STATE.connected ? "overview" : "device";
  $$(".page").forEach((p) => (p.hidden = p.id !== `page-${page}`));
  $$(".nav a").forEach((a) => a.setAttribute("aria-current", a.getAttribute("href") === `#${page}` ? "page" : "false"));
  if (page === "settings") {
    const sub = SUBS.includes(sub0) ? sub0 : "profile";
    $$(".subtabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.sub === sub)));
    $$(".subpage").forEach((s) => (s.hidden = s.id !== `sub-${sub}`));
  }
  window.scrollTo({ top: 0 });
}
window.addEventListener("hashchange", route);
$$(".subtabs button").forEach((b) => b.addEventListener("click", () => (location.hash = `#settings/${b.dataset.sub}`)));

/* ============================================================ vòng tay + số liệu */

const live = { hr: null, steps: null, battery: null, charging: false, hrHistory: [] };

function drawBand() {
  const now = new Date();
  $("#bTime").textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
  $("#bDate").textContent = `${weekdays()[(now.getDay() + 6) % 7]}  ${pad(now.getDate())}/${pad(now.getMonth() + 1)}`;
  $("#bHr").textContent = `♥ ${live.hr || "--"}`;
  const goal = Number(STATE.profile.goal || 8000);
  const frac = live.steps == null ? 0 : Math.min(1, live.steps / goal);
  const c = 2 * Math.PI * 24;
  $("#bRing").setAttribute("stroke-dasharray", `${(frac * c).toFixed(1)} ${c.toFixed(1)}`);
  $("#bSteps").textContent = live.steps == null ? "--" : fmtInt(live.steps);
  $("#bSteps").style.fontSize = (live.steps ?? 0) >= 10000 ? "10px" : "";
  const hasBat = live.battery != null;
  $("#bBatText").textContent = hasBat ? `${live.battery}%${live.charging ? " ⚡" : ""}` : "";
  const bat = $("#bBat");
  bat.setAttribute("width", hasBat ? (30 * Math.max(0, Math.min(100, live.battery))) / 100 : 0);
  bat.classList.toggle("low", hasBat && live.battery <= 20);
  $("#dateLine").textContent = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long" }).format(now);
}
setInterval(drawBand, 15000);

function drawSpark() {
  const pts = live.hrHistory;
  const line = $("#hrLine");
  if (pts.length < 2) { line.setAttribute("points", ""); return; }
  const lo = Math.min(...pts) - 4;
  const hi = Math.max(...pts) + 4;
  const step = 200 / (pts.length - 1);
  line.setAttribute("points", pts.map((v, i) => `${(i * step).toFixed(1)},${(46 - ((v - lo) / (hi - lo)) * 44).toFixed(1)}`).join(" "));
}

function updateGoal() {
  const goal = Number(STATE.profile.goal || 8000);
  const pct = live.steps == null ? 0 : Math.min(100, (live.steps / goal) * 100);
  $("#goalBar").style.width = `${pct}%`;
  $("#goalBar").parentElement.setAttribute("aria-valuenow", String(Math.round(pct)));
  $("#goalPct").textContent = `${Math.round(pct)}%`;
  $("#goalLabel").textContent = fmtInt(goal);
}

function render(kind, d) {
  if (d == null) return;
  switch (kind) {
    case "battery": {
      live.battery = d.level;
      live.charging = d.charging;
      $("#bat").textContent = `${d.level}%`;
      const c = 2 * Math.PI * 40;
      $("#batRing").setAttribute("stroke-dasharray", `${((d.level / 100) * c).toFixed(1)} ${c.toFixed(1)}`);
      $("#batRing").classList.toggle("low", d.level <= 20);
      const notes = [];
      if (d.charging) notes.push(t("Đang sạc"));
      if (d.last_charge) {
        const when = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(d.last_charge));
        notes.push(t("Sạc lần cuối {when}", { when }));
      }
      $("#batNote").textContent = notes.join(" · ");
      $("#statusBat").textContent = `${d.level}%`;
      break;
    }
    case "activity":
      live.steps = d.steps;
      $("#steps").textContent = fmtInt(d.steps);
      if (d.meters != null) $("#dist").textContent = fmtDec(d.meters / 1000);
      if (d.calories != null) $("#cal").textContent = fmtInt(d.calories);
      updateGoal();
      break;
    case "heart_rate":
      live.hr = d;
      live.hrHistory.push(d);
      if (live.hrHistory.length > 40) live.hrHistory.shift();
      $("#hr").textContent = d;
      drawSpark();
      break;
    case "device_info":
      $("#iName").textContent = d.name || "—";
      $("#iFirmware").textContent = d.firmware || "—";
      $("#iHardware").textContent = d.hardware || "—";
      $("#iSerial").textContent = d.serial || "—";
      break;
    case "band_time":
      if (typeof d === "string") {
        const tm = new Date(d.slice(0, 19));
        $("#iBandTime").textContent = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit", second: "2-digit", day: "2-digit", month: "2-digit" }).format(tm);
      }
      break;
    case "alarms":
      fillAlarms(d);
      break;
  }
  drawBand();
}

/* ============================================================ trạng thái */

const PROTO = { classic: () => t("Kiểu cũ"), "2021": () => t("Kiểu mới (2021)"), auto: () => t("Tự động") };
let wasReconnecting = false;

function applyState(st) {
  const wasConnected = STATE.connected;
  STATE = st;
  const on = st.connected;
  const waiting = !on && !st.busy && st.reconnect;  // đang chờ tới lượt tự kết nối lại
  $$("[data-conn]").forEach((b) => (b.disabled = !on));
  $("#connectBtn").disabled = on || st.busy;
  $("#disconnectBtn").disabled = !(on || st.reconnect);  // khi đang chờ nối lại: bấm để thôi chờ
  $("#scanBtn").disabled = st.busy;
  $("#keepConn").checked = st.settings?.keep_connected ?? true;
  $("#demoBanner").hidden = !st.demo;
  $$(".conn-hint").forEach((el) => (el.hidden = on));
  $("#overviewEmpty").hidden = on;
  $("#overviewBody").hidden = !on;

  const status = $("#status");
  status.dataset.state = on ? "on" : st.busy || waiting ? "busy" : "off";
  $("#statusText").textContent = on ? st.device?.name || "Mi Smart Band 6"
    : st.busy ? t("Đang kết nối…") : waiting ? t("Đang chờ kết nối lại…") : t("Chưa kết nối");
  if (waiting) {
    const at = new Date(st.reconnect.at * 1000);
    const time = `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`;
    $("#connStatus").className = "conn-status";
    $("#connStatus").textContent = t("Mất kết nối với vòng tay. Tự thử lại lúc {time} (lần {n}).", { time, n: st.reconnect.attempt });
  } else if (on && wasReconnecting) {
    $("#connStatus").className = "conn-status ok";
    $("#connStatus").textContent = t("Đã tự kết nối lại với vòng tay.");
  }
  wasReconnecting = !!st.reconnect;
  if (!on) {
    $("#statusBat").textContent = "";
    live.hr = null;
    $("#hrLiveBtn").setAttribute("aria-pressed", "false");
  } else {
    $("#iProtocol").textContent = (PROTO[st.device?.protocol] || (() => "—"))();
  }
  if (!formsFilled) {
    fillForms();
    formsFilled = true;
  }
  for (const [kind, data] of Object.entries(st.live || {})) render(kind, data);
  updateGoal();
  drawBand();
  if (on !== wasConnected && !location.hash) route();
}

/* ============================================================ WebSocket */

function connectEvents() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/events`);
  ws.onopen = () => ($("#offline").hidden = true);
  ws.onclose = () => {
    $("#offline").hidden = false;
    setTimeout(connectEvents, 2000);
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    switch (msg.type) {
      case "hello":
        $("#logView").textContent = "";
        (msg.logs || []).forEach(appendLog);
        applyState(msg.state);
        route();
        break;
      case "state": applyState(msg.state); break;
      case "log": appendLog(msg.line); break;
      case "disconnected":
        toast(msg.reconnecting ? t("Vòng tay đã ngắt kết nối. Đang tự kết nối lại…")
          : t("Vòng tay đã ngắt kết nối. Bấm Kết nối để nối lại."), true);
        stopFindPhone();
        break;
      case "cloud": renderCloud(msg.status); break;
      case "device_event":
        if (msg.data === 0x08) startFindPhone();
        else if (msg.data === 0x0f) stopFindPhone();
        break;
      default: render(msg.type, msg.data);
    }
  };
}

/* ============================================================ nhật ký */

function appendLog(line) {
  const v = $("#logView");
  const atBottom = v.scrollTop + v.clientHeight >= v.scrollHeight - 30;
  v.append(line + "\n");
  if (v.childNodes.length > 4000) v.removeChild(v.firstChild);
  if (atBottom) v.scrollTop = v.scrollHeight;
}
$("#logGroup").addEventListener("toggle", () => { const v = $("#logView"); v.scrollTop = v.scrollHeight; });
$("#logClearBtn").onclick = () => quiet(run(null, async () => { await api("/api/log/clear", {}); $("#logView").textContent = ""; }));
$("#logSaveBtn").onclick = () => {
  const blob = new Blob([$("#logView").textContent], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  const d = new Date();
  a.href = URL.createObjectURL(blob);
  a.download = `miband6-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}.txt`;
  a.click();
  // ứng dụng macOS (WKWebView) tải tệp bất đồng bộ: thu hồi blob ngay thì tệp tải về bị rỗng
  setTimeout(() => URL.revokeObjectURL(a.href), 60000);
};

/* ============================================================ thiết bị: quét, kết nối */

let selected = null;
let scanList = [];

const radio = (name) => $(`input[name="${name}"]:checked`)?.value;
function setRadio(name, value) {
  const el = $(`input[name="${name}"][value="${value}"]`);
  if (el) el.checked = true;
}

function signalBars(rssi) {
  const n = rssi == null ? 0 : rssi > -60 ? 4 : rssi > -70 ? 3 : rssi > -82 ? 2 : 1;
  return `<span class="signal" title="${rssi ?? "?"} dBm">${[1, 2, 3, 4].map((i) => `<i class="${i <= n ? "on" : ""}"></i>`).join("")}</span>`;
}

function renderDevices(list) {
  scanList = list;
  const ul = $("#deviceList");
  ul.textContent = "";
  if (!list.length) {
    const li = document.createElement("li");
    li.className = "placeholder";
    li.textContent = t("Không thấy Mi Band 6. Tắt Bluetooth trên điện thoại, chạm cho vòng tay sáng màn hình rồi quét lại.");
    ul.append(li);
    return;
  }
  list.forEach((d, i) => {
    const li = document.createElement("li");
    li.className = "dev";
    li.tabIndex = 0;
    li.setAttribute("role", "option");
    li.innerHTML = `<svg class="ic"><use href="#i-band"/></svg><div class="dev-main"><div class="dev-name"></div><div class="dev-addr"></div></div>${d.is_band ? `<span class="tag">Mi Band</span>` : ""}${signalBars(d.rssi)}`;
    $(".dev-name", li).textContent = d.name || t("(không tên)");
    $(".dev-addr", li).textContent = d.address;
    li.onclick = () => pickDevice(i);
    li.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pickDevice(i); } };
    ul.append(li);
  });
  pickDevice(0);
}

function pickDevice(i) {
  const d = scanList[i];
  if (!d) return;
  selected = { address: d.address, name: d.name };
  $$("#deviceList .dev").forEach((li, j) => li.setAttribute("aria-selected", String(j === i)));
  $("#selectedDevice").textContent = d.name || d.address;
  const saved = STATE.saved_devices.find((s) => s.address === d.address);
  if (saved?.auth_key && !STATE.env_key) $("#keyInput").value = saved.auth_key;
  if (saved?.protocol) setRadio("proto", saved.protocol);
}

$("#scanBtn").onclick = async () => {
  $("#scanLabel").textContent = t("Đang quét…");
  try {
    const r = await run($("#scanBtn"), () => api("/api/scan", { show_all: $("#showAll").checked }));
    renderDevices(r.devices);
    if (r.devices.length) toast(t("Tìm thấy {n} thiết bị.", { n: r.devices.length }));
  } catch { /* đã báo */ } finally {
    $("#scanLabel").textContent = t("Quét lại");
  }
};

$("#showKey").onclick = () => {
  const k = $("#keyInput");
  const show = k.type === "password";
  k.type = show ? "text" : "password";
  $("#showKey").textContent = show ? t("Ẩn mã") : t("Hiện mã");
};
$("#keyHelpBtn").onclick = () => $("#keyHelp").showModal();

$("#connectBtn").onclick = async () => {
  const status = $("#connStatus");
  status.className = "conn-status";
  if (!selected) {
    status.textContent = t("Hãy quét và chọn vòng tay trước.");
    status.classList.add("error");
    return;
  }
  status.textContent = t("Đang kết nối và xác thực…");
  $("#connectBtn").disabled = true;
  try {
    const r = await api("/api/connect", { address: selected.address, key: $("#keyInput").value, protocol: radio("proto") || "auto" });
    status.textContent = t("Đã kết nối ({proto}). Giờ trên vòng tay đã được đồng bộ.", { proto: PROTO[r.protocol]().toLowerCase() });
    status.classList.add("ok");
    applyState(r.state);
    toast(t("Đã kết nối vòng tay."));
    location.hash = "#overview";
  } catch (e) {
    status.textContent = t("Không kết nối được: {error}", { error: e.message });
    status.classList.add("error");
    $("#connectBtn").disabled = STATE.connected || STATE.busy;
  }
};

$("#disconnectBtn").onclick = async () => {
  try {
    const r = await run($("#disconnectBtn"), () => api("/api/disconnect", {}), t("Đã ngắt kết nối."));
    applyState(r.state);
    $("#connStatus").className = "conn-status";
    $("#connStatus").textContent = t("Đã ngắt kết nối.");
  } catch { /* đã báo */ }
};

$("#keepConn").onchange = () => quiet(run(null, async () => {
  applyState((await api("/api/prefs", { keep_connected: $("#keepConn").checked })).state);
}));

/* ============================================================ tổng quan */

$("#refreshBtn").onclick = () => quiet(run($("#refreshBtn"), () => api("/api/refresh", {}), t("Đã đọc dữ liệu mới nhất từ vòng tay.")));
$("#syncTimeBtn").onclick = () => quiet(run($("#syncTimeBtn"), async () => {
  render("band_time", (await api("/api/time/sync", {})).band_time);
}, t("Đã đồng bộ giờ với máy tính.")));

$("#hrMeasureBtn").onclick = async () => {
  $("#hrNote").textContent = t("Đang đo, giữ yên tay khoảng 15–30 giây…");
  try {
    const r = await run($("#hrMeasureBtn"), () => api("/api/hr/measure", {}));
    const now = new Date();
    $("#hrNote").textContent = t("Đo lúc {time}.", { time: `${pad(now.getHours())}:${pad(now.getMinutes())}` });
    render("heart_rate", r.bpm);
  } catch {
    $("#hrNote").textContent = t("Không đo được. Đeo vòng sát cổ tay hơn rồi thử lại.");
  }
};

$("#hrLiveBtn").onclick = async () => {
  const btn = $("#hrLiveBtn");
  const on = btn.getAttribute("aria-pressed") !== "true";
  try {
    await run(btn, () => api("/api/hr/live", { on }), on ? t("Đang theo dõi nhịp tim liên tục.") : t("Đã dừng theo dõi nhịp tim."));
    btn.setAttribute("aria-pressed", String(on));
    $("#hrNote").textContent = on ? t("Đang theo dõi liên tục.") : t("Đã dừng theo dõi liên tục.");
  } catch { /* đã báo */ }
};

/* ============================================================ cài đặt */

function fillSelect(sel, items, current) {
  sel.textContent = "";
  for (const [value, label] of items) sel.add(new Option(label, value));
  if (current != null) sel.value = String(current);
}

function bindSchedule(seg) {
  const target = $(`#${seg.dataset.schedule}`);
  const upd = () => {
    const on = $("input:checked", seg)?.value === "scheduled";
    $$("input", target).forEach((i) => (i.disabled = !on));
    $(".range", target)?.classList.toggle("dim", !on);
  };
  $$("input", seg).forEach((i) => i.addEventListener("change", upd));
  upd();
}

function fillProfile() {
  const p = STATE.profile || {};
  const b = (v, d) => (v == null ? d : v);
  $("#pAlias").value = p.alias || "";
  $("#pBirth").value = p.birth || "2000-01-01";
  setRadio("gender", b(p.gender, 0));
  $("#pHeight").value = b(p.height, 170);
  $("#pWeight").value = b(p.weight, 60);
  $("#pGoal").value = b(p.goal, 8000);
  $("#pGoalNotify").checked = b(p.goal_notify, true);
  setRadio("wear", b(p.wear_left, true) ? "left" : "right");
}

function fillForms() {
  const s = STATE.settings || {};
  const b = (v, d) => (v == null ? d : v);
  fillProfile();

  fillSelect($("#dLang"), Object.entries(META.languages), s.language || "vi_VN");
  fillSelect($("#dDate"), META.date_formats.map((f) => [f, f]), s.date_format || "dd/MM/yyyy");
  setRadio("h24", b(s.time_24h, true) ? "1" : "0");
  setRadio("metric", b(s.metric, true) ? "1" : "0");
  setRadio("lift", s.lift || "on");
  $("#dLiftFrom").value = s.lift_from || "07:00";
  $("#dLiftTo").value = s.lift_to || "23:00";
  $("#dLiftSens").checked = !!s.lift_sensitive;
  setRadio("night", s.night || "off");
  $("#dNightFrom").value = s.night_from || "19:00";
  $("#dNightTo").value = s.night_to || "07:00";
  $("#dPwOn").checked = !!s.pw_on;
  $("#dPw").value = s.pw || "";
  buildAppSorter(s.display_items || META.display_default);
  buildShortcuts(s.shortcuts || META.shortcuts_default);

  fillSelect($("#hInterval"), META.hr_intervals.map((m) => [m, m === 0 ? t("Tắt") : m === 1 ? t("Mỗi phút") : t("Mỗi {m} phút", { m })]), b(s.hr_interval, 0));
  fillSelect($("#hThreshold"), META.hr_thresholds.map((v) => [v, t("{v} nhịp/phút", { v })]), b(s.hr_threshold, 120));
  $("#hSleep").checked = !!s.hr_sleep;
  $("#hActivity").checked = !!s.hr_activity;
  $("#hAlert").checked = !!s.hr_alert;
  $("#hStress").checked = !!s.stress;
  $("#iOn").checked = !!s.idle_on;
  $("#iMinutes").value = b(s.idle_minutes, 60);
  $("#iFrom").value = s.idle_from || "08:00";
  $("#iTo").value = s.idle_to || "22:00";
  $("#iLunch").checked = b(s.idle_lunch, true);
  $("#iLunchFrom").value = s.idle_lunch_from || "12:00";
  $("#iLunchTo").value = s.idle_lunch_to || "13:30";
  setRadio("dnd", s.dnd || "off");
  $("#nFrom").value = s.dnd_from || "23:00";
  $("#nTo").value = s.dnd_to || "07:00";
  $("#nLift").checked = !!s.dnd_lift;

  fillSelect($("#tIcon"), Object.entries(META.icons).map(([label, id]) => [id, t(label)]));
  $("#tFindSound").checked = b(s.find_sound, true);
  fillAlarms((s.alarms || []).filter((a) => a.in_use));

  const last = STATE.saved_devices.find((d) => d.address === STATE.last_device);
  if (last) {
    selected = { address: last.address, name: last.name };
    $("#selectedDevice").textContent = last.name || last.address;
    $("#keyInput").value = STATE.env_key ? "" : last.auth_key || "";
    setRadio("proto", last.protocol || "auto");
  } else {
    setRadio("proto", "auto");
  }
  if (STATE.env_key) {
    $("#keyInput").placeholder = t("Để trống để dùng auth key trong tệp .env");
    $("#envKeyNote").hidden = false;
  }
  $$(".seg[data-schedule]").forEach(bindSchedule);
}

const collectors = {
  profile: () => ({
    alias: $("#pAlias").value, birth: $("#pBirth").value, gender: Number(radio("gender") ?? 0),
    height: Number($("#pHeight").value), weight: Number($("#pWeight").value),
  }),
  goal: () => ({ goal: Number($("#pGoal").value), notify: $("#pGoalNotify").checked }),
  wear: () => ({ left: radio("wear") !== "right" }),
  formats: () => ({ language: $("#dLang").value, time_24h: radio("h24") === "1", date_format: $("#dDate").value, metric: radio("metric") === "1" }),
  lift: () => ({ mode: radio("lift"), from: $("#dLiftFrom").value, to: $("#dLiftTo").value, sensitive: $("#dLiftSens").checked }),
  night: () => ({ mode: radio("night"), from: $("#dNightFrom").value, to: $("#dNightTo").value }),
  password: () => ({ on: $("#dPwOn").checked, pin: $("#dPw").value.trim() }),
  "menu-apps": () => ({ kind: "apps", items: appKeys("shown") }),
  "menu-shortcuts": () => ({ kind: "shortcuts", items: $$("#menuShortcuts li").filter((li) => $(".switch", li).checked).map((li) => li.dataset.key) }),
  hr: () => ({
    interval: Number($("#hInterval").value), sleep: $("#hSleep").checked, activity: $("#hActivity").checked,
    alert: $("#hAlert").checked, threshold: Number($("#hThreshold").value), stress: $("#hStress").checked,
  }),
  idle: () => ({
    on: $("#iOn").checked, minutes: Number($("#iMinutes").value), from: $("#iFrom").value, to: $("#iTo").value,
    lunch: $("#iLunch").checked, lunch_from: $("#iLunchFrom").value, lunch_to: $("#iLunchTo").value,
  }),
  dnd: () => ({ mode: radio("dnd"), from: $("#nFrom").value, to: $("#nTo").value, lift: $("#nLift").checked }),
};

$$("[data-save]").forEach((btn) => btn.addEventListener("click", async () => {
  const key = btn.dataset.save;
  try {
    const r = await run(btn, () => api(`/api/settings/${key.startsWith("menu") ? "menu" : key}`, collectors[key]()));
    STATE.settings = r.state.settings;
    STATE.profile = r.state.profile;
    updateGoal();
    drawBand();
  } catch { /* đã báo */ }
}));

/* ============================================================ sắp xếp ứng dụng (hiện / ẩn) */

// Mi Band 6 không có thư mục "Thêm": mọi ứng dụng hiện nằm trong một danh sách theo thứ tự.
const BUCKET = { shown: "#appsShown", hidden: "#appsHidden" };
let dragged = null;
const appKeys = (group) => $$("li", $(BUCKET[group])).map((li) => li.dataset.key);
const appLabel = (key) => t(META.menu_labels[key] || key);

function moveApp(li, group, before = null) {
  const target = $(BUCKET[group]);
  const from = li.parentElement?.dataset.group;
  const sel = $("select", li);
  if (group === "hidden" && li.dataset.key === META.menu_always_visible) {
    toast(t("Cài đặt không ẩn được; nếu ẩn bạn sẽ không mở được cài đặt trên vòng tay."), true);
    sel.value = from;
    return;
  }
  target.insertBefore(li, before && before.parentElement === target ? before : null);
  sel.value = group;
}

function dragHandlers(li, onDrop) {
  li.draggable = true;
  li.ondragstart = (e) => { dragged = li; li.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; };
  li.ondragend = () => {
    dragged = null;
    li.classList.remove("dragging");
    $$(".apps li.over").forEach((x) => x.classList.remove("over"));
    $$(".apps.drop").forEach((x) => x.classList.remove("drop"));
  };
  li.ondragover = (e) => { if (dragged && dragged !== li) { e.preventDefault(); li.classList.add("over"); } };
  li.ondragleave = () => li.classList.remove("over");
  li.ondrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    li.classList.remove("over");
    if (dragged && dragged !== li) onDrop(dragged, li);
  };
}

function moveButtons(li) {
  return `<button type="button" class="icon-btn up" aria-label="${t("Đưa lên")}"><svg class="ic"><use href="#i-up"/></svg></button>`
    + `<button type="button" class="icon-btn down" aria-label="${t("Đưa xuống")}"><svg class="ic"><use href="#i-down"/></svg></button>`;
}
function bindMoveButtons(li) {
  $(".up", li).onclick = () => li.previousElementSibling && li.parentElement.insertBefore(li, li.previousElementSibling);
  $(".down", li).onclick = () => li.nextElementSibling && li.parentElement.insertBefore(li.nextElementSibling, li);
}

function appRow(key) {
  const li = document.createElement("li");
  li.dataset.key = key;
  li.innerHTML = `<svg class="ic grip" aria-hidden="true"><use href="#i-grip"/></svg><span class="name"></span>`
    + `<select><option value="shown">${t("Hiện")}</option><option value="hidden">${t("Ẩn")}</option></select>`
    + moveButtons(li);
  $(".name", li).textContent = appLabel(key);
  const sel = $("select", li);
  sel.setAttribute("aria-label", t("Nhóm của {app}", { app: appLabel(key) }));
  if (key === META.menu_always_visible) sel.options[1].disabled = true;
  sel.onchange = () => moveApp(li, sel.value);
  bindMoveButtons(li);
  dragHandlers(li, (src, dst) => { if (src.parentElement?.closest(".sorter")) moveApp(src, dst.parentElement.dataset.group, dst); });
  return li;
}

function buildAppSorter(shown) {
  Object.values(BUCKET).forEach((s) => ($(s).textContent = ""));
  const used = new Set();
  const add = (group, keys) => keys.filter((k) => META.display_all.includes(k) && !used.has(k)).forEach((k) => {
    used.add(k);
    const li = appRow(k);
    $(BUCKET[group]).append(li);
    $("select", li).value = group;
  });
  add("shown", [...shown, META.menu_always_visible]);
  add("hidden", META.display_all);
}

Object.values(BUCKET).forEach((s) => {
  const ol = $(s);
  ol.addEventListener("dragover", (e) => { if (dragged?.closest(".sorter")) { e.preventDefault(); ol.classList.add("drop"); } });
  ol.addEventListener("dragleave", (e) => { if (e.target === ol) ol.classList.remove("drop"); });
  ol.addEventListener("drop", (e) => {
    e.preventDefault();
    ol.classList.remove("drop");
    if (dragged?.closest(".sorter")) moveApp(dragged, ol.dataset.group);
  });
});

$("#appsResetBtn").onclick = () => {
  buildAppSorter(META.display_default);
  toast(t("Đã đưa về bố cục gốc. Bấm Lưu bố cục để ghi vào vòng tay."));
};

function buildShortcuts(enabled) {
  const ol = $("#menuShortcuts");
  ol.textContent = "";
  const order = [...enabled.filter((k) => META.shortcuts_all.includes(k)), ...META.shortcuts_all.filter((k) => !enabled.includes(k))];
  for (const key of order) {
    const li = document.createElement("li");
    li.dataset.key = key;
    li.innerHTML = `<svg class="ic grip" aria-hidden="true"><use href="#i-grip"/></svg><span class="name"></span><input type="checkbox" class="switch">${moveButtons(li)}`;
    $(".name", li).textContent = appLabel(key);
    const sw = $(".switch", li);
    sw.checked = enabled.includes(key);
    sw.setAttribute("aria-label", appLabel(key));
    li.classList.toggle("off", !sw.checked);
    sw.onchange = () => li.classList.toggle("off", !sw.checked);
    bindMoveButtons(li);
    dragHandlers(li, (src, dst) => { if (src.parentElement === ol) ol.insertBefore(src, dst); });
    ol.append(li);
  }
}

/* ============================================================ báo thức */

let alarms = [];
const blankAlarms = () => Array.from({ length: 10 }, (_, i) => ({ slot: i, in_use: false, enabled: true, hour: 7, minute: 0, days: 0 }));

function daysSummary(days) {
  if (!days) return t("Một lần");
  if (days === 127) return t("Mỗi ngày");
  if (days === 31) return t("Ngày thường");
  if (days === 96) return t("Cuối tuần");
  return weekdays().filter((_, i) => days & DAY_BITS[i]).join(", ");
}

function fillAlarms(list) {
  alarms = blankAlarms();
  for (const a of list || []) {
    if (a.slot >= 0 && a.slot < alarms.length) alarms[a.slot] = { ...a, in_use: true, days: a.days || 0 };
  }
  renderAlarms();
}

function renderAlarms() {
  const box = $("#alarmList");
  box.textContent = "";
  const used = alarms.filter((a) => a.in_use);
  $("#alarmEmpty").hidden = used.length > 0;
  $("#alarmAddBtn").disabled = used.length >= alarms.length;
  for (const a of used) {
    const card = document.createElement("article");
    card.className = `alarm${a.enabled ? "" : " off"}`;
    card.innerHTML = `
      <div class="alarm-top">
        <input type="time" class="alarm-time" aria-label="${t("Giờ báo thức")}">
        <input type="checkbox" class="switch" aria-label="${t("Bật báo thức")}">
      </div>
      <div class="days" role="group" aria-label="${t("Lặp lại")}"></div>
      <div class="alarm-foot"><span class="sum"></span>
        <button type="button" class="icon-btn del" aria-label="${t("Xóa báo thức")}"><svg class="ic"><use href="#i-trash"/></svg></button></div>`;
    const time = $(".alarm-time", card);
    time.value = `${pad(a.hour)}:${pad(a.minute)}`;
    time.onchange = () => { const [h, m] = (time.value || "07:00").split(":").map(Number); a.hour = h; a.minute = m; };
    const sw = $(".switch", card);
    sw.checked = a.enabled;
    sw.onchange = () => { a.enabled = sw.checked; card.classList.toggle("off", !a.enabled); };
    const sum = $(".sum", card);
    sum.textContent = daysSummary(a.days);
    weekdays().forEach((label, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "day";
      b.textContent = label;
      b.setAttribute("aria-pressed", String((a.days & DAY_BITS[i]) !== 0));
      b.onclick = () => {
        a.days ^= DAY_BITS[i];
        b.setAttribute("aria-pressed", String((a.days & DAY_BITS[i]) !== 0));
        sum.textContent = daysSummary(a.days);
      };
      $(".days", card).append(b);
    });
    $(".del", card).onclick = () => { a.in_use = false; renderAlarms(); };
    box.append(card);
  }
}

$("#alarmAddBtn").onclick = () => {
  const free = alarms.find((a) => !a.in_use);
  if (!free) return;
  Object.assign(free, { in_use: true, enabled: true, hour: 7, minute: 0, days: 0 });
  renderAlarms();
  $$(".alarm-time").at(-1)?.focus();
};
$("#alarmsReadBtn").onclick = () => quiet(run($("#alarmsReadBtn"), async () => fillAlarms((await api("/api/alarms")).alarms), t("Đã đọc báo thức từ vòng tay.")));
$("#alarmsSaveBtn").onclick = () => quiet(run($("#alarmsSaveBtn"), () => api("/api/alarms", { alarms })));

/* ============================================================ công cụ */

$("#notifyBtn").onclick = () => quiet(run($("#notifyBtn"), () => api("/api/notify", {
  title: $("#tTitle").value, body: $("#tBody").value, app: $("#tApp").value, icon: Number($("#tIcon").value),
})));
$("#callBtn").onclick = () => quiet(run($("#callBtn"), () => api("/api/call", { name: $("#tCaller").value })));
$("#callStopBtn").onclick = () => quiet(run($("#callStopBtn"), () => api("/api/call/stop", {})));
$("#findBtn").onclick = () => quiet(run($("#findBtn"), () => api("/api/find", { on: true })));
$("#findStopBtn").onclick = () => quiet(run($("#findStopBtn"), () => api("/api/find", { on: false })));
$("#tFindSound").onchange = () => quiet(api("/api/prefs", { find_sound: $("#tFindSound").checked }));

/* Khi vòng tay bấm "Tìm điện thoại": server trên Mac tự phát âm thanh;
   nếu trang được mở từ máy khác (điện thoại) thì trình duyệt phát thay. */
let audioCtx;
let beepTimer;
document.addEventListener("pointerdown", () => {
  if (!audioCtx && window.AudioContext) audioCtx = new AudioContext();
  audioCtx?.resume?.();
});
function beep() {
  if (!audioCtx) return;
  const o = audioCtx.createOscillator();
  const g = audioCtx.createGain();
  o.frequency.value = 880;
  g.gain.setValueAtTime(0.0001, audioCtx.currentTime);
  g.gain.exponentialRampToValueAtTime(0.3, audioCtx.currentTime + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + 0.5);
  o.connect(g).connect(audioCtx.destination);
  o.start();
  o.stop(audioCtx.currentTime + 0.55);
}
function startFindPhone() {
  const dlg = $("#findPhone");
  if (!dlg.open) dlg.showModal();
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  if ($("#tFindSound").checked && !(local && META.platform === "darwin")) {
    clearInterval(beepTimer);
    beep();
    beepTimer = setInterval(beep, 1200);
    setTimeout(stopFindPhone, 30000);
  }
}
function stopFindPhone() {
  clearInterval(beepTimer);
  const dlg = $("#findPhone");
  if (dlg.open) dlg.close();
}
$("#findPhone").addEventListener("close", () => {
  clearInterval(beepTimer);
  quiet(api("/api/find-phone/stop", {}));
});

/* ============================================================ khởi động */

async function init() {
  await loadLanguage();
  quiet(api("/api/prefs", { lang: LANG }));
  try {
    META = await api("/api/meta");
  } catch (e) {
    $("#offline").hidden = false;
    $("#offline").textContent = t("Không tải được dữ liệu từ server: {error}", { error: e.message });
    return;
  }
  alarms = blankAlarms();
  renderAlarms();
  drawBand();
  route();
  connectEvents();
}

/* ============================================================ đồng bộ hồ sơ từ Mi Fitness */

let cloudOpen = false;
let cloudSeq = -1;
let cloudTimer = null;

function renderCloud(st) {
  if (!st) return;
  if (st.seq != null) {
    if (st.seq < cloudSeq) return;  // bản trạng thái cũ đến muộn
    cloudSeq = st.seq;
  }
  STATE.cloud = st;
  const s = st.state || "idle";
  if (s === "done") {
    fillProfile();
    if (cloudOpen) {
      closeCloud();
      toast(st.message || t("Đã lấy hồ sơ từ Mi Fitness."));
    }
    return;
  }
  if (!cloudOpen) return;
  const busy = s === "checking" || s === "fetching";
  $("#cloudBusy").hidden = !busy;
  $("#cloudBusyText").textContent = s === "fetching" ? t("Đang đọc hồ sơ từ Mi Fitness…") : t("Đang kết nối tới máy chủ Xiaomi…");
  $("#cloudLogin").hidden = s !== "login";
  $("#cloudError").hidden = s !== "error";
  $("#cloudError").textContent = st.error || "";
  $("#cloudRetryBtn").hidden = s !== "error";
  $("#cloudReloginBtn").hidden = s !== "error";
  clearInterval(cloudTimer);
  if (s === "login") {
    if ($("#cloudQr").getAttribute("src") !== st.qr) $("#cloudQr").src = st.qr;
    $("#cloudLink").href = st.url || "#";
    const tick = () => {
      const left = Math.max(0, Math.round(st.expires - Date.now() / 1000));
      $("#cloudExpire").textContent = t("Mã hết hạn sau {time}", { time: `${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` });
    };
    tick();
    cloudTimer = setInterval(tick, 1000);
  }
}

async function startCloud(fresh = false) {
  cloudOpen = true;
  const dlg = $("#cloudDialog");
  if (!dlg.open) dlg.showModal();
  renderCloud({ state: "checking" });
  try {
    const r = await api("/api/cloud/sync", { write: true, fresh });
    renderCloud(r.cloud);
  } catch (e) {
    renderCloud({ state: "error", error: e.message });
  }
}

function closeCloud() {
  cloudOpen = false;
  clearInterval(cloudTimer);
  const dlg = $("#cloudDialog");
  if (dlg.open) dlg.close();
}

function cancelCloud() {
  const active = ["checking", "login", "fetching"].includes(STATE.cloud?.state);
  closeCloud();
  if (active) quiet(api("/api/cloud/cancel", {}));
}

$("#cloudSyncBtn").addEventListener("click", () => startCloud(false));
$("#cloudRetryBtn").addEventListener("click", () => startCloud(false));
$("#cloudReloginBtn").addEventListener("click", () => startCloud(true));
$("#cloudCancelBtn").addEventListener("click", cancelCloud);
$("#cloudDialog").addEventListener("cancel", (ev) => { ev.preventDefault(); cancelCloud(); });

init();
