"use strict";

/* Quản lý Mi Band 6 — giao diện web.
   Server trên máy tính giữ kết nối Bluetooth; trang này gọi REST API và nhận sự kiện qua WebSocket.
   Ngôn ngữ: chuỗi tiếng Việt là bản gốc; tiếng Anh lấy từ /static/i18n/en.json. */

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const pad = (n) => String(n).padStart(2, "0");
const DAY_BITS = [1, 2, 4, 8, 16, 32, 64];

/* ============================================================ ngôn ngữ */

let LANG = (() => {
  try {
    const saved = localStorage.getItem("mb6_lang");
    if (saved === "vi" || saved === "en") return saved;
  } catch { /* trình duyệt chặn localStorage */ }
  return (navigator.language || "vi").toLowerCase().startsWith("vi") ? "vi" : "en";
})();
let LOCALE = LANG === "en" ? "en-US" : "vi-VN";
let CATALOG = {};
let REVERSE = null;            // bản dịch tiếng Anh -> chuỗi gốc tiếng Việt (để đổi ngược về tiếng Việt)
const TITLE = document.title;  // tiêu đề gốc (tiếng Việt) trong index.html
const DOM_SRC = new WeakMap(); // nút chữ / phần tử -> {khóa: [chuỗi gốc, chuỗi đang hiện]}

/** Dịch một chuỗi gốc tiếng Việt; {tên} được thay bằng vars.tên. */
function t(source, vars) {
  let out = LANG === "en" ? CATALOG[source] ?? source : source;
  if (vars) out = out.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ""));
  return out;
}

/** Chuỗi gốc tiếng Việt của một đoạn chữ đang hiện (bằng ngôn ngữ nào cũng được), hoặc null nếu không phải chuỗi dịch. */
function sourceOf(text, remembered) {
  if (remembered && remembered[1] === text) return remembered[0];   // chính chuỗi ta đã đặt lần trước
  if (text in CATALOG) return text;
  REVERSE ||= Object.fromEntries(Object.entries(CATALOG).map(([vi, en]) => [en, vi]));
  return REVERSE[text] ?? null;
}

function translateText(holder, slot, text, apply) {
  const memo = DOM_SRC.get(holder) || {};
  const src = sourceOf(text, memo[slot]);
  if (src == null) return;
  const out = t(src);
  if (out !== text) apply(out);
  memo[slot] = [src, out];
  DOM_SRC.set(holder, memo);
}

/** Dịch chữ trong trang (nút, nhãn, placeholder…) sang ngôn ngữ đang chọn, theo cả hai chiều: lúc mở trang và
    mỗi lần đổi ngôn ngữ, không tải lại trang. Phần chữ có số liệu được vẽ lại bằng rerenderLanguage(). */
function translateDom() {
  document.documentElement.lang = LANG;
  document.title = t(TITLE);
  if (LANG === "vi" && !Object.keys(CATALOG).length) return;   // trang gốc đã là tiếng Việt
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
    translateText(node, "text", raw.trim().replace(/\s+/g, " "), (out) => { node.nodeValue = raw.replace(raw.trim(), () => out); });
  }
  $$("[data-i18n-value]").forEach((el) => translateText(el, "value", el.value, (out) => { el.value = out; }));
  for (const attr of ["placeholder", "aria-label", "title", "data-empty"]) {
    $$(`[${attr}]`).forEach((el) => translateText(el, attr, el.getAttribute(attr), (out) => el.setAttribute(attr, out)));
  }
}

let catalogLoad = null;
function ensureCatalog() {
  catalogLoad ||= fetch("/static/i18n/en.json", { cache: "no-cache" })
    .then((r) => r.json())
    .then((c) => { CATALOG = c; REVERSE = null; })
    .catch(() => { catalogLoad = null; });
  return catalogLoad;
}

