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

const PAGES = ["overview", "health", "settings", "alarms", "tools", "device"];
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
  if (page === "health") {
    healthAnchor = sub0 || "";
    quiet(loadHealth());
  }
}
window.addEventListener("hashchange", route);
$$(".subtabs button").forEach((b) => b.addEventListener("click", () => (location.hash = `#settings/${b.dataset.sub}`)));

/* ============================================================ vòng tay + số liệu */

const live = { hr: null, steps: null, battery: null, charging: false, hrHistory: [] };

function drawBand() {
  $("#dateLine").textContent = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long" }).format(new Date());
}

/** Mặt đồng hồ trên hình vòng tay: ảnh xem trước thật (của mặt đã cài hoặc ảnh người dùng chọn). */
function renderWatchface(info) {
  const img = $("#wfImage");
  const has = !!info?.preview;
  if (has) img.setAttribute("href", `/api/watchface/preview?v=${info.version || 0}`);
  else img.removeAttribute("href");
  img.style.display = has ? "" : "none";
  $("#wfEmpty").hidden = has;
  let current = t("Không rõ");
  if (info?.name) {
    const when = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(info.installed * 1000));
    current = t("{name} (cài lúc {when})", { name: info.name, when });
  } else if (has) {
    current = t("Mặt đồng hồ có sẵn (đã đặt ảnh xem trước)");
  }
  $("#wfCurrent").textContent = current;
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
  markSync();
  renderWatchface(st.watchface);
  renderHealthStatus(st.health);
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
      case "health": renderHealthStatus(msg.status); break;
      case "health_data": if (!$("#page-health").hidden) quiet(loadHealth()); break;
      case "watchface_progress": renderWatchfaceProgress(msg.data); break;
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
/** Chọn một ô trong nhóm radio; value null = chưa biết (bỏ chọn tất cả). */
function setRadio(name, value) {
  if (value == null) {
    $$(`input[name="${name}"]`).forEach((el) => (el.checked = false));
    return;
  }
  const el = $(`input[name="${name}"][value="${value}"]`);
  if (el) el.checked = true;
}
/** Công tắc; value null = chưa biết (hiện ở giữa, phải chọn trước khi lưu). */
function setSwitch(el, value) {
  el.indeterminate = value == null;
  el.checked = !!value;
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
    const unknown = markSync();
    toast(unknown ? t("Đã kết nối. {n} nhóm cài đặt chưa đồng bộ với vòng tay: xem ở mục Cài đặt.", { n: unknown }) : t("Đã kết nối vòng tay."));
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
/** Như fillSelect, nhưng current null thêm dòng "Chưa biết" (giá trị trên vòng tay chưa biết). */
function fillSelectKnown(sel, items, current) {
  fillSelect(sel, current == null ? [["", t("— Chưa biết —")], ...items] : items, current ?? "");
  sel.classList.toggle("unknown", current == null);
  sel.addEventListener("change", () => sel.classList.remove("unknown"), { once: true });
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

/* Vòng tay không cho đọc lại cài đặt: giá trị chưa từng được ghi từ ứng dụng hiện là "chưa biết"
   (không chọn sẵn), thay vì một giá trị mặc định trông như thật. */
function fillProfile() {
  const p = STATE.profile || {};
  const known = !!p.birth;
  $("#pAlias").value = p.alias || "";
  $("#pBirth").value = p.birth || "";
  setRadio("gender", known ? p.gender ?? 0 : null);
  $("#pHeight").value = p.height ?? "";
  $("#pWeight").value = p.weight ?? "";
  $("#pGoal").value = p.goal ?? "";
  setSwitch($("#pGoalNotify"), p.goal_notify ?? null);
  setRadio("wear", p.wear_left == null ? null : p.wear_left ? "left" : "right");
}

function fillForms() {
  const s = STATE.settings || {};
  const b = (v, d) => (v == null ? d : v);
  fillProfile();

  const has = (k) => s[k] != null;
  fillSelectKnown($("#dLang"), Object.entries(META.languages), s.language ?? null);
  fillSelectKnown($("#dDate"), META.date_formats.map((f) => [f, f]), s.date_format ?? null);
  setRadio("h24", has("time_24h") ? (s.time_24h ? "1" : "0") : null);
  setRadio("metric", has("metric") ? (s.metric ? "1" : "0") : null);
  setRadio("lift", s.lift ?? null);
  $("#dLiftFrom").value = s.lift_from || "07:00";
  $("#dLiftTo").value = s.lift_to || "23:00";
  setSwitch($("#dLiftSens"), has("lift") ? !!s.lift_sensitive : null);
  setRadio("night", s.night ?? null);
  $("#dNightFrom").value = s.night_from || "19:00";
  $("#dNightTo").value = s.night_to || "07:00";
  setSwitch($("#dPwOn"), has("pw_on") ? !!s.pw_on : null);
  $("#dPw").value = s.pw || "";
  buildAppSorter(s.display_items || META.display_default);
  buildShortcuts(s.shortcuts || META.shortcuts_default);

  const hrKnown = has("hr_interval");
  fillSelectKnown($("#hInterval"), META.hr_intervals.map((m) => [m, m === 0 ? t("Tắt") : m === 1 ? t("Mỗi phút") : t("Mỗi {m} phút", { m })]), hrKnown ? s.hr_interval : null);
  fillSelectKnown($("#hThreshold"), META.hr_thresholds.map((v) => [v, t("{v} nhịp/phút", { v })]), hrKnown ? b(s.hr_threshold, 120) : null);
  setSwitch($("#hSleep"), hrKnown ? !!s.hr_sleep : null);
  setSwitch($("#hActivity"), hrKnown ? !!s.hr_activity : null);
  setSwitch($("#hAlert"), hrKnown ? !!s.hr_alert : null);
  setSwitch($("#hStress"), hrKnown ? !!s.stress : null);
  const idleKnown = has("idle_on");
  setSwitch($("#iOn"), idleKnown ? !!s.idle_on : null);
  $("#iMinutes").value = b(s.idle_minutes, 60);
  $("#iFrom").value = s.idle_from || "08:00";
  $("#iTo").value = s.idle_to || "22:00";
  setSwitch($("#iLunch"), idleKnown ? b(s.idle_lunch, true) : null);
  $("#iLunchFrom").value = s.idle_lunch_from || "12:00";
  $("#iLunchTo").value = s.idle_lunch_to || "13:30";
  setRadio("dnd", s.dnd ?? null);
  $("#nFrom").value = s.dnd_from || "23:00";
  $("#nTo").value = s.dnd_to || "07:00";
  setSwitch($("#nLift"), has("dnd") ? !!s.dnd_lift : null);

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

/** Ô đầu tiên trong nhóm còn để "chưa biết" (chưa chọn), hoặc null nếu đã đủ. */
function incompleteField(group) {
  for (const seg of $$(".seg", group)) if ($("input[type=radio]", seg) && !$("input:checked", seg)) return $("input", seg);
  for (const sel of $$("select", group)) if (sel.value === "") return sel;
  for (const sw of $$(".switch", group)) if (sw.indeterminate) return sw;
  for (const inp of $$('input[type="number"], input[type="date"]', group)) if (inp.value === "") return inp;
  return null;
}

$$("[data-save]").forEach((btn) => btn.addEventListener("click", async () => {
  const key = btn.dataset.save;
  const missing = incompleteField(btn.closest(".group"));
  if (missing) {
    toast(t("Chọn giá trị cho mọi mục trong nhóm này trước khi lưu."), true);
    (missing.closest(".seg") ? $("label", missing.closest(".seg")) : missing).scrollIntoView({ block: "center" });
    missing.focus();
    return;
  }
  try {
    const r = await run(btn, () => api(`/api/settings/${key.startsWith("menu") ? "menu" : key}`, collectors[key]()));
    STATE.settings = r.state.settings;
    STATE.profile = r.state.profile;
    markSync();
    updateGoal();
    drawBand();
  } catch { /* đã báo */ }
}));

/* Nhóm cài đặt chưa từng được ứng dụng ghi lên vòng tay: gắn nhãn "Chưa đồng bộ". */
const SYNC_KEYS = {
  profile: (s, p) => !!p.birth, goal: (s, p) => p.goal != null && p.goal_notify != null, wear: (s, p) => p.wear_left != null,
  formats: (s) => s.language != null, lift: (s) => s.lift != null, night: (s) => s.night != null,
  password: (s) => s.pw_on != null, "menu-apps": (s) => s.display_items != null, "menu-shortcuts": (s) => s.shortcuts != null,
  hr: (s) => s.hr_interval != null, idle: (s) => s.idle_on != null, dnd: (s) => s.dnd != null,
};
function markSync() {
  const s = STATE.settings || {};
  const p = STATE.profile || {};
  let unknown = 0;
  $$("[data-save]").forEach((btn) => {
    const known = SYNC_KEYS[btn.dataset.save]?.(s, p) ?? true;
    const group = btn.closest(".group");
    let badge = $(".sync-badge", group);
    if (!known && !badge) {
      badge = document.createElement("span");
      badge.className = "sync-badge";
      badge.textContent = t("Chưa đồng bộ");
      $(".group-head h2", group).append(badge);
    } else if (known && badge) {
      badge.remove();
    }
    if (!known) unknown++;
  });
  $("#unsyncedNote").hidden = !unknown;
  return unknown;
}

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

/* ============================================================ mặt đồng hồ */

const readBase64 = (file) => new Promise((resolve, reject) => {
  const r = new FileReader();
  r.onload = () => resolve(String(r.result).split(",")[1] || "");
  r.onerror = () => reject(r.error);
  r.readAsDataURL(file);
});

function renderWatchfaceProgress(d) {
  const pct = d.total ? Math.round((d.sent / d.total) * 100) : 0;
  $("#wfProgressRow").hidden = false;
  $("#wfBar").style.width = `${pct}%`;
  $("#wfPct").textContent = `${pct}%`;
}

$("#wfInstallBtn").onclick = () => quiet(run($("#wfInstallBtn"), async () => {
  const file = $("#wfFile").files[0];
  if (!file) throw new Error(t("Chọn tệp mặt đồng hồ (.bin) trước."));
  const preview = $("#wfPreview").files[0];
  renderWatchfaceProgress({ sent: 0, total: 1 });
  try {
    const r = await api("/api/watchface", { name: file.name, file: await readBase64(file), preview: preview ? await readBase64(preview) : null });
    applyState(r.state);
    return r;
  } finally {
    $("#wfProgressRow").hidden = true;
  }
}));
$("#wfPreviewBtn").onclick = () => quiet(run($("#wfPreviewBtn"), async () => {
  const preview = $("#wfPreview").files[0];
  if (!preview) throw new Error(t("Chọn ảnh xem trước trước (ảnh chụp mặt đồng hồ đang dùng)."));
  applyState((await api("/api/watchface/preview", { image: await readBase64(preview) })).state);
}, t("Đã đặt ảnh xem trước.")));
$("#wfClearBtn").onclick = () => quiet(run($("#wfClearBtn"), async () => {
  applyState((await api("/api/watchface/preview", { image: null })).state);
}, t("Đã bỏ ảnh xem trước.")));

/* ============================================================ ảnh nền tùy chỉnh */

/* Tọa độ tính theo điểm ảnh của màn hình vòng tay (152 × 486). Ảnh nằm tại (ox, oy) với tỉ lệ scale. */
const WP = { W: 152, H: 486, R: 76, img: null, base: 1, scale: 1, ox: 0, oy: 0, k: 1 };
const DIGIT_W = 44;
const DIGIT_H = 64;
const DIGIT_X = (152 - 2 * DIGIT_W) / 2;
const WP_ROWS = { top: 40, middle: 177, bottom: 314 };
let wpDigits = null;
let wpDigitsColor = "";
let wpDrag = null;

async function wpMakeDigits() {
  const color = radio("wpColor") || "light";
  if (wpDigits && wpDigitsColor === color) return;
  await document.fonts.load('700 60px "Be Vietnam Pro"').catch(() => {});
  wpDigits = [...Array(10).keys()].map((d) => {
    const c = document.createElement("canvas");
    c.width = DIGIT_W;
    c.height = DIGIT_H;
    const g = c.getContext("2d");
    g.font = '700 60px "Be Vietnam Pro", -apple-system, sans-serif';
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.shadowColor = color === "light" ? "rgba(0, 0, 0, .65)" : "rgba(255, 255, 255, .6)";
    g.shadowBlur = 4;
    g.fillStyle = color === "light" ? "#fff" : "#000";
    g.fillText(String(d), DIGIT_W / 2, DIGIT_H / 2 + 3);
    return c;
  });
  wpDigitsColor = color;
}
/** Vị trí hàng giờ và hàng phút (góc trên trái), hoặc null nếu không hiện giờ. */
function wpTimeRows() {
  const pos = radio("wpTime");
  if (pos === "off" || !WP_ROWS[pos]) return null;
  return [[DIGIT_X, WP_ROWS[pos]], [DIGIT_X, WP_ROWS[pos] + DIGIT_H + 4]];
}
function wpDrawTime(g) {
  const rows = wpTimeRows();
  if (!rows || !wpDigits) return;
  const now = new Date();
  [pad(now.getHours()), pad(now.getMinutes())].forEach((txt, r) => {
    [...txt].forEach((ch, i) => g.drawImage(wpDigits[Number(ch)], rows[r][0] + i * DIGIT_W, rows[r][1]));
  });
}
function wpClamp() {
  const w = WP.img.width * WP.scale;
  const h = WP.img.height * WP.scale;
  // ảnh lớn hơn màn hình: không để lộ khoảng trống; nhỏ hơn: không để ảnh ra ngoài màn hình
  WP.ox = w >= WP.W ? Math.min(0, Math.max(WP.W - w, WP.ox)) : Math.max(0, Math.min(WP.W - w, WP.ox));
  WP.oy = h >= WP.H ? Math.min(0, Math.max(WP.H - h, WP.oy)) : Math.max(0, Math.min(WP.H - h, WP.oy));
}
function wpReset() {
  const { img } = WP;
  const cover = Math.max(WP.W / img.width, WP.H / img.height);
  const contain = Math.min(WP.W / img.width, WP.H / img.height);
  WP.base = radio("wpFit") === "contain" ? contain : cover;
  WP.scale = WP.base;
  $("#wpZoom").value = 0;
  WP.ox = (WP.W - img.width * WP.scale) / 2;
  WP.oy = (WP.H - img.height * WP.scale) / 2;
  wpDraw();
}
function wpZoomTo(scale) {
  const s1 = WP.scale;
  const s2 = Math.max(WP.base, Math.min(WP.base * 4, scale));
  // giữ nguyên điểm ở giữa màn hình khi phóng to
  WP.ox = WP.W / 2 - ((WP.W / 2 - WP.ox) * s2) / s1;
  WP.oy = WP.H / 2 - ((WP.H / 2 - WP.oy) * s2) / s1;
  WP.scale = s2;
  $("#wpZoom").value = Math.round((s2 / WP.base - 1) * 100);
  wpClamp();
  wpDraw();
}
function wpScreenPath(g, x, y, k) {
  const w = WP.W * k, h = WP.H * k, r = WP.R * k;
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}
function wpDraw() {
  if (!WP.img) return;
  // khung chỉnh: cả ảnh (phần bị cắt tối đi) và khung màn hình vòng tay ở giữa
  const stage = $("#wpStage");
  const box = stage.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  stage.width = Math.round(box.width * dpr);
  stage.height = Math.round(box.height * dpr);
  const g = stage.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, box.width, box.height);
  const k = (WP.k = Math.min(1, (box.height - 32) / WP.H, (box.width - 32) / WP.W));
  const wx = (box.width - WP.W * k) / 2;
  const wy = (box.height - WP.H * k) / 2;
  g.imageSmoothingQuality = "high";
  g.drawImage(WP.img, wx + WP.ox * k, wy + WP.oy * k, WP.img.width * WP.scale * k, WP.img.height * WP.scale * k);
  g.save();
  g.translate(wx, wy);
  g.scale(k, k);
  wpDrawTime(g);
  g.restore();
  g.beginPath();
  g.rect(0, 0, box.width, box.height);
  wpScreenPath(g, wx, wy, k);
  g.fillStyle = "rgba(8, 11, 10, .72)";
  g.fill("evenodd");
  g.beginPath();
  wpScreenPath(g, wx, wy, k);
  g.strokeStyle = "rgba(255, 255, 255, .55)";
  g.lineWidth = 1;
  g.stroke();

  // kết quả đúng 152 × 486 điểm ảnh như trên vòng tay
  const out = $("#wpResult").getContext("2d");
  wpBackground(out);
  wpDrawTime(out);
}
function wpBackground(g) {
  g.fillStyle = "#000";
  g.fillRect(0, 0, WP.W, WP.H);
  g.imageSmoothingQuality = "high";
  g.drawImage(WP.img, WP.ox, WP.oy, WP.img.width * WP.scale, WP.img.height * WP.scale);
}
const bytesToBase64 = (u8) => {
  let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
};
const rgbaOf = (canvas) => ({
  w: canvas.width, h: canvas.height,
  rgba: bytesToBase64(new Uint8Array(canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data.buffer)),
});

$("#wpFile").onchange = () => {
  const file = $("#wpFile").files[0];
  if (!file) return;
  const img = new Image();
  img.onload = async () => {
    WP.img = img;
    ["#wpEditor", "#wpControls", "#wpFoot"].forEach((sel) => ($(sel).hidden = false));
    await wpMakeDigits();
    wpReset();
  };
  img.onerror = () => toast(t("Không mở được ảnh này. Chọn ảnh PNG hoặc JPEG."), true);
  img.src = URL.createObjectURL(file);
};
const stageEl = $("#wpStage");
stageEl.tabIndex = 0;
stageEl.addEventListener("pointerdown", (e) => {
  if (!WP.img) return;
  wpDrag = { x: e.clientX, y: e.clientY, ox: WP.ox, oy: WP.oy };
  stageEl.setPointerCapture(e.pointerId);
  stageEl.classList.add("dragging");
});
stageEl.addEventListener("pointermove", (e) => {
  if (!wpDrag) return;
  WP.ox = wpDrag.ox + (e.clientX - wpDrag.x) / WP.k;
  WP.oy = wpDrag.oy + (e.clientY - wpDrag.y) / WP.k;
  wpClamp();
  wpDraw();
});
const endDrag = () => { wpDrag = null; stageEl.classList.remove("dragging"); };
stageEl.addEventListener("pointerup", endDrag);
stageEl.addEventListener("pointercancel", endDrag);
stageEl.addEventListener("wheel", (e) => {
  if (!WP.img) return;
  e.preventDefault();
  wpZoomTo(WP.scale * (e.deltaY < 0 ? 1.06 : 1 / 1.06));
}, { passive: false });
stageEl.addEventListener("keydown", (e) => {
  if (!WP.img) return;
  const step = e.shiftKey ? 10 : 2;
  const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  if (moves[e.key]) {
    e.preventDefault();
    WP.ox += moves[e.key][0];
    WP.oy += moves[e.key][1];
    wpClamp();
    wpDraw();
  } else if (e.key === "+" || e.key === "=") wpZoomTo(WP.scale * 1.1);
  else if (e.key === "-") wpZoomTo(WP.scale / 1.1);
});
$("#wpZoom").addEventListener("input", () => wpZoomTo(WP.base * (1 + Number($("#wpZoom").value) / 100)));
$$('input[name="wpFit"]').forEach((el) => el.addEventListener("change", () => WP.img && wpReset()));
$$('input[name="wpTime"]').forEach((el) => el.addEventListener("change", wpDraw));
$$('input[name="wpColor"]').forEach((el) => el.addEventListener("change", async () => { await wpMakeDigits(); wpDraw(); }));
$("#wpResetBtn").onclick = () => WP.img && wpReset();
window.addEventListener("resize", () => { if (WP.img && !$("#sub-display").hidden) wpDraw(); });

$("#wpPreviewBtn").onclick = () => quiet(run($("#wpPreviewBtn"), async () => {
  wpDraw();
  applyState((await api("/api/watchface/preview", { image: $("#wpResult").toDataURL("image/png") })).state);
}, t("Đã đặt ảnh xem trước.")));
$("#wpInstallBtn").onclick = () => quiet(run($("#wpInstallBtn"), async () => {
  if (!WP.img) throw new Error(t("Chọn ảnh trước."));
  wpDraw();
  const bg = document.createElement("canvas");
  bg.width = WP.W;
  bg.height = WP.H;
  wpBackground(bg.getContext("2d"));
  const pv = document.createElement("canvas");   // ảnh nhỏ để chọn mặt đồng hồ trên vòng tay
  pv.width = WP.W / 2;
  pv.height = Math.round(WP.H / 2);
  pv.getContext("2d").drawImage($("#wpResult"), 0, 0, pv.width, pv.height);
  const rows = wpTimeRows();
  renderWatchfaceProgress({ sent: 0, total: 1 });
  try {
    const r = await api("/api/wallpaper", {
      background: rgbaOf(bg), preview: rgbaOf(pv), image: $("#wpResult").toDataURL("image/png"),
      digits: rows ? wpDigits.map(rgbaOf) : [], hours: rows ? rows[0] : null, minutes: rows ? rows[1] : null,
    });
    applyState(r.state);
    return r;
  } finally {
    $("#wfProgressRow").hidden = true;
  }
}));

/* ============================================================ sức khỏe */

const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
const shiftDate = (iso, days) => {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};
const hhmm = (ts) => { const d = new Date(ts * 1000); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const shortDate = (iso) => new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "numeric" }).format(new Date(`${iso}T12:00:00`));
const longDate = (iso) => new Intl.DateTimeFormat(LOCALE, { weekday: "short", day: "numeric", month: "short" }).format(new Date(`${iso}T12:00:00`));
const dateTime = (ts) => new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(ts * 1000));
function fmtMinutes(min) {
  const h = Math.floor(min / 60);
  const m = Math.round(min % 60);
  return h ? t("{h} giờ {m} phút", { h, m }) : t("{m} phút", { m });
}

const STAGES = [
  ["awake", () => t("Thức"), "var(--c-awake)"],
  ["rem", () => t("REM"), "var(--c-rem)"],
  ["light", () => t("Ngủ nông"), "var(--c-light)"],
  ["deep", () => t("Ngủ sâu"), "var(--c-deep)"],
];
const stageInfo = (key) => STAGES.find((s) => s[0] === key);

const sportName = (k) => ({
  1: t("Chạy ngoài trời"), 2: t("Chạy máy"), 3: t("Đi bộ"), 4: t("Đạp xe"), 5: t("Tập tự do"), 6: t("Bơi trong hồ"),
  7: t("Bơi ngoài trời"), 8: t("Đạp xe trong nhà"), 9: t("Máy tập elip"), 10: t("Leo núi"), 15: t("Đi bộ đường dài"),
  18: t("Bóng đá"), 21: t("Nhảy dây"), 23: t("Máy chèo thuyền"), 52: t("Tập sức mạnh"), 60: t("Yoga"),
  78: t("Cricket"), 85: t("Bóng rổ"), 89: t("Bóng bàn"), 92: t("Cầu lông"),
})[k] ?? t("Bài tập {k}", { k });

const stressLabel = (v) => (v < 40 ? t("Thư giãn") : v < 60 ? t("Bình thường") : v < 80 ? t("Trung bình") : t("Cao"));