async function loadLanguage() {
  if (LANG === "en") await ensureCatalog();
  translateDom();
  $$(".lang button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === LANG)));
  document.documentElement.classList.remove("i18n-pending");
  if (LANG === "vi") setTimeout(ensureCatalog, 1500);   // tải sẵn để đổi sang tiếng Anh tức thì
}

/** Đổi ngôn ngữ tại chỗ: thay chữ đang hiện, vẽ lại phần có số liệu; không tải lại trang. */
async function setLanguage(lang) {
  if (lang === LANG || (lang !== "vi" && lang !== "en")) return;
  await ensureCatalog();
  LANG = lang;
  LOCALE = lang === "en" ? "en-US" : "vi-VN";
  try { localStorage.setItem("mb6_lang", lang); } catch { /* bỏ qua */ }
  translateDom();
  $$(".lang button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === LANG)));
  rerenderLanguage();
  try { await api("/api/prefs", { lang }); } catch { /* server vẫn dùng ngôn ngữ cũ cho thông báo */ }
  // phần phân tích sức khỏe do server viết theo ngôn ngữ đã chọn: lấy lại khi trang đang mở
  if (LANG === lang && healthData && !$("#page-health").hidden) quiet(loadHealth());
}

$$(".lang button").forEach((b) => b.addEventListener("click", () => setLanguage(b.dataset.lang)));

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
const SUBS = ["profile", "display", "face", "apps", "health"];

function route() {
  const [page0, sub0] = (location.hash.slice(1) || "").split("/");
  const page = PAGES.includes(page0) ? page0 : STATE.connected ? "overview" : "device";
  $$(".page").forEach((p) => (p.hidden = p.id !== `page-${page}`));
  $$(".nav a").forEach((a) => a.setAttribute("aria-current", a.getAttribute("href") === `#${page}` ? "page" : "false"));
  if (page === "settings") {
    const sub = SUBS.includes(sub0) ? sub0 : "profile";
    $$(".subtabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.sub === sub)));
    $$(".subpage").forEach((s) => (s.hidden = s.id !== `sub-${sub}`));
    if (sub === "face") requestAnimationFrame(() => (WP.img ? wpDraw() : drawSim()));
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

/** Giờ như vòng tay hiện: theo kiểu 12/24 giờ đã lưu (mặc định 24 giờ). */
function bandClock(now = new Date()) {
  const h = now.getHours();
  const h12 = STATE.settings?.time_24h === false;
  return `${h12 ? (h % 12) || 12 : pad(h)}:${pad(now.getMinutes())}`;
}

/** Mặt đồng hồ mặc định của ứng dụng (khi chưa có ảnh mặt đồng hồ thật): giờ, ngày, nhịp tim, bước, pin. */
function drawBand() {
  const now = new Date();
  $("#dateLine").textContent = new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long" }).format(now);
  $("#bTime").textContent = bandClock(now);
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
  if (SIM.source === "default" && !$("#sub-face").hidden) drawSim();
}

/** Mặt mặc định vẽ lên khung mô phỏng 152 × 486 (cùng bố cục với hình ở trang Tổng quan). */
function drawDefaultFace(g) {
  const now = new Date();
  const css = getComputedStyle(document.documentElement);
  const color = (v) => css.getPropertyValue(v).trim();
  const font = (w, px) => `${w} ${px}px "Be Vietnam Pro", -apple-system, sans-serif`;
  g.textAlign = "center";
  g.textBaseline = "alphabetic";
  g.fillStyle = "#fff";
  g.font = font(700, 52);
  g.fillText(bandClock(now), 76, 128);
  g.fillStyle = "#8e9b97";
  g.font = font(500, 17);
  g.fillText(`${weekdays()[(now.getDay() + 6) % 7]}  ${pad(now.getDate())}/${pad(now.getMonth() + 1)}`, 76, 160);
  g.fillStyle = color("--coral");
  g.font = font(700, 30);
  g.fillText(`♥ ${live.hr || "--"}`, 76, 228);
  const goal = Number(STATE.profile?.goal || 8000);
  const frac = live.steps == null ? 0 : Math.min(1, live.steps / goal);
  g.lineWidth = 9;
  g.lineCap = "round";
  g.strokeStyle = "#222826";
  g.beginPath();
  g.arc(76, 310, 42, 0, Math.PI * 2);
  g.stroke();
  if (frac > 0) {
    g.strokeStyle = color("--amber");
    g.beginPath();
    g.arc(76, 310, 42, -Math.PI / 2, -Math.PI / 2 + frac * Math.PI * 2);
    g.stroke();
  }
  g.fillStyle = color("--amber");
  g.font = font(700, (live.steps ?? 0) >= 10000 ? 17 : 21);
  g.fillText(live.steps == null ? "--" : fmtInt(live.steps), 76, 318);
  if (live.battery != null) {
    g.fillStyle = "#8e9b97";
    g.font = font(500, 17);
    g.fillText(`${live.battery}%${live.charging ? " ⚡" : ""}`, 76, 392);
    g.strokeStyle = "#5c6763";
    g.lineWidth = 2;
    g.strokeRect(46, 404, 56, 19);
    g.fillStyle = "#5c6763";
    g.fillRect(103, 410, 4, 7);
    g.fillStyle = live.battery <= 20 ? color("--coral") : color("--mint");
    g.fillRect(50, 408, (48 * Math.max(0, Math.min(100, live.battery))) / 100, 11);
  }
}

/** Mặt đồng hồ trên hình vòng tay: ảnh xem trước thật (của mặt đã cài hoặc ảnh người dùng chọn). */
function renderWatchface(info) {
  const img = $("#wfImage");
  const has = !!info?.preview;
  if (has) img.setAttribute("href", `/api/watchface/preview?v=${info.version || 0}`);
  else img.removeAttribute("href");
  img.style.display = has ? "" : "none";
  $("#bandDefault").style.display = has ? "none" : "";
  $("#wfEmpty").hidden = has;
  let current = t("Chưa cài mặt đồng hồ nào qua ứng dụng");
  if (info?.name) {
    const when = new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(info.installed * 1000));
    current = t("Cài gần nhất qua ứng dụng: {name}, {when}", { name: info.name, when });
  } else if (has) {
    current = t("Mặt đồng hồ có sẵn (đã đặt ảnh xem trước)");
  }
  $("#faceCurrent").textContent = current;
  loadCurrentFace(info);
  faceButtons();
}
setInterval(drawBand, 15000);

/** Nhịp tim các lần đo gần nhất (trang Tổng quan): trục số, giờ đo, giá trị mới nhất. */
function drawSpark() {
  const pts = live.hrHistory;
  const el = $("#hrLive");
  if (pts.length < 2) {
    emptyChart(el, 72, pts.length ? t("Đang chờ thêm số đo…") : t("Bấm Đo ngay hoặc Theo dõi liên tục để xem nhịp tim."));
    return;
  }
  const t0 = pts[0][0];
  const t1 = Math.max(pts[pts.length - 1][0], t0 + 30);
  const hms = (ts) => { const d = new Date(ts * 1000); return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`; };
  const v = pts.map((p) => p[1]);
  lineChart(el, pts, {
    t0, t1, color: "var(--c-hr)", unit: t("nhịp/phút"), height: 150, last: true, gap: 120, timeFmt: hms,
    yMin: Math.max(30, Math.floor((Math.min(...v) - 8) / 10) * 10), xTicks: [[t0, hms(t0)], [t1, hms(t1)]],
    label: t("Nhịp tim các lần đo gần nhất"),
  });
  $("#hrRange").textContent = t("Thấp nhất {lo} · cao nhất {hi} nhịp/phút trong {n} lần đo", { lo: Math.min(...v), hi: Math.max(...v), n: v.length });
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
      live.hrHistory.push([Date.now() / 1000, d]);
      if (live.hrHistory.length > 120) live.hrHistory.shift();
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
const hrIntervalLabel = (m) => (m === 0 ? t("Tắt") : m === 1 ? t("Mỗi phút") : t("Mỗi {m} phút", { m }));
const hrThresholdLabel = (v) => t("{v} nhịp/phút", { v });

/** Đổi nhãn các lựa chọn có số (đổi ngôn ngữ), giữ nguyên lựa chọn đang chọn. */
function relabelOptions(sel, label) {
  for (const o of sel.options) if (o.value !== "") o.textContent = label(Number(o.value));
}

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
  fillSelectKnown($("#hInterval"), META.hr_intervals.map((m) => [m, hrIntervalLabel(m)]), hrKnown ? s.hr_interval : null);
  fillSelectKnown($("#hThreshold"), META.hr_thresholds.map((v) => [v, hrThresholdLabel(v)]), hrKnown ? b(s.hr_threshold, 120) : null);
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

/* ============================================================ mặt đồng hồ: mô phỏng, ảnh nền, tệp .bin */

/* Mi Band 6 không cho đọc mặt đồng hồ đang hiện. Khung mô phỏng hiện: ảnh đang chỉnh, ảnh xem trước trong
   tệp .bin vừa chọn, hoặc mặt đồng hồ đã cài qua ứng dụng. Mọi ảnh gửi đi đều là ảnh 152 × 486 vẽ lại từ
   khung mô phỏng, nên ảnh gốc lớn đến đâu cũng được tự thu nhỏ. */

const readBase64 = (file) => new Promise((resolve, reject) => {
  const r = new FileReader();
  r.onload = () => resolve(String(r.result).split(",")[1] || "");
  r.onerror = () => reject(r.error);
  r.readAsDataURL(file);
});
const loadImage = (src) => new Promise((resolve, reject) => {
  const img = new Image();
  img.onload = () => resolve(img);
  img.onerror = () => reject(new Error(t("Không mở được ảnh này. Chọn ảnh PNG hoặc JPEG.")));
  img.src = src;
});

const WP = { W: 152, H: 486, R: 76, img: null, base: 1, scale: 1, ox: 0, oy: 0, k: 1 };
const SIM = { source: null, binB64: null, binName: "", binPreview: null, current: null, currentKey: null };
const DIGIT_W = 44;
const DIGIT_H = 64;
const DIGIT_X = (152 - 2 * DIGIT_W) / 2;
const WP_ROWS = { top: 40, middle: 177, bottom: 314 };
let wpDigits = null;
let wpDigitsColor = "";
let wpDrag = null;

const faceMode = () => radio("faceMode") || "photo";

function renderWatchfaceProgress(d) {
  const pct = d.total ? Math.round((d.sent / d.total) * 100) : 0;
  $("#wfProgressRow").hidden = false;
  $("#wfBar").style.width = `${pct}%`;
  $("#wfPct").textContent = `${pct}%`;
}

/** Ảnh của mặt đồng hồ đã cài qua ứng dụng (hoặc ảnh xem trước tự đặt), hiện khi chưa chọn gì mới. */
function loadCurrentFace(info) {
  const key = info?.preview ? String(info.version || 0) : "";
  if (key === SIM.currentKey) return;
  SIM.currentKey = key;
  SIM.current = null;
  if (key) loadImage(`/api/watchface/preview?v=${key}`).then((img) => { SIM.current = img; drawSim(); }).catch(() => {});
  drawSim();
}

function drawCover(g, img) {
  const s = Math.max(WP.W / img.width, WP.H / img.height);
  g.drawImage(img, (WP.W - img.width * s) / 2, (WP.H - img.height * s) / 2, img.width * s, img.height * s);
}

function drawSim() {
  const g = $("#simScreen").getContext("2d");
  g.fillStyle = "#000";
  g.fillRect(0, 0, WP.W, WP.H);
  let source = null;
  if (faceMode() === "photo" && WP.img) {
    wpBackground(g);
    wpDrawTime(g);
    source = "photo";
  } else if (faceMode() === "bin" && SIM.binPreview) {
    drawCover(g, SIM.binPreview);
    source = "bin";
  } else if (SIM.current) {
    drawCover(g, SIM.current);
    source = "current";
  } else {
    drawDefaultFace(g);
    source = "default";
  }
  SIM.source = source;
  $("#simEmpty").hidden = true;
  $("#simCaption").textContent = ({
    photo: () => t("Mô phỏng ảnh nền của bạn trên Mi Band 6"),
    bin: () => t("Mô phỏng: ảnh xem trước trong tệp .bin"),
    current: () => t("Mặt đồng hồ đã cài qua ứng dụng"),
    default: () => t("Mặt mặc định của ứng dụng (chưa chọn ảnh)"),
  }[source])();
  faceButtons();
}

function faceButtons() {
  // ảnh nền: cài lên vòng tay đang tắt (vòng tay treo với mặt đồng hồ ứng dụng tạo), chỉ đặt làm ảnh xem trước
  const ready = faceMode() === "photo" ? false : !!SIM.binB64;
  $("#faceInstallBtn").disabled = !ready || !STATE.connected;
  $("#facePreviewBtn").disabled = !(SIM.source === "photo" || SIM.source === "bin");
  $("#wfClearBtn").disabled = !STATE.watchface?.preview;
}

$$('input[name="faceMode"]').forEach((el) => el.addEventListener("change", () => {
  $("#modePhoto").hidden = faceMode() !== "photo";
  $("#modeBin").hidden = faceMode() !== "bin";
  if (faceMode() === "photo" && WP.img) wpDraw(); else drawSim();
}));

/* ---- ảnh của bạn: cắt, phóng to, vị trí giờ */

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
/** Vị trí hàng giờ và hàng phút (góc trên trái), hoặc null nếu ẩn giờ. */
function wpTimeRows() {
  const pos = radio("wpTime");
  if (!WP_ROWS[pos]) return null;
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
function wpBackground(g) {
  g.fillStyle = "#000";
  g.fillRect(0, 0, WP.W, WP.H);
  g.imageSmoothingQuality = "high";
  g.drawImage(WP.img, WP.ox, WP.oy, WP.img.width * WP.scale, WP.img.height * WP.scale);
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
  WP.ox = WP.W / 2 - ((WP.W / 2 - WP.ox) * s2) / s1;   // giữ nguyên điểm giữa màn hình
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
/** Khung chỉnh (cả ảnh, phần bị cắt tối đi) rồi khung mô phỏng. */
function wpDraw() {
  if (!WP.img) return;
  const stage = $("#wpStage");
  const box = stage.getBoundingClientRect();
  if (box.width && box.height) {
    const dpr = window.devicePixelRatio || 1;
    stage.width = Math.round(box.width * dpr);
    stage.height = Math.round(box.height * dpr);
    const g = stage.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, box.width, box.height);
    const k = (WP.k = Math.min(0.8, (box.height - 24) / WP.H, (box.width - 24) / WP.W));
    const wx = (box.width - WP.W * k) / 2;
    const wy = (box.height - WP.H * k) / 2;
    g.imageSmoothingQuality = "high";
    g.drawImage(WP.img, wx + WP.ox * k, wy + WP.oy * k, WP.img.width * WP.scale * k, WP.img.height * WP.scale * k);
    g.beginPath();
    g.rect(0, 0, box.width, box.height);
    wpScreenPath(g, wx, wy, k);
    g.fillStyle = "rgba(8, 11, 10, .72)";
    g.fill("evenodd");
    g.beginPath();
    wpScreenPath(g, wx, wy, k);
    g.strokeStyle = "rgba(255, 255, 255, .6)";
    g.lineWidth = 1;
    g.stroke();
  }
  drawSim();
}

$("#wpPickBtn").onclick = () => $("#wpFile").click();
$("#wpFile").onchange = async () => {
  const file = $("#wpFile").files[0];
  if (!file) return;
  try {
    const img = await loadImage(URL.createObjectURL(file));
    WP.img = img;
    $("#wpName").textContent = `${file.name} · ${img.width} × ${img.height}`;
    $("#wpName").classList.add("chosen");
    $("#wpAdjust").hidden = false;
    await wpMakeDigits();
    wpReset();
  } catch (e) {
    toast(e.message, true);
  }
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
window.addEventListener("resize", () => { if (WP.img && !$("#sub-face").hidden) wpDraw(); });
setInterval(() => { if (WP.img && !$("#sub-face").hidden) wpDraw(); }, 30000);   // giờ trong mô phỏng chạy theo đồng hồ

/* ---- tệp .bin */

$("#wfPickBtn").onclick = () => $("#wfFile").click();
$("#wfFile").onchange = async () => {
  const file = $("#wfFile").files[0];
  if (!file) return;
  SIM.binB64 = null;
  SIM.binPreview = null;
  $("#wfInfo").hidden = true;
  try {
    const b64 = await readBase64(file);
    const r = await api("/api/watchface/inspect", { file: b64 });
    SIM.binB64 = b64;
    SIM.binName = file.name;
    $("#wfName").textContent = `${file.name} · ${fmtInt(Math.round(r.size / 1024))} KB`;
    $("#wfName").classList.add("chosen");
    if (r.preview) SIM.binPreview = await loadImage(r.preview);
    $("#wfInfo").textContent = r.preview ? t("Đã đọc ảnh xem trước trong tệp.") : t("Không đọc được ảnh xem trước trong tệp này (ảnh nén); tệp vẫn cài được.");
    $("#wfInfo").hidden = false;
  } catch (e) {
    $("#wfName").textContent = t("Chưa chọn tệp");
    $("#wfName").classList.remove("chosen");
    toast(e.message, true);
  }
  drawSim();
};

/* ---- cài lên vòng tay / chỉ đặt ảnh xem trước */

const bytesToBase64 = (u8) => {
  let s = "";
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
};
const rgbaOf = (canvas) => ({
  w: canvas.width, h: canvas.height,
  rgba: bytesToBase64(new Uint8Array(canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data.buffer)),
});
function wallpaperPayload() {
  wpDraw();
  const bg = document.createElement("canvas");
  bg.width = WP.W;
  bg.height = WP.H;
  wpBackground(bg.getContext("2d"));
  const pv = document.createElement("canvas");   // ảnh nhỏ để chọn mặt đồng hồ trên vòng tay
  pv.width = WP.W / 2;
  pv.height = Math.round(WP.H / 2);
  pv.getContext("2d").drawImage($("#simScreen"), 0, 0, pv.width, pv.height);
  const rows = wpTimeRows();
  return {
    background: rgbaOf(bg), preview: rgbaOf(pv), image: $("#simScreen").toDataURL("image/png"),
    digits: rows ? wpDigits.map(rgbaOf) : [], hours: rows ? rows[0] : null, minutes: rows ? rows[1] : null,
  };
}

$("#faceInstallBtn").onclick = () => quiet(run($("#faceInstallBtn"), async () => {
  renderWatchfaceProgress({ sent: 0, total: 1 });
  try {
    const r = faceMode() === "photo"
      ? await api("/api/wallpaper", wallpaperPayload())
      : await api("/api/watchface", { name: SIM.binName, file: SIM.binB64, preview: SIM.binPreview ? $("#simScreen").toDataURL("image/png") : null });
    applyState(r.state);
    return r;
  } finally {
    $("#wfProgressRow").hidden = true;
    faceButtons();
  }
}));
$("#facePreviewBtn").onclick = () => quiet(run($("#facePreviewBtn"), async () => {
  drawSim();
  applyState((await api("/api/watchface/preview", { image: $("#simScreen").toDataURL("image/png") })).state);
}, t("Đã đặt ảnh xem trước.")).finally(faceButtons));
$("#wfClearBtn").onclick = () => quiet(run($("#wfClearBtn"), async () => {
  applyState((await api("/api/watchface/preview", { image: null })).state);
}, t("Đã bỏ ảnh xem trước.")).finally(faceButtons));

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

/** Mã loại bài tập của Mi Fitness (khác mã vòng tay); chỉ các mã đã kiểm chứng (dự án mifit). */
const mfSportName = (k) => ({ 1: t("Chạy bộ"), 6: t("Đạp xe"), 300: t("Máy leo cầu thang"), 308: t("Tập sức mạnh") })[k];
const workoutName = (w) => (w.type != null ? sportName(w.type) : mfSportName(w.mf_type) ?? t("Bài tập (mã Mi Fitness {k})", { k: w.mf_type ?? "?" }));
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

/* ---- chọn ngày */

let calMonth = null;   // ngày đầu của tháng đang xem trong lịch
const isoOf = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
function goToDate(iso) {
  healthDate = iso > todayISO() ? todayISO() : iso;
  closeCal();
  quiet(loadHealth());
}
function renderDateNav() {
  const today = todayISO();
  const d = new Date(`${healthDate}T12:00:00`);
  $("#hDateMain").textContent = healthDate === today ? t("Hôm nay") : healthDate === shiftDate(today, -1) ? t("Hôm qua")
    : new Intl.DateTimeFormat(LOCALE, { weekday: "long" }).format(d);
  $("#hDateSub").textContent = new Intl.DateTimeFormat(LOCALE, { weekday: healthDate >= shiftDate(today, -1) ? "long" : undefined, day: "numeric", month: "long", year: "numeric" }).format(d);
  $("#hNext").disabled = healthDate >= today;
}
function daysWithData() {
  const set = new Set();
  for (const d of healthData?.steps_days || []) if (d.steps > 0) set.add(d.date);
  for (const d of healthData?.sleep_days || []) if (d.minutes) set.add(d.date);
  return set;
}
function renderCal() {
  const grid = $("#calGrid");
  grid.textContent = "";
  $("#calTitle").textContent = new Intl.DateTimeFormat(LOCALE, { month: "long", year: "numeric" }).format(calMonth);
  for (const name of weekdays()) {
    const el = document.createElement("span");
    el.className = "cal-dow";
    el.textContent = name;
    grid.append(el);
  }
  const lead = (calMonth.getDay() + 6) % 7;   // tuần bắt đầu từ thứ Hai
  for (let i = 0; i < lead; i++) grid.append(document.createElement("span"));
  const today = todayISO();
  const has = daysWithData();
  const d = new Date(calMonth);
  while (d.getMonth() === calMonth.getMonth()) {
    const iso = isoOf(d);
    const b = document.createElement("button");
    b.type = "button";
    b.className = "cal-day";
    b.textContent = String(d.getDate());
    b.disabled = iso > today;
    b.classList.toggle("today", iso === today);
    b.classList.toggle("has", has.has(iso));
    b.setAttribute("aria-selected", String(iso === healthDate));
    b.setAttribute("aria-label", new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long" }).format(d));
    b.onclick = () => goToDate(iso);
    grid.append(b);
    d.setDate(d.getDate() + 1);
  }
  const now = new Date();
  $("#calNextM").disabled = calMonth.getFullYear() === now.getFullYear() && calMonth.getMonth() === now.getMonth();
}
function openCal() {
  const d = new Date(`${healthDate}T12:00:00`);
  calMonth = new Date(d.getFullYear(), d.getMonth(), 1);
  renderCal();
  $("#calPop").hidden = false;
  $("#hDateBtn").setAttribute("aria-expanded", "true");
  ($("#calGrid .cal-day[aria-selected=true]") || $("#calToday")).focus();
}
function closeCal() {
  if ($("#calPop").hidden) return;
  $("#calPop").hidden = true;
  $("#hDateBtn").setAttribute("aria-expanded", "false");
}
$("#hDateBtn").onclick = () => ($("#calPop").hidden ? openCal() : closeCal());
$("#calPrevM").onclick = () => { calMonth = new Date(calMonth.getFullYear(), calMonth.getMonth() - 1, 1); renderCal(); };
$("#calNextM").onclick = () => { calMonth = new Date(calMonth.getFullYear(), calMonth.getMonth() + 1, 1); renderCal(); };
$("#calToday").onclick = () => goToDate(todayISO());
$("#calYesterday").onclick = () => goToDate(shiftDate(todayISO(), -1));
document.addEventListener("pointerdown", (e) => { if (!e.target.closest(".day-nav")) closeCal(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#calPop").hidden) { closeCal(); $("#hDateBtn").focus(); }
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
function svText(parent, x, y, text, cls = "axis", anchor = "start") {
  const el = sv("text", { x, y, class: cls, "text-anchor": anchor }, parent);
  el.textContent = text;
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
  const w = Math.max(240, Math.floor(el.clientWidth || 600));
  const svg = sv("svg", { viewBox: `0 0 ${w} ${height}`, width: w, height, role: "img", "aria-label": label }, el);
  return { svg, w, h: height };
}
function emptyChart(el, height, text) {
  const { svg, w } = chartBox(el, height, text);
  svText(svg, w / 2, height / 2 + 4, text, "empty-msg", "middle");
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
/** Đường mốc ngang (mục tiêu, trung bình); nhãn hai dòng nằm ở lề phải, ngoài vùng cột. */
function refLine(svg, x0, x1, y, name, value) {
  sv("line", { x1: x0, x2: x1 + 4, y1: y, y2: y, class: "ref" }, svg);
  svText(svg, x1 + 8, y - 2, name, "ref-name");
  svText(svg, x1 + 8, y + 11, value, "ref-label");
}

/** Biểu đồ cột (một chuỗi, hoặc chồng nhiều phần).
    items: {key, label, parts: [{value, color}], tip: () => rows}; o: height, label, empty, yFmt, selected, onPick,
    refs: [{value, name, text}], band: {from, to, label}, valueFmt (nhãn số trên cột được chọn / cao nhất). */
function columnChart(el, items, o) {
  const H = o.height || 190;
  const total = (it) => it.parts.reduce((a, p) => a + p.value, 0);
  const maxV = Math.max(0, ...items.map(total), ...(o.refs || []).map((r) => r.value * 1.08), o.band ? o.band.to * 1.05 : 0);
  if (!items.length || items.every((it) => total(it) <= 0)) { emptyChart(el, Math.min(H, 120), o.empty); return; }
  const { svg, w } = chartBox(el, H, o.label);
  const padL = 44, padR = o.refs?.length ? 92 : 8, padT = 18, padB = 26;
  const iw = w - padL - padR, ih = H - padT - padB;
  const { max, step } = niceScale(maxV, 4);
  const Y = (v) => padT + ih - (v / max) * ih;
  if (o.band) {
    sv("rect", { x: padL, y: Y(o.band.to), width: iw, height: Y(o.band.from) - Y(o.band.to), class: "band" }, svg);
    // nhãn của vùng khuyến nghị nằm phía trên biểu đồ (chú giải), không bị cột che
    sv("rect", { x: padL, y: 2, width: 12, height: 10, rx: 2, class: "band band-key" }, svg);
    svText(svg, padL + 18, 11, o.band.label, "band-label");
  }
  for (let v = 0; v <= max + 1e-9; v += step) {
    const y = Math.round(Y(v)) + 0.5;
    sv("line", { x1: padL, x2: w - padR, y1: y, y2: y, class: v === 0 ? "baseline" : "grid" }, svg);
    svText(svg, padL - 8, y + 4, (o.yFmt || compact)(v), "axis", "end");
  }
  const slot = iw / items.length;
  const bw = Math.max(3, Math.min(24, slot * 0.62));
  const every = Math.max(1, Math.ceil(items.length / Math.max(2, Math.floor(iw / 52))));
  const highest = items.reduce((a, it) => (total(it) > total(a) ? it : a), items[0]);
  items.forEach((it, i) => {
    const g = sv("g", {}, svg);
    const sx = padL + i * slot;
    const isSel = o.selected != null && it.key === o.selected;
    if (isSel) sv("rect", { x: sx, y: padT, width: slot, height: ih, class: "sel" }, g);
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
    if (o.valueFmt && total(it) > 0 && (isSel || (it === highest && !o.refs?.length))) {
      svText(g, sx + slot / 2, Math.max(12, y0 - 6), o.valueFmt(total(it)), "value-label", "middle");
    }
    if (it.label && (i % every === 0 || isSel)) svText(svg, sx + slot / 2, H - 8, it.label, isSel ? "axis strong" : "axis", "middle");
    const hit = sv("rect", { x: sx, y: padT, width: slot, height: ih, class: "hit" }, g);
    hoverable(hit, it.tip);
    if (o.onPick) hit.addEventListener("click", () => o.onPick(it.key));
  });
  for (const r of o.refs || []) refLine(svg, padL, w - padR, Math.round(Y(r.value)) + 0.5, r.name, r.text);
}

/** Đường theo thời gian, có vùng tô nhạt, thước dọc theo con trỏ.
    points: [[ts, value]]; o: t0, t1, color, unit, label, empty, height, yMin, yMax, gap (giây),
    dots: [[ts, value]] (đo tay), zones: [{from, to, label}], shade: [{from, to, label}] (khoảng thời gian),
    xTicks: [[ts, nhãn]], extremes (đánh dấu cao/thấp nhất), last (ghi giá trị điểm cuối), timeFmt. */
function lineChart(el, points, o) {
  const H = o.height || 230;
  if (!points.length && !(o.dots || []).length) { emptyChart(el, Math.min(H, 120), o.empty); return; }
  const { svg, w } = chartBox(el, H, o.label);
  const padL = 40, padR = o.last ? 46 : 10, padT = 14, padB = 26;
  const iw = w - padL - padR, ih = H - padT - padB;
  const all = points.concat(o.dots || []).sort((a, b) => a[0] - b[0]);
  const vals = all.map((p) => p[1]);
  let lo = o.yMin ?? Math.max(0, Math.floor((Math.min(...vals) - 6) / 10) * 10);
  const { max: span, step } = niceScale(Math.max((o.yMax ?? Math.max(...vals) + 4) - lo, 10), 4);
  const hi = o.yMax ?? lo + span;
  const X = (ts) => padL + ((ts - o.t0) / (o.t1 - o.t0)) * iw;
  const Y = (v) => padT + ih - ((v - lo) / (hi - lo)) * ih;
  for (const s of o.shade || []) {
    const x0 = Math.max(padL, X(s.from)), x1 = Math.min(padL + iw, X(s.to));
    if (x1 <= x0) continue;
    sv("rect", { x: x0, y: padT, width: x1 - x0, height: ih, class: "shade" }, svg);
    svText(svg, x0 + 6, padT + 13, s.label, "band-label");
  }
  for (const z of o.zones || []) {
    const y0 = Y(Math.min(z.to, hi)), y1 = Y(Math.max(z.from, lo));
    if (z.tint) sv("rect", { x: padL, y: y0, width: iw, height: y1 - y0, class: "zone" }, svg);
    svText(svg, padL + iw - 6, y0 + 13, z.label, "band-label", "end");
  }
  const stepY = o.yStep || step;
  for (let v = lo; v <= hi + 1e-9; v += stepY) {
    const y = Math.round(Y(v)) + 0.5;
    sv("line", { x1: padL, x2: padL + iw, y1: y, y2: y, class: "grid" }, svg);
    svText(svg, padL - 8, y + 4, fmtInt(v), "axis", "end");
  }
  for (const [ts, text] of o.xTicks || []) {
    const x = X(ts);
    svText(svg, x, H - 8, text, "axis", x < padL + 20 ? "start" : x > padL + iw - 20 ? "end" : "middle");
  }
  // đường + vùng tô (tách đoạn khi mất dữ liệu lâu)
  const segs = [];
  points.forEach((p, i) => {
    if (i === 0 || p[0] - points[i - 1][0] > (o.gap || 900)) segs.push([]);
    segs[segs.length - 1].push(p);
  });
  for (const seg of segs) {
    const d = seg.map(([ts, v], i) => `${i ? "L" : "M"}${X(ts).toFixed(1)},${Y(v).toFixed(1)}`).join("");
    if (seg.length > 1) {
      sv("path", { d: `${d}L${X(seg[seg.length - 1][0]).toFixed(1)},${padT + ih}L${X(seg[0][0]).toFixed(1)},${padT + ih}Z`, class: "area", style: `fill:${o.color}` }, svg);
    }
    sv("path", { d, fill: "none", style: `stroke:${o.color}`, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
  }
  const dot = (ts, v, r = 4) => sv("circle", { cx: X(ts), cy: Y(v), r, style: `fill:${o.color}`, stroke: "var(--surface)", "stroke-width": 2 }, svg);
  for (const [ts, v] of o.dots || []) dot(ts, v);
  if (o.extremes && points.length > 2) {
    const hiP = points.reduce((a, p) => (p[1] > a[1] ? p : a));
    const loP = points.reduce((a, p) => (p[1] < a[1] ? p : a));
    for (const [p, above] of [[hiP, true], [loP, false]]) {
      dot(p[0], p[1], 3.5);
      const x = Math.min(padL + iw - 18, Math.max(padL + 18, X(p[0])));
      svText(svg, x, above ? Y(p[1]) - 9 : Y(p[1]) + 18, String(p[1]), "value-label", "middle");
    }
  }
  if (o.last && points.length) {
    const p = points[points.length - 1];
    dot(p[0], p[1], 4.5);
    svText(svg, X(p[0]) + 9, Y(p[1]) + 5, String(p[1]), "value-label big");
  }
  const cross = sv("line", { y1: padT, y2: padT + ih, class: "crosshair", visibility: "hidden" }, svg);
  const mark = sv("circle", { r: 4.5, style: `fill:${o.color}`, stroke: "var(--surface)", "stroke-width": 2, visibility: "hidden" }, svg);
  const hit = sv("rect", { x: padL, y: padT, width: iw, height: ih, class: "hit" }, svg);
  const fmtT = o.timeFmt || hhmm;
  hit.addEventListener("pointermove", (e) => {
    const box = svg.getBoundingClientRect();
    const ts = o.t0 + ((e.clientX - box.left - padL) / iw) * (o.t1 - o.t0);
    let best = all[0];
    for (const p of all) if (Math.abs(p[0] - ts) < Math.abs(best[0] - ts)) best = p;
    const x = X(best[0]);
    cross.setAttribute("x1", x); cross.setAttribute("x2", x); cross.setAttribute("visibility", "visible");
    mark.setAttribute("cx", x); mark.setAttribute("cy", Y(best[1])); mark.setAttribute("visibility", "visible");
    showTip(e.clientX, e.clientY, [[`${best[1]}${o.unit ? ` ${o.unit}` : ""}`, fmtT(best[0]), o.color]]);
  });
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); mark.setAttribute("visibility", "hidden"); hideTip(); });
}
const dayTicks = (t0) => [0, 6, 12, 18, 24].map((h) => [t0 + h * 3600, `${pad(h % 24)}:00`]);

/** Các giai đoạn của một giấc ngủ: mỗi giai đoạn một hàng, nối bằng đường bậc thang. */
function sleepChart(el, sess, rows = STAGES) {
  const rowH = 22, rowGap = 10, padL = 78, padR = 10, padT = 6, padB = 26;
  const H = padT + rows.length * (rowH + rowGap) + padB;
  const { svg, w } = chartBox(el, H, t("Các giai đoạn giấc ngủ"));
  const iw = w - padL - padR;
  const X = (ts) => padL + ((ts - sess.start) / (sess.end - sess.start)) * iw;
  const rowY = (i) => padT + i * (rowH + rowGap);
  rows.forEach(([, name], i) => {
    sv("rect", { x: padL, y: rowY(i), width: iw, height: rowH, rx: 4, class: "row-bg" }, svg);
    svText(svg, padL - 10, rowY(i) + rowH / 2 + 4, name(), "axis", "end");
  });
  // đường bậc thang nối các giai đoạn liên tiếp
  let path = "";
  sess.stages.forEach(([a, , stage], k) => {
    const i = rows.findIndex((s) => s[0] === stage);
    const y = rowY(i) + rowH / 2;
    path += `${k ? "L" : "M"}${X(a).toFixed(1)},${y}`;
  });
  sv("path", { d: path, class: "step-line" }, svg);
  for (const [a, b, stage] of sess.stages) {
    const i = rows.findIndex((s) => s[0] === stage);
    const [, name, color] = rows[i];
    const x = X(a);
    const rect = sv("rect", { x, y: rowY(i), width: Math.max(2, X(b) - x), height: rowH, rx: 3, class: "mark", style: `fill:${color}` }, svg);
    hoverable(rect, () => [[fmtMinutes((b - a) / 60), `${name()} · ${hhmm(a)}–${hhmm(b)}`, color]]);
  }
  svText(svg, padL, H - 8, hhmm(sess.start), "axis strong");
  svText(svg, w - padR, H - 8, hhmm(sess.end), "axis strong", "end");
  const span = sess.end - sess.start;
  const stepH = span > 8 * 3600 ? 2 : 1;
  for (let ts = Math.ceil(sess.start / 3600) * 3600; ts < sess.end; ts += 3600 * stepH) {
    if (ts - sess.start < 2400 || sess.end - ts < 2400) continue;
    svText(svg, X(ts), H - 8, hhmm(ts), "axis", "middle");
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

const STATUS = {
  good: [() => t("Tốt"), "✓"],
  ok: [() => t("Ổn"), "•"],
  watch: [() => t("Nên chú ý"), "!"],
  alert: [() => t("Cần lưu ý"), "!!"],
  none: [() => t("Chưa đủ dữ liệu"), "–"],
};

function renderAnalysis(a) {
  const list = $("#anList");
  list.textContent = "";
  if (!a || !a.items.length) {
    $("#anSub").textContent = t("Chưa đủ dữ liệu để phân tích. Kết nối vòng tay rồi bấm Đồng bộ.");
    return;
  }
  const c = a.counts;
  $("#anSub").textContent = t("Dựa trên dữ liệu 7–30 ngày gần nhất: {good} mục tốt, {ok} mục ổn, {watch} mục nên chú ý, {alert} mục cần lưu ý.", c);
  for (const it of a.items) {
    const card = document.createElement("div");
    card.className = "insight";
    card.dataset.status = it.status;
    const [label, icon] = STATUS[it.status] || STATUS.none;
    const chip = document.createElement("span");
    chip.className = "ins-status";
    const ic = document.createElement("b");
    ic.textContent = icon;
    chip.append(ic, label());
    const h = document.createElement("h3");
    h.textContent = it.title;
    const v = document.createElement("p");
    v.className = "ins-value";
    v.textContent = it.value;
    const d = document.createElement("p");
    d.className = "ins-detail";
    d.textContent = it.detail;
    card.append(chip, h, v, d);
    list.append(card);
  }
}

function renderHealth() {
  const H = healthData;
  renderDateNav();
  $("#hEmpty").hidden = !!H?.has_data;
  renderAnalysis(H?.analysis);
  if (!H) {
    $$(".hgrid .chart").forEach((el) => emptyChart(el, 80, t("Chưa có dữ liệu")));
    return;
  }
  const day = H.day;
  const isToday = healthDate === todayISO();
  const dayLabel = isToday ? t("Hôm nay") : longDate(healthDate);
  const t0 = new Date(`${healthDate}T00:00:00`).getTime() / 1000;
  const t1 = t0 + 86400;

  // giấc ngủ
  const sl = day.sleep;
  $("#slTotal").textContent = sl ? fmtMinutes(sl.minutes) : "—";
  $("#slRange").textContent = sl ? t("Ngủ lúc {start}, dậy lúc {end}", { start: hhmm(sl.start), end: hhmm(sl.end) }) : t("Không có giấc ngủ kết thúc vào {day}.", { day: dayLabel.toLowerCase() });
  const hasRem = H.sleep_days.some((d) => d.rem > 0);   // Mi Band 6 thường không ghi REM
  const rows = STAGES.filter(([key]) => key !== "rem" || hasRem);
  if (sl) sleepChart($("#slChart"), sl, rows); else emptyChart($("#slChart"), 60, t("Chưa có dữ liệu giấc ngủ cho ngày này."));
  const legend = $("#slLegend");
  legend.textContent = "";
  for (const [key, name, color] of STAGES) {
    if (key === "rem" && !hasRem) continue;   // Mi Band 6 thường không ghi REM
    const li = document.createElement("li");
    const sw = document.createElement("i");
    sw.style.background = color;
    const b = document.createElement("b");
    b.textContent = sl ? fmtMinutes(sl[key]) : "—";
    li.append(sw, `${name()} `, b);
    legend.append(li);
  }
  const slept = H.sleep_days.filter((d) => d.minutes);
  const avgSleep = slept.length ? slept.reduce((a, d) => a + d.minutes, 0) / slept.length : 0;
  columnChart($("#slHistory"), H.sleep_days.map((d) => ({
    key: d.date, label: shortDate(d.date),
    parts: [["deep", d.deep], ["light", d.light], ["rem", d.rem]].map(([k, v]) => ({ value: v / 60, color: stageInfo(k)[2] })),
    tip: () => [[fmtMinutes(d.minutes), longDate(d.date)], ...["deep", "light", "rem", "awake"].filter((k) => k !== "rem" || hasRem).map((k) => [fmtMinutes(d[k]), stageInfo(k)[1](), stageInfo(k)[2]])],
  })), {
    height: 210, label: t("Thời gian ngủ 14 ngày gần đây"), empty: t("Chưa có dữ liệu giấc ngủ."), yFmt: (v) => `${v}h`,
    selected: healthDate, onPick: pick, valueFmt: (v) => fmtMinutes(v * 60),
    band: { from: 7, to: 9, label: t("Khuyến nghị 7–9 giờ") },
    refs: avgSleep ? [{ value: avgSleep / 60, name: t("Trung bình"), text: fmtMinutes(avgSleep) }] : [],
  });

  // bước chân (hôm nay: số trực tiếp từ vòng tay mới hơn dữ liệu đã đồng bộ)
  const goal = Number(STATE.profile?.goal || 8000);
  const liveSteps = isToday && STATE.connected ? STATE.live?.activity?.steps : null;
  const steps = Math.max(day.steps, liveSteps ?? 0);
  $("#stTotal").textContent = fmtInt(steps);
  $("#stSub").textContent = t("{day} · {p}% mục tiêu {goal} bước", { day: dayLabel, p: Math.round((steps / goal) * 100), goal: fmtInt(goal) });
  columnChart($("#stHourly"), day.steps_hourly.map((v, h) => ({
    key: h, label: h % 3 === 0 ? `${pad(h)}:00` : "", parts: [{ value: v, color: "var(--c-steps)" }],
    tip: () => [[t("{n} bước", { n: fmtInt(v) }), `${pad(h)}:00–${pad((h + 1) % 24)}:00`]],
  })), { height: 180, label: t("Bước chân theo giờ"), empty: t("Không có bước chân nào được ghi trong ngày này."), valueFmt: fmtInt });
  const days = H.steps_days.slice();
  if (liveSteps != null) {
    const today = days.find((d) => d.date === healthDate);
    if (today) today.steps = Math.max(today.steps, liveSteps); else days.push({ date: healthDate, steps: liveSteps });
  }
  columnChart($("#stHistory"), days.map((d) => ({
    key: d.date, label: shortDate(d.date), parts: [{ value: d.steps, color: "var(--c-steps)" }],
    tip: () => [[t("{n} bước", { n: fmtInt(d.steps) }), longDate(d.date)], [d.steps >= goal ? t("Đạt mục tiêu") : t("Chưa đạt mục tiêu"), ""]],
  })), {
    height: 210, label: t("Bước chân mỗi ngày"), empty: t("Chưa có lịch sử bước chân."), selected: healthDate, onPick: pick,
    valueFmt: fmtInt, refs: [{ value: goal, name: t("Mục tiêu"), text: fmtInt(goal) }],
  });
  tableRows($("#stTable"), days.slice().reverse().map((d) => [longDate(d.date), fmtInt(d.steps)]), t("Chưa có dữ liệu"), 2);

  // nhịp tim (vùng tô: lúc ngủ)
  const hr = day.hr;
  $("#hrSub").textContent = dayLabel;
  if (hr.length) {
    const v = hr.map((p) => p[1]);
    statsList($("#hrStats"), [[t("Thấp nhất"), fmtInt(Math.min(...v)), t("nhịp/phút")], [t("Trung bình"), fmtInt(Math.round(v.reduce((a, b) => a + b, 0) / v.length)), t("nhịp/phút")], [t("Cao nhất"), fmtInt(Math.max(...v)), t("nhịp/phút")]]);
  } else statsList($("#hrStats"), []);
  lineChart($("#hrChart"), hr, {
    t0, t1, color: "var(--c-hr)", unit: t("nhịp/phút"), label: t("Nhịp tim trong ngày"), xTicks: dayTicks(t0), extremes: true,
    shade: [sl, ...(day.naps || [])].filter(Boolean).map((s) => ({ from: s.start, to: s.end, label: t("Ngủ") })),
    empty: t("Không có số đo nhịp tim trong ngày này."),
  });

  // căng thẳng (nền chia theo mức)
  const autoS = day.stress.filter((s) => s[2]).map((s) => [s[0], s[1]]);
  const manualS = day.stress.filter((s) => !s[2]).map((s) => [s[0], s[1]]);
  $("#ssSub").textContent = dayLabel;
  const sv_ = day.stress.map((s) => s[1]);
  if (sv_.length) {
    const avg = Math.round(sv_.reduce((a, b) => a + b, 0) / sv_.length);
    statsList($("#ssStats"), [[t("Trung bình"), String(avg), stressLabel(avg)], [t("Cao nhất"), String(Math.max(...sv_)), ""]]);
  } else statsList($("#ssStats"), []);
  lineChart($("#ssChart"), autoS, {
    t0, t1, yMin: 0, yMax: 100, yStep: 20, color: "var(--c-stress)", unit: "", dots: manualS, gap: 1800, xTicks: dayTicks(t0),
    zones: [{ from: 80, to: 100, label: t("Cao"), tint: true }, { from: 60, to: 80, label: t("Trung bình") },
      { from: 40, to: 60, label: t("Bình thường"), tint: true }, { from: 0, to: 40, label: t("Thư giãn") }],
    label: t("Mức căng thẳng trong ngày"),
    empty: manualS.length ? t("Chỉ có lần đo tay.") : t("Không có số đo căng thẳng. Bật Theo dõi căng thẳng trong Cài đặt → Sức khỏe."),
  });

  // PAI
  const pai = H.pai;
  if (pai.latest) statsList($("#paiStats"), [[t("Tổng 7 ngày"), fmtInt(Math.round(pai.latest.total)), ""], [t("Thêm hôm đó"), `+${fmtInt(Math.round(pai.latest.today))}`, ""]]);
  else statsList($("#paiStats"), []);
  columnChart($("#paiChart"), pai.days.map((d) => ({
    key: d.date, label: shortDate(d.date), parts: [{ value: d.total, color: "var(--c-pai)" }],
    tip: () => [[`${fmtInt(Math.round(d.total))} PAI`, longDate(d.date)], [`+${fmtInt(Math.round(d.today))}`, t("trong ngày")]],
  })), {
    height: 200, label: t("PAI các ngày gần đây"), empty: t("Chưa có dữ liệu PAI."), valueFmt: (v) => fmtInt(Math.round(v)),
    refs: [{ value: 100, name: t("Mục tiêu"), text: "100" }],
  });

  // SpO2
  const sp = H.spo2_recent;
  if (sp.length) statsList($("#spStats"), [[t("Lần đo gần nhất · {when}", { when: dateTime(sp[0][0]) }), String(sp[0][1]), "%"]]);
  else statsList($("#spStats"), []);
  tableRows($("#spTable"), sp.map(([ts, v, auto]) => [dateTime(ts), `${v}%`, auto ? t("Tự động") : t("Đo tay")]), t("Chưa có lần đo SpO2 nào. Đo trên vòng tay rồi đồng bộ lại."), 3);

  // tập luyện
  const fromCloud = H.workouts.filter((w) => w.source === "mifitness").length;
  $("#woSub").textContent = t("{n} buổi tập: {band} từ vòng tay, {cloud} từ Mi Fitness.", { n: H.workouts.length, band: H.workouts.length - fromCloud, cloud: fromCloud });
  tableRows($("#woTable"), H.workouts.map((w) => [
    workoutName(w), dateTime(w.start), fmtMinutes(((w.active_seconds || (w.end - w.start)) / 60)),
    w.distance ? `${fmtDec(w.distance / 1000)} km` : "—", w.calories ? `${fmtInt(w.calories)} kcal` : "—",
    w.avg_hr ? t("{n} nhịp/phút", { n: w.avg_hr }) : "—", w.steps ? fmtInt(w.steps) : "—",
    w.source === "mifitness" ? "Mi Fitness" : t("Vòng tay"), "",
  ]), t("Chưa có buổi tập nào. Bấm Lấy lịch sử từ Mi Fitness để lấy các buổi cũ."), 9);
  // nút Bản đồ cho buổi chạy / đạp xe ngoài trời có lộ trình GPS (Mi Fitness ghi từ GPS của điện thoại)
  $$("#woTable tr").forEach((tr, i) => {
    const w = H.workouts[i];
    if (!w?.gps) return;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn small wo-map";
    b.innerHTML = '<svg class="ic"><use href="#i-route"/></svg><span></span>';
    $("span", b).textContent = t("Bản đồ");
    b.onclick = () => openMap(w, b);
    tr.lastElementChild.append(b);
  });

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

/* ============================================================ bản đồ lộ trình */

/* Bản đồ nền: ô ảnh chuẩn của OpenStreetMap (CSS làm tối cho hợp giao diện); lộ trình vẽ bằng SVG lên trên.
   Theo chính sách dùng ô ảnh của OpenStreetMap: có ghi nguồn, chỉ tải phần đang xem.
   Phép chiếu Web Mercator; MAP.cx/cy là tâm khung nhìn tính bằng điểm ảnh ở mức phóng to MAP.z. */
const MAP = { pts: null, z: 14, cx: 0, cy: 0, drag: null, frame: 0 };
const TILE = 256;
function project(lat, lon, z) {
  const size = TILE * 2 ** z;
  const r = (lat * Math.PI) / 180;
  return [((lon + 180) / 360) * size, ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * size];
}
function mapFit() {
  const el = $("#map");
  const w = el.clientWidth, h = el.clientHeight;
  const xy = MAP.pts.map(([, lat, lon]) => project(lat, lon, 0));
  const xs = xy.map((p) => p[0]), ys = xy.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  let z = 18;
  while (z > 2 && ((x1 - x0) * 2 ** z > w - 80 || (y1 - y0) * 2 ** z > h - 80)) z--;
  MAP.z = z;
  MAP.cx = ((x0 + x1) / 2) * 2 ** z;
  MAP.cy = ((y0 + y1) / 2) * 2 ** z;
  mapDraw();
}
function mapDraw() {
  const el = $("#map");
  const w = el.clientWidth, h = el.clientHeight;
  const ox = MAP.cx - w / 2, oy = MAP.cy - h / 2;
  const n = 2 ** MAP.z;
  const tiles = $("#mapTiles");
  tiles.textContent = "";
  for (let ty = Math.floor(oy / TILE); ty <= Math.floor((oy + h) / TILE); ty++) {
    if (ty < 0 || ty >= n) continue;
    for (let tx = Math.floor(ox / TILE); tx <= Math.floor((ox + w) / TILE); tx++) {
      const img = document.createElement("img");
      img.alt = "";
      img.src = `https://tile.openstreetmap.org/${MAP.z}/${((tx % n) + n) % n}/${ty}.png`;
      img.style.left = `${tx * TILE - ox}px`;
      img.style.top = `${ty * TILE - oy}px`;
      img.onerror = () => img.remove();
      tiles.append(img);
    }
  }
  const svg = $("#mapRoute");
  svg.textContent = "";
  const pts = MAP.pts.map(([, lat, lon]) => { const [x, y] = project(lat, lon, MAP.z); return [x - ox, y - oy]; });
  const d = pts.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  sv("path", { d, class: "casing" }, svg);
  sv("path", { d, class: "line" }, svg);
  const [sx, sy] = pts[0], [ex, ey] = pts[pts.length - 1];
  sv("circle", { cx: ex, cy: ey, r: 7, class: "end" }, svg);
  sv("circle", { cx: sx, cy: sy, r: 7, class: "start" }, svg);
}
function mapZoom(delta, mx, my) {
  const z = Math.max(2, Math.min(19, MAP.z + delta));
  if (z === MAP.z) return;
  const el = $("#map");
  const ax = (mx ?? el.clientWidth / 2) - el.clientWidth / 2, ay = (my ?? el.clientHeight / 2) - el.clientHeight / 2;
  const f = 2 ** (z - MAP.z);
  MAP.cx = (MAP.cx + ax) * f - ax;   // giữ nguyên điểm dưới con trỏ
  MAP.cy = (MAP.cy + ay) * f - ay;
  MAP.z = z;
  mapDraw();
}
function mapMessage(text) {
  $("#mapMsg").textContent = text;
  $("#mapMsg").hidden = !text;
}

// Trong ứng dụng macOS, lộ trình mở trong cửa sổ Apple Maps (MapKit) của ứng dụng; trên trình duyệt dùng bản đồ dưới đây.
const nativeMap = () => window.webkit?.messageHandlers?.routeMap || null;

async function openMap(w, btn) {
  const stats = workoutStats(w);
  const native = nativeMap();
  let error = null;
  if (native) {
    if (btn) { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
    try {
      const r = await api(`/api/workouts/${w.start}/track`);
      if (r.points.length >= 2) {
        native.postMessage({ title: workoutName(w), subtitle: dateTime(w.start), points: r.points, stats });
        return;
      }
      error = t("Buổi tập này không có điểm GPS nào.");
    } catch (e) {
      error = e.message;
    } finally {
      if (btn) { btn.disabled = false; btn.removeAttribute("aria-busy"); }
    }
  }
  const dlg = $("#mapDialog");
  $("#mapTitle").textContent = workoutName(w);
  $("#mapSub").textContent = dateTime(w.start);
  $("#mapTiles").textContent = "";
  $("#mapRoute").textContent = "";
  statsList($("#mapStats"), stats);
  if (error) {   // ứng dụng macOS: chỉ mở hộp thoại này để báo lỗi
    MAP.pts = null;
    mapMessage(error);
    if (!dlg.open) dlg.showModal();
    return;
  }
  mapMessage(t("Đang tải lộ trình…"));
  if (!dlg.open) dlg.showModal();
  try {
    const r = await api(`/api/workouts/${w.start}/track`);
    if (!r.points.length) { mapMessage(t("Buổi tập này không có điểm GPS nào.")); return; }
    MAP.pts = r.points;
    mapMessage("");
    mapFit();
  } catch (e) {
    mapMessage(e.message);
  }
}

function workoutStats(w) {
  const secs = w.active_seconds || w.end - w.start;
  const stats = [[t("Thời gian"), fmtMinutes(secs / 60), ""]];
  if (w.distance) {
    stats.push([t("Quãng đường"), fmtDec(w.distance / 1000), "km"]);
    const perKm = secs / (w.distance / 1000);
    if (w.mf_type === 6 || w.type === 4) stats.push([t("Tốc độ TB"), fmtDec((w.distance / 1000) / (secs / 3600), 1), "km/h"]);
    else stats.push([t("Tốc độ TB"), `${Math.floor(perKm / 60)}'${pad(Math.round(perKm % 60))}"`, "/km"]);
  }
  if (w.avg_hr) stats.push([t("Nhịp tim TB"), String(w.avg_hr), t("nhịp/phút")]);
  if (w.calories) stats.push([t("Năng lượng"), fmtInt(w.calories), "kcal"]);
  return stats;
}
$("#mapClose").onclick = () => $("#mapDialog").close();
$("#mapIn").onclick = () => mapZoom(1);
$("#mapOut").onclick = () => mapZoom(-1);
$("#mapFit").onclick = () => MAP.pts && mapFit();
(() => {
  const el = $("#map");
  el.addEventListener("pointerdown", (e) => {
    if (!MAP.pts || e.target.closest(".map-zoom, .map-attr")) return;
    MAP.drag = { x: e.clientX, y: e.clientY, cx: MAP.cx, cy: MAP.cy };
    el.setPointerCapture(e.pointerId);
    el.classList.add("dragging");
  });
  el.addEventListener("pointermove", (e) => {
    if (!MAP.drag) return;
    MAP.cx = MAP.drag.cx - (e.clientX - MAP.drag.x);
    MAP.cy = MAP.drag.cy - (e.clientY - MAP.drag.y);
    cancelAnimationFrame(MAP.frame);
    MAP.frame = requestAnimationFrame(mapDraw);
  });
  const end = () => { MAP.drag = null; el.classList.remove("dragging"); };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
  el.addEventListener("wheel", (e) => {
    if (!MAP.pts) return;
    e.preventDefault();
    const b = el.getBoundingClientRect();
    mapZoom(e.deltaY < 0 ? 1 : -1, e.clientX - b.left, e.clientY - b.top);
  }, { passive: false });
  el.addEventListener("keydown", (e) => {
    if (!MAP.pts) return;
    const step = 80;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (moves[e.key]) { e.preventDefault(); MAP.cx += moves[e.key][0]; MAP.cy += moves[e.key][1]; mapDraw(); }
    else if (e.key === "+" || e.key === "=") mapZoom(1);
    else if (e.key === "-") mapZoom(-1);
  });
  window.addEventListener("resize", () => { if ($("#mapDialog").open && MAP.pts) mapDraw(); });
})();

/** Vẽ lại các phần có chữ ghép với số liệu, ngày giờ (không đụng tới giá trị đang sửa trong các ô nhập). */
function rerenderLanguage() {
  if (!META) return;
  const steps = [
    () => applyState(STATE),
    () => { relabelOptions($("#hInterval"), hrIntervalLabel); relabelOptions($("#hThreshold"), hrThresholdLabel); },
    renderAlarms,
    drawSpark,
    // trang ẩn thì để lúc mở trang (route -> loadHealth) vẽ lại, tránh vẽ biểu đồ khi chưa có kích thước
    () => { if (healthData && !$("#page-health").hidden) { renderDateNav(); renderHealth(); } },
    () => { if (SIM) drawSim(); },
    () => { if (cloudOpen && STATE.cloud && STATE.cloud.state !== "done") renderCloud({ ...STATE.cloud, seq: null }); },
  ];
  for (const step of steps) {
    try { step(); } catch (e) { console.warn(e); }
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
  drawSpark();
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
    if (st.job === "workouts") quiet(loadHealth());
    else fillProfile();
    if (cloudOpen) {
      closeCloud();
      toast(st.message || t("Đã lấy hồ sơ từ Mi Fitness."));
    }
    return;
  }
  if (!cloudOpen) return;
  const busy = s === "checking" || s === "fetching";
  $("#cloudBusy").hidden = !busy;
  $("#cloudBusyText").textContent = s !== "fetching" ? t("Đang kết nối tới máy chủ Xiaomi…")
    : st.job === "workouts" ? t("Đang đọc lịch sử buổi tập từ Mi Fitness…") : t("Đang đọc hồ sơ từ Mi Fitness…");
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

let cloudJob = "profile";
async function startCloud(fresh = false, job = cloudJob) {
  cloudOpen = true;
  cloudJob = job;
  const dlg = $("#cloudDialog");
  if (!dlg.open) dlg.showModal();
  renderCloud({ state: "checking" });
  try {
    const r = await api("/api/cloud/sync", { write: true, fresh, job });
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

$("#cloudSyncBtn").addEventListener("click", () => startCloud(false, "profile"));
$("#woCloudBtn").addEventListener("click", () => startCloud(false, "workouts"));
$("#cloudRetryBtn").addEventListener("click", () => startCloud(false));
$("#cloudReloginBtn").addEventListener("click", () => startCloud(true));
$("#cloudCancelBtn").addEventListener("click", cancelCloud);
$("#cloudDialog").addEventListener("cancel", (ev) => { ev.preventDefault(); cancelCloud(); });

init();