let healthDate = todayISO();
let healthData = null;
let healthAnchor = "";

function renderHealthStatus(st) {
  if (!st) return;
  const line = $("#hSyncLine");
  if (st.state === "running") {
    line.textContent = t("Đang lấy dữ liệu từ vòng tay: {step}…", { step: st.step || "" });
  } else if (st.last_sync) {
    line.textContent = t("Đồng bộ lần cuối {when}", { when: dateTime(st.last_sync) })
      + (st.errors?.length ? ` · ${t("chưa lấy được: {list}", { list: st.errors.join(", ") })}` : "");
  } else {
    line.textContent = t("Chưa đồng bộ dữ liệu sức khỏe.");
  }
  $("#hSyncBtn").disabled = !STATE.connected || st.state === "running";
}

async function loadHealth() {
  const r = await api(`/api/health?date=${healthDate}`);
  healthData = r.health;
  renderHealthStatus(r.status);
  renderHealth();
  if (healthAnchor) {
    $(`#health-${healthAnchor}`)?.scrollIntoView({ block: "start" });
    healthAnchor = "";
  }
}

$("#hDate").addEventListener("change", () => {
  if (!$("#hDate").value) return;
  healthDate = $("#hDate").value > todayISO() ? todayISO() : $("#hDate").value;
  quiet(loadHealth());
});
$("#hPrev").onclick = () => { healthDate = shiftDate(healthDate, -1); quiet(loadHealth()); };
$("#hNext").onclick = () => { if (healthDate < todayISO()) { healthDate = shiftDate(healthDate, 1); quiet(loadHealth()); } };
$("#hSyncBtn").onclick = () => quiet(run($("#hSyncBtn"), async () => renderHealthStatus((await api("/api/health/sync", {})).status)));
let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (!$("#page-health").hidden && healthData) renderHealth(); }, 150);
});

/* ---- vẽ biểu đồ (SVG thuần) */

const SVGNS = "http://www.w3.org/2000/svg";
function sv(tag, attrs, parent) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, v);
  parent?.append(el);
  return el;
}
const tip = document.createElement("div");
tip.className = "chart-tip";
tip.hidden = true;
document.body.append(tip);
/** Chú thích khi rê chuột / chọn bằng bàn phím: [[giá trị, nhãn, màu?], ...]; chữ chèn bằng textContent. */
function showTip(x, y, rows) {
  tip.textContent = "";
  for (const [value, label, color] of rows) {
    const row = document.createElement("div");
    if (color) { const key = document.createElement("i"); key.style.background = color; row.append(key); }
    const strong = document.createElement("strong");
    strong.textContent = value;
    row.append(strong);
    if (label) { const span = document.createElement("span"); span.textContent = label; row.append(span); }
    tip.append(row);
  }
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  tip.style.left = `${Math.min(window.innerWidth - r.width - 8, x + 14)}px`;
  tip.style.top = `${Math.max(8, Math.min(window.innerHeight - r.height - 8, y + 14))}px`;
}
const hideTip = () => (tip.hidden = true);
function hoverable(el, rows) {
  el.setAttribute("tabindex", "0");
  el.addEventListener("pointermove", (e) => showTip(e.clientX, e.clientY, rows()));
  el.addEventListener("pointerleave", hideTip);
  el.addEventListener("focus", () => { const b = el.getBoundingClientRect(); showTip(b.right, b.top, rows()); });
  el.addEventListener("blur", hideTip);
}

function chartBox(el, height, label) {
  el.textContent = "";
  const w = Math.max(260, Math.floor(el.clientWidth || 600));
  const svg = sv("svg", { viewBox: `0 0 ${w} ${height}`, width: w, height, role: "img", "aria-label": label }, el);
  return { svg, w, h: height };
}
function emptyChart(el, height, text) {
  const { svg, w } = chartBox(el, height, text);
  sv("text", { x: w / 2, y: height / 2, class: "empty-msg" }, svg).textContent = text;
}
function niceScale(maxValue, ticks = 3) {
  if (!(maxValue > 0)) return { max: 1, step: 1 };
  const raw = maxValue / ticks;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((v) => v >= raw);
  return { max: Math.ceil(maxValue / step) * step, step };
}
const compact = (v) => (v >= 10000 ? `${fmtInt(Math.round(v / 1000))}K` : fmtInt(v));
/** Cột: bo 4px ở đầu dữ liệu, vuông ở đáy. */
function colPath(x, y, w, h, r = 4) {
  r = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

/** Biểu đồ cột (một chuỗi, hoặc chồng nhiều phần). items: {key, label, parts: [{value, color}], tip: () => rows}. */
function columnChart(el, items, o) {
  const H = o.height || 150;
  const total = (it) => it.parts.reduce((a, p) => a + p.value, 0);
  const maxV = Math.max(0, ...items.map(total));
  if (!items.length || maxV <= 0) { emptyChart(el, H, o.empty); return; }
  const { svg, w } = chartBox(el, H, o.label);
  const padL = 40, padR = 4, padT = 8, padB = 22;
  const iw = w - padL - padR, ih = H - padT - padB;
  const { max, step } = niceScale(maxV, 3);
  for (let v = 0; v <= max + 1e-9; v += step) {
    const y = Math.round(padT + ih - (v / max) * ih) + 0.5;
    sv("line", { x1: padL, x2: w - padR, y1: y, y2: y, class: "grid" }, svg);
    sv("text", { x: padL - 6, y: y + 4, "text-anchor": "end", class: "axis" }, svg).textContent = (o.yFmt || compact)(v);
  }
  const slot = iw / items.length;
  const bw = Math.max(2, Math.min(24, slot - 2));
  const every = Math.max(1, Math.ceil(items.length / Math.max(2, Math.floor(iw / 46))));
  items.forEach((it, i) => {
    const g = sv("g", {}, svg);
    const sx = padL + i * slot;
    if (o.selected != null && it.key === o.selected) sv("rect", { x: sx, y: padT, width: slot, height: ih, class: "sel" }, g);
    const x = sx + (slot - bw) / 2;
    let y0 = padT + ih;
    const visible = it.parts.filter((p) => p.value > 0);
    visible.forEach((p, j) => {
      const h = (p.value / max) * ih;
      const gap = j > 0 ? 2 : 0;   // khe 2px giữa các phần chồng nhau
      const top = j === visible.length - 1;
      const y = y0 - h;
      const hh = Math.max(0, h - gap);
      if (hh > 0) sv("path", { d: top ? colPath(x, y, bw, hh) : `M${x},${y}h${bw}v${hh}h${-bw}Z`, class: "mark", style: `fill:${p.color}` }, g);
      y0 = y;
    });
    if (it.label && i % every === 0) {
      sv("text", { x: sx + slot / 2, y: H - 6, "text-anchor": "middle", class: "axis" }, svg).textContent = it.label;
    }
    const hit = sv("rect", { x: sx, y: padT, width: slot, height: ih, class: "hit" }, g);
    hoverable(hit, it.tip);
    if (o.onPick) hit.addEventListener("click", () => o.onPick(it.key));
  });
}

/** Đường theo thời gian trong ngày, có thước dọc theo con trỏ. points: [[ts, value]]. */
function lineChart(el, points, o) {
  const H = o.height || 170;
  if (!points.length) { emptyChart(el, H, o.empty); return; }
  const { svg, w } = chartBox(el, H, o.label);
  const padL = 40, padR = 8, padT = 10, padB = 22;
  const iw = w - padL - padR, ih = H - padT - padB;
  const vals = points.map((p) => p[1]).concat((o.dots || []).map((p) => p[1]));
  const lo = o.yMin ?? Math.max(0, Math.floor((Math.min(...vals) - 5) / 10) * 10);
  const { max: span, step } = niceScale(Math.max(...vals) - lo, 3);
  const hi = lo + span;
  const X = (ts) => padL + ((ts - o.t0) / (o.t1 - o.t0)) * iw;
  const Y = (v) => padT + ih - ((v - lo) / (hi - lo)) * ih;
  for (let v = lo; v <= hi + 1e-9; v += step) {
    const y = Math.round(Y(v)) + 0.5;
    sv("line", { x1: padL, x2: w - padR, y1: y, y2: y, class: "grid" }, svg);
    sv("text", { x: padL - 6, y: y + 4, "text-anchor": "end", class: "axis" }, svg).textContent = fmtInt(v);
  }
  for (let hr = 0; hr <= 24; hr += 6) {
    sv("text", { x: X(o.t0 + hr * 3600), y: H - 6, "text-anchor": hr === 0 ? "start" : hr === 24 ? "end" : "middle", class: "axis" }, svg).textContent = `${pad(hr % 24)}:00`;
  }
  let d = "";
  points.forEach(([ts, v], i) => {
    const gap = i === 0 || ts - points[i - 1][0] > (o.gap || 900);
    d += `${gap ? "M" : "L"}${X(ts).toFixed(1)},${Y(v).toFixed(1)}`;
  });
  sv("path", { d, fill: "none", style: `stroke:${o.color}`, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
  for (const [ts, v] of o.dots || []) {
    sv("circle", { cx: X(ts), cy: Y(v), r: 4, style: `fill:${o.color}`, stroke: "var(--surface)", "stroke-width": 2 }, svg);
  }
  const cross = sv("line", { y1: padT, y2: padT + ih, class: "crosshair", visibility: "hidden" }, svg);
  const dot = sv("circle", { r: 4, style: `fill:${o.color}`, stroke: "var(--surface)", "stroke-width": 2, visibility: "hidden" }, svg);
  const hit = sv("rect", { x: padL, y: padT, width: iw, height: ih, class: "hit" }, svg);
  const all = points.concat(o.dots || []).sort((a, b) => a[0] - b[0]);
  hit.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const ts = o.t0 + ((e.clientX - box.left - padL) / iw) * (o.t1 - o.t0);
    let best = all[0];
    for (const p of all) if (Math.abs(p[0] - ts) < Math.abs(best[0] - ts)) best = p;
    const x = X(best[0]);
    cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
    dot.setAttribute("cx", x); dot.setAttribute("cy", Y(best[1])); dot.setAttribute("visibility", "visible");
    showTip(e.clientX, e.clientY, [[`${best[1]} ${o.unit}`, hhmm(best[0]), o.color]]);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideTip(); });
}

/** Các giai đoạn của một giấc ngủ, mỗi giai đoạn một hàng. */
function sleepChart(el, sess) {
  const rowH = 18, rowGap = 6, padL = 74, padR = 8, padT = 4, padB = 22;
  const H = padT + STAGES.length * (rowH + rowGap) + padB;
  const { svg, w } = chartBox(el, H, t("Các giai đoạn giấc ngủ"));
  const iw = w - padL - padR;
  const X = (ts) => padL + ((ts - sess.start) / (sess.end - sess.start)) * iw;
  STAGES.forEach(([key, name], i) => {
    const y = padT + i * (rowH + rowGap);
    sv("line", { x1: padL, x2: w - padR, y1: y + rowH + rowGap / 2, y2: y + rowH + rowGap / 2, class: "grid" }, svg);
    sv("text", { x: padL - 8, y: y + rowH - 4, "text-anchor": "end", class: "axis" }, svg).textContent = name();
  });
  for (const [a, b, stage] of sess.stages) {
    const i = STAGES.findIndex((s) => s[0] === stage);
    const [, name, color] = STAGES[i];
    const x = X(a);
    const rect = sv("rect", { x, y: padT + i * (rowH + rowGap), width: Math.max(1.5, X(b) - x), height: rowH, rx: 2, class: "mark", style: `fill:${color}` }, svg);
    hoverable(rect, () => [[fmtMinutes((b - a) / 60), `${name()} · ${hhmm(a)}–${hhmm(b)}`, color]]);
  }
  const first = Math.ceil(sess.start / 3600) * 3600;
  sv("text", { x: padL, y: H - 6, class: "axis" }, svg).textContent = hhmm(sess.start);
  sv("text", { x: w - padR, y: H - 6, "text-anchor": "end", class: "axis" }, svg).textContent = hhmm(sess.end);
  const stepH = (sess.end - sess.start) > 6 * 3600 ? 2 : 1;
  for (let ts = first; ts < sess.end - 1800; ts += 3600 * stepH) {
    if (ts - sess.start < 1800) continue;
    sv("text", { x: X(ts), y: H - 6, "text-anchor": "middle", class: "axis" }, svg).textContent = hhmm(ts);
  }
}

function statsList(el, items) {
  el.textContent = "";
  for (const [label, value, unit] of items) {
    const div = document.createElement("div");
    const dt_ = document.createElement("dt");
    dt_.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    if (unit) { const small = document.createElement("small"); small.textContent = unit; dd.append(small); }
    div.append(dt_, dd);
    el.append(div);
  }
}
function tableRows(tbody, rows, emptyText, cols) {
  tbody.textContent = "";
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = cols;
    td.className = "none";
    td.textContent = emptyText;
    tr.append(td);
    tbody.append(tr);
    return;
  }
  for (const cells of rows) {
    const tr = document.createElement("tr");
    for (const c of cells) { const td = document.createElement("td"); td.textContent = c; tr.append(td); }
    tbody.append(tr);
  }
}
const pick = (date) => { healthDate = date; quiet(loadHealth()); };

function renderHealth() {
  const H = healthData;
  $("#hDate").value = healthDate;
  $("#hDate").max = todayISO();
  $("#hNext").disabled = healthDate >= todayISO();
  $("#hEmpty").hidden = !!H?.has_data;
  if (!H) {
    $$(".hgrid .chart").forEach((el) => emptyChart(el, 80, t("Chưa có dữ liệu")));
    return;
  }
  const day = H.day;
  const isToday = healthDate === todayISO();
  const dayLabel = isToday ? t("Hôm nay") : longDate(healthDate);
  const [t0] = [new Date(`${healthDate}T00:00:00`).getTime() / 1000];
  const t1 = t0 + 86400;

  // giấc ngủ
  const sl = day.sleep;
  $("#slTotal").textContent = sl ? fmtMinutes(sl.minutes) : "—";
  $("#slRange").textContent = sl ? t("{start} – {end}, thức dậy {day}", { start: hhmm(sl.start), end: hhmm(sl.end), day: dayLabel.toLowerCase() }) : t("Không có giấc ngủ kết thúc vào {day}.", { day: dayLabel.toLowerCase() });
  if (sl) sleepChart($("#slChart"), sl); else emptyChart($("#slChart"), 60, t("Chưa có dữ liệu giấc ngủ cho ngày này."));
  const legend = $("#slLegend");
  legend.textContent = "";
  for (const [key, name, color] of STAGES) {
    const li = document.createElement("li");
    const sw = document.createElement("i");
    sw.style.background = color;
    const b = document.createElement("b");
    b.textContent = sl ? fmtMinutes(sl[key]) : "—";
    li.append(sw, `${name()} `, b);
    legend.append(li);
  }
  columnChart($("#slHistory"), H.sleep_days.map((d) => ({
    key: d.date, label: shortDate(d.date),
    parts: [["deep", d.deep], ["light", d.light], ["rem", d.rem]].map(([k, v]) => ({ value: v / 60, color: stageInfo(k)[2] })),
    tip: () => [[fmtMinutes(d.minutes), longDate(d.date)], ...["deep", "light", "rem", "awake"].map((k) => [fmtMinutes(d[k]), stageInfo(k)[1](), stageInfo(k)[2]])],
  })), { height: 140, label: t("Thời gian ngủ 14 ngày gần đây"), empty: t("Chưa có dữ liệu giấc ngủ."), yFmt: (v) => `${v}h`, selected: healthDate, onPick: pick });

  // bước chân (hôm nay: số trực tiếp từ vòng tay mới hơn dữ liệu đã đồng bộ)
  const liveSteps = isToday && STATE.connected ? STATE.live?.activity?.steps : null;
  const steps = Math.max(day.steps, liveSteps ?? 0);
  $("#stTotal").textContent = fmtInt(steps);
  $("#stSub").textContent = dayLabel;
  columnChart($("#stHourly"), day.steps_hourly.map((v, h) => ({
    key: h, label: h % 3 === 0 ? `${pad(h)}h` : "", parts: [{ value: v, color: "var(--c-steps)" }],
    tip: () => [[t("{n} bước", { n: fmtInt(v) }), `${pad(h)}:00–${pad((h + 1) % 24)}:00`]],
  })), { height: 140, label: t("Bước chân theo giờ"), empty: t("Không có bước chân nào được ghi trong ngày này.") });
  const days = H.steps_days.slice();
  if (liveSteps != null) {
    const today = days.find((d) => d.date === healthDate);
    if (today) today.steps = Math.max(today.steps, liveSteps); else days.push({ date: healthDate, steps: liveSteps });
  }
  columnChart($("#stHistory"), days.map((d) => ({
    key: d.date, label: shortDate(d.date), parts: [{ value: d.steps, color: "var(--c-steps)" }],
    tip: () => [[t("{n} bước", { n: fmtInt(d.steps) }), longDate(d.date)]],
  })), { height: 150, label: t("Bước chân mỗi ngày"), empty: t("Chưa có lịch sử bước chân."), selected: healthDate, onPick: pick });
  tableRows($("#stTable"), days.slice().reverse().map((d) => [longDate(d.date), fmtInt(d.steps)]), t("Chưa có dữ liệu"), 2);

  // nhịp tim
  const hr = day.hr;
  $("#hrSub").textContent = dayLabel;
  if (hr.length) {
    const v = hr.map((p) => p[1]);
    statsList($("#hrStats"), [[t("Thấp nhất"), fmtInt(Math.min(...v)), t("nhịp/phút")], [t("Trung bình"), fmtInt(Math.round(v.reduce((a, b) => a + b, 0) / v.length)), t("nhịp/phút")], [t("Cao nhất"), fmtInt(Math.max(...v)), t("nhịp/phút")]]);
  } else statsList($("#hrStats"), []);
  lineChart($("#hrChart"), hr, { t0, t1, color: "var(--c-hr)", unit: t("nhịp/phút"), label: t("Nhịp tim trong ngày"), empty: t("Không có số đo nhịp tim trong ngày này.") });

  // căng thẳng
  const autoS = day.stress.filter((s) => s[2]).map((s) => [s[0], s[1]]);
  const manualS = day.stress.filter((s) => !s[2]).map((s) => [s[0], s[1]]);
  $("#ssSub").textContent = dayLabel;
  const sv_ = day.stress.map((s) => s[1]);
  if (sv_.length) {
    const avg = Math.round(sv_.reduce((a, b) => a + b, 0) / sv_.length);
    statsList($("#ssStats"), [[t("Trung bình"), String(avg), stressLabel(avg)], [t("Cao nhất"), String(Math.max(...sv_)), ""]]);
  } else statsList($("#ssStats"), []);
  lineChart($("#ssChart"), autoS, { t0, t1, yMin: 0, color: "var(--c-stress)", unit: "", dots: manualS, gap: 1800, label: t("Mức căng thẳng trong ngày"), empty: manualS.length ? t("Chỉ có lần đo tay.") : t("Không có số đo căng thẳng. Bật Theo dõi căng thẳng trong Cài đặt → Sức khỏe.") });

  // PAI
  const pai = H.pai;
  if (pai.latest) statsList($("#paiStats"), [[t("Tổng 7 ngày"), fmtInt(Math.round(pai.latest.total)), ""], [t("Thêm hôm đó"), `+${fmtInt(Math.round(pai.latest.today))}`, ""]]);
  else statsList($("#paiStats"), []);
  columnChart($("#paiChart"), pai.days.map((d) => ({
    key: d.date, label: shortDate(d.date), parts: [{ value: d.total, color: "var(--c-pai)" }],
    tip: () => [[`${fmtInt(Math.round(d.total))} PAI`, longDate(d.date)], [`+${fmtInt(Math.round(d.today))}`, t("trong ngày")]],
  })), { height: 140, label: t("PAI các ngày gần đây"), empty: t("Chưa có dữ liệu PAI.") });

  // SpO2
  const sp = H.spo2_recent;
  if (sp.length) statsList($("#spStats"), [[t("Lần đo gần nhất · {when}", { when: dateTime(sp[0][0]) }), String(sp[0][1]), "%"]]);
  else statsList($("#spStats"), []);
  tableRows($("#spTable"), sp.map(([ts, v, auto]) => [dateTime(ts), `${v}%`, auto ? t("Tự động") : t("Đo tay")]), t("Chưa có lần đo SpO2 nào. Đo trên vòng tay rồi đồng bộ lại."), 3);

  // tập luyện
  tableRows($("#woTable"), H.workouts.map((w) => [
    sportName(w.type), dateTime(w.start), fmtMinutes(((w.active_seconds || (w.end - w.start)) / 60)),
    w.distance ? `${fmtDec(w.distance / 1000)} km` : "—", w.calories ? `${fmtInt(w.calories)} kcal` : "—",
    w.avg_hr ? t("{n} nhịp/phút", { n: w.avg_hr }) : "—", w.steps ? fmtInt(w.steps) : "—",
  ]), t("Chưa có buổi tập nào."), 7);

  // đo tự động
  const s = STATE.settings || {};
  const facts = $("#measureFacts");
  facts.textContent = "";
  const unknown = t("Chưa đồng bộ");
  for (const [k, v] of [
    [t("Nhịp tim"), s.hr_interval == null ? unknown : s.hr_interval === 0 ? t("Tắt") : s.hr_interval === 1 ? t("Mỗi phút") : t("Mỗi {m} phút", { m: s.hr_interval })],
    [t("Căng thẳng"), s.stress == null ? unknown : s.stress ? t("Bật") : t("Tắt")],
    ["SpO2", t("Đo trên vòng tay")],
  ]) {
    const dt_ = document.createElement("dt");
    dt_.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = v;
    facts.append(dt_, dd);
  }
}

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
