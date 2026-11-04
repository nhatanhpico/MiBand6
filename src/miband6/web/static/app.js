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
let activeSyncs = 0;
let isScanning = false;
let isConnecting = false;

function setSyncActive(active) {
  if (active) activeSyncs++;
  else activeSyncs = Math.max(0, activeSyncs - 1);
  updateCornerDot();
}

function updateCornerDot() {
  const el = $("#cornerDot");
  if (!el) return;
  const isHealthRunning = STATE.health?.state === "running";
  const isCloudRunning = STATE.cloud?.state === "checking" || STATE.cloud?.state === "fetching";
  const isSyncing = activeSyncs > 0 || isHealthRunning || isCloudRunning;
  const isLookingForBand = !STATE.connected && (isScanning || isConnecting || STATE.busy || STATE.reconnect);

  if (isSyncing) {
    el.hidden = false;
    el.dataset.mode = "sync";
    el.title = t("Đang đồng bộ…");
    el.setAttribute("aria-label", t("Đang đồng bộ…"));
  } else if (isLookingForBand) {
    el.hidden = false;
    el.dataset.mode = "connecting";
    el.title = t("Đang tìm vòng tay…");
    el.setAttribute("aria-label", t("Đang tìm vòng tay…"));
  } else {
    el.hidden = true;
    delete el.dataset.mode;
  }
}

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

const PAGES = ["overview", "health", "settings", "alarms", "tools", "device", "app"];   // settings: vòng tay; app: ứng dụng
const SUBS = ["profile", "display", "face", "apps", "health"];
// Thẻ của trang Sức khỏe; cycle chỉ cho hồ sơ nữ, intimacy chỉ cho hồ sơ nam. Địa chỉ cũ (#health/steps…) vẫn mở đúng thẻ.
const HTABS = ["sleep", "activity", "heart", "body", "workouts", "cycle", "intimacy", "trends", "insights"];
const HTAB_ALIAS = { readiness: "insights", analysis: "insights", mind: "insights", summary: "trends", changes: "trends",
  hr: "heart", stress: "heart", spo2: "heart",
  measure: "heart", steps: "activity", pai: "activity", intensity: "activity", circadian: "sleep", weight: "body", bmi: "body" };
/** Giới tính trong hồ sơ (Cài đặt vòng tay → Hồ sơ): 0 nam, 1 nữ; "Khác" / chưa chọn: null. */
const profileSex = () => ({ 0: "male", 1: "female" })[Number(STATE.profile?.gender ?? -1)] ?? null;
const tabAllowed = (tab) => HTABS.includes(tab) && (tab !== "cycle" || profileSex() === "female")
  && (tab !== "intimacy" || profileSex() === "male");

const LAST_SUBS = (() => {
  try {
    const s = sessionStorage.getItem("mb6_last_subs");
    return s ? JSON.parse(s) : {};
  } catch {
    return {};
  }
})();

function saveLastSub(page, sub) {
  LAST_SUBS[page] = sub;
  try { sessionStorage.setItem("mb6_last_subs", JSON.stringify(LAST_SUBS)); } catch {}
}

function route() {
  const [page0, sub0] = (location.hash.slice(1) || "").split("/");
  const page = PAGES.includes(page0) ? page0 : STATE.connected || STATE.last_device ? "overview" : "device";
  $$(".page").forEach((p) => (p.hidden = p.id !== `page-${page}`));
  $$(".nav a").forEach((a) => {
    const target = (a.getAttribute("href") || "").slice(1).split("/")[0];
    a.setAttribute("aria-current", target === page ? "page" : "false");
  });
  if (page === "settings") {
    const sub = SUBS.includes(sub0) ? sub0 : (LAST_SUBS.settings && SUBS.includes(LAST_SUBS.settings) ? LAST_SUBS.settings : "profile");
    saveLastSub("settings", sub);
    if (sub0 !== sub) {
      history.replaceState(null, "", `#settings/${sub}`);
    }
    const navSettings = $('.nav a[href^="#settings"]');
    if (navSettings) navSettings.setAttribute("href", `#settings/${sub}`);
    $$("#page-settings .subtabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.sub === sub)));
    $$("#page-settings .subpage").forEach((s) => (s.hidden = s.id !== `sub-${sub}`));
    if (sub === "face") requestAnimationFrame(() => (WP.img ? wpDraw() : drawSim()));
  }
  window.scrollTo({ top: 0 });
  $(".main")?.scrollTo({ top: 0 });
  if (page === "overview") quiet(loadOverview());
  if (page === "health") {
    const day = (location.hash.slice(1).split("/")[2] || "").match(/^\d{4}-\d{2}-\d{2}$/)?.[0];
    if (day) healthDate = day > todayISO() ? todayISO() : day;   // #health/<thẻ>/<ngày>: liên kết mở đúng ngày
    let tab = sub0 || "";
    if (tab.startsWith("map:")) {   // ứng dụng mở từ nút "Mở trong ứng dụng" của trình duyệt
      healthMap = tab.slice(4);
      tab = "workouts";
    }
    tab = HTAB_ALIAS[tab] || tab;
    if (!tabAllowed(tab)) tab = tabAllowed(LAST_SUBS.health) ? LAST_SUBS.health : "sleep";
    healthTab = tab;
    saveLastSub("health", tab);
    if (sub0 !== tab || day) history.replaceState(null, "", `#health/${tab}`);
    $('.nav a[href^="#health"]')?.setAttribute("href", `#health/${tab}`);
    showHealthTab();
    if (healthData) renderHealth();   // vẽ ngay bằng dữ liệu đã có, rồi lấy bản mới
    quiet(loadHealth());
  }
}
window.addEventListener("hashchange", route);
$$("#page-settings .subtabs button").forEach((b) => b.addEventListener("click", () => {
  saveLastSub("settings", b.dataset.sub);
  location.hash = `#settings/${b.dataset.sub}`;
}));
$$(".htabs button").forEach((b) => b.addEventListener("click", () => { location.hash = `#health/${b.dataset.htab}`; }));

/* ============================================================ vòng tay + số liệu */

const live = { hr: null, steps: null, meters: null, calories: null, battery: null, charging: false, hrHistory: [] };

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
  const wfEmpty = $("#wfEmpty");
  if (wfEmpty) wfEmpty.hidden = has;
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
setInterval(() => renderSyncChip(), 30000);   // "Đồng bộ 5 phút trước" cập nhật theo thời gian

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
  // Goal progress is now shown only in the goal-glance card (ovGoalRing/ovSteps/ovGoalTarget),
  // which is updated by renderOverview(). Trigger a re-render when live data changes.
  renderOverview();
}

function render(kind, d) {
  if (d == null) return;
  switch (kind) {
    case "battery": {
      live.battery = d.level;
      live.charging = d.charging;
      $("#bat").textContent = `${d.level}%`;
      $("#batBar").style.width = `${Math.max(0, Math.min(100, d.level))}%`;
      $("#batBar").classList.toggle("low", d.level <= 20);
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
      live.meters = d.meters;
      live.calories = d.calories;
      updateGoal();
      break;
    case "heart_rate":
      live.hr = d;
      live.hrHistory.push([Date.now() / 1000, d]);
      if (live.hrHistory.length > 120) live.hrHistory.shift();
      $("#hr").textContent = d;
      drawSpark();
      liveHrToHealth(Math.floor(Date.now() / 1000), d);
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
  renderOverview();
}

/* ============================================================ trạng thái */

/** "Mất kết nối… Tự thử lại lúc hh:mm:ss (lần n)." kèm lý do lần thử trước (Bluetooth tắt, vòng tay bận…). */
function reconnectText(rc) {
  const at = new Date(rc.at * 1000);
  const time = `${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`;
  const text = t("Mất kết nối với vòng tay. Tự thử lại lúc {time} (lần {n}).", { time, n: rc.attempt });
  return rc.error ? `${text} ${t("Lần trước: {e}", { e: rc.error })}` : text;
}

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
  $("#deviceHero").hidden = !on;
  $("#liveHrAuto").checked = !!st.settings?.live_hr_auto;
  $("#hrLiveBtn").setAttribute("aria-pressed", String(!!(on && st.live_hr)));

  const status = $("#status");
  status.dataset.state = on ? "on" : st.busy || waiting ? "busy" : "off";
  $("#statusText").textContent = on ? st.device?.name || "Mi Smart Band 6"
    : st.busy ? t("Đang kết nối…") : waiting ? t("Đang chờ kết nối lại…") : t("Chưa kết nối");
  if (waiting) {
    $("#connStatus").className = "conn-status";
    $("#connStatus").textContent = reconnectText(st.reconnect);
  } else if (!on && st.reconnect_stopped) {
    $("#connStatus").className = "conn-status error";
    $("#connStatus").textContent = t("Đã ngừng tự kết nối lại: {reason}", { reason: st.reconnect_stopped.message });
  } else if (on && wasReconnecting) {
    $("#connStatus").className = "conn-status ok";
    $("#connStatus").textContent = t("Đã tự kết nối lại với vòng tay.");
  }
  wasReconnecting = !!st.reconnect;
  if (!on) {
    $("#statusBat").textContent = "";
    live.hr = null;
    live.battery = null;
    $("#bat").textContent = "—";
    $("#batBar").style.width = "0";
    $("#batNote").textContent = t("Chưa kết nối");
  } else {
    $("#iProtocol").textContent = (PROTO[st.device?.protocol] || (() => "—"))();
  }
  if (!formsFilled) {
    fillForms();
    formsFilled = true;
  }
  markSync();
  showHealthTab();
  renderWatchface(st.watchface);
  renderHealthStatus(st.health);
  renderWeather(st.weather);
  renderGeneral(st);
  for (const [kind, data] of Object.entries(st.live || {})) render(kind, data);
  updateGoal();
  drawBand();
  updateCornerDot();
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
      case "music_error": toast(msg.message, true); break;
      case "disconnected":
        toast(msg.reconnecting ? t("Vòng tay đã ngắt kết nối. Đang tự kết nối lại…")
          : t("Vòng tay đã ngắt kết nối. Bấm Kết nối để nối lại."), true);
        stopFindPhone();
        break;
      case "cloud": renderCloud(msg.status); break;
      case "health": renderHealthStatus(msg.status); break;
      case "weather": STATE.weather = msg.status; renderWeather(msg.status); break;
      case "health_data":
        if (!$("#page-health").hidden) quiet(loadHealth());
        if (!$("#page-overview").hidden) quiet(loadOverview());
        break;
      case "hr_minute": liveHrToHealth(msg.data[0], msg.data[1], true); break;
      case "tracks":   // vừa tải xong thêm lộ trình: bản đồ tổng đang mở thì vẽ thêm; bảng buổi tập cập nhật nút Bản đồ
        if ($("#mapDialog").open && MAP.mode === "all") {
          clearTimeout(MAP.refresh);
          MAP.refresh = setTimeout(() => openAllMaps(true), 400);
        }
        clearTimeout(MAP.tableRefresh);
        MAP.tableRefresh = setTimeout(() => { if (!$("#page-health").hidden && !$("#mapDialog").open) quiet(loadHealth()); }, 800);
        break;
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
  isScanning = true;
  updateCornerDot();
  $("#scanLabel").textContent = t("Đang quét…");
  try {
    const r = await run($("#scanBtn"), () => api("/api/scan", { show_all: $("#showAll").checked }));
    renderDevices(r.devices);
    if (r.devices.length) toast(t("Tìm thấy {n} thiết bị.", { n: r.devices.length }));
  } catch { /* đã báo */ } finally {
    isScanning = false;
    updateCornerDot();
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
  isConnecting = true;
  updateCornerDot();
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
  } finally {
    isConnecting = false;
    updateCornerDot();
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

$("#keepConn2").onchange = () => { $("#keepConn").checked = $("#keepConn2").checked; $("#keepConn").onchange(); };
$("#keepConn").onchange = () => quiet(run(null, async () => {
  applyState((await api("/api/prefs", { keep_connected: $("#keepConn").checked })).state);
}));

/* ============================================================ tổng quan */

$("#syncTimeBtn").onclick = () => quiet(run($("#syncTimeBtn"), async () => {
  setSyncActive(true);
  try {
    render("band_time", (await api("/api/time/sync", {})).band_time);
  } finally {
    setSyncActive(false);
  }
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
  $("#pMaxHr").value = p.max_hr_override ?? "";
  $("#pGoal").value = p.goal ?? "";
  setSwitch($("#pGoalNotify"), p.goal_notify ?? null);
  setRadio("wear", p.wear_left == null ? null : p.wear_left ? "left" : "right");
}

$("#maxHrForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("#pMaxHr");
  quiet(run($("button", event.currentTarget), async () => {
    const result = await api("/api/prefs", { max_hr_override: input.value === "" ? null : input.valueAsNumber });
    applyState(result.state);
  }, t("Đã lưu.")));
});

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
    const target = missing.classList.contains("date-native") ? missing.nextElementSibling : missing;
    (missing.closest(".seg") ? $("label", missing.closest(".seg")) : target).scrollIntoView({ block: "center" });
    target.focus();
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
  $("#unsyncedNote").hidden = false;   // cached preferences never prove current band state
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
const SIM = { source: null, binB64: null, binName: "", binPreview: null, binRendered: false, binAnim: null, raf: 0,
  current: null, currentKey: null };
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

/** Mặt đồng hồ có ảnh động trong tệp .bin: lớp dưới, khung hiện tại của từng ảnh động, lớp trên. */
function drawFaceAnim(g, a, now) {
  g.drawImage(a.below, 0, 0);
  for (const it of a.items) g.drawImage(it.frames[Math.floor(now / it.interval) % it.frames.length], it.x, it.y);
  if (a.above) g.drawImage(a.above, 0, 0);
}

/** Chạy ảnh động trong khung mô phỏng; tự dừng khi rời chế độ tệp .bin hoặc bỏ tệp. */
function simAnimate(now) {
  SIM.raf = 0;
  const a = SIM.binAnim;
  if (!a || faceMode() !== "bin") return;
  if ($("#simScreen").getClientRects().length) drawFaceAnim($("#simScreen").getContext("2d"), a, now);
  SIM.raf = requestAnimationFrame(simAnimate);
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
  } else if (faceMode() === "bin" && SIM.binAnim) {
    drawFaceAnim(g, SIM.binAnim, performance.now());
    if (!SIM.raf) SIM.raf = requestAnimationFrame(simAnimate);
    source = "bin";
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
    bin: () => (SIM.binRendered ? t("Mô phỏng mặt đồng hồ trong tệp .bin") : t("Mô phỏng: ảnh xem trước trong tệp .bin")),
    current: () => t("Mặt đồng hồ đã cài qua ứng dụng"),
    default: () => t("Mặt mặc định của ứng dụng (chưa chọn ảnh)"),
  }[source])();
  faceButtons();
}

function faceButtons() {
  const ready = faceMode() === "photo" ? !!WP.img : !!SIM.binB64;
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

function pickFile(inputId) {
  const input = $(inputId);
  const accept = input.accept || "";
  if (window.webkit?.messageHandlers?.fileAccept) {
    window.webkit.messageHandlers.fileAccept.postMessage(accept);
  }
  input.click();
}

$("#wpPickBtn").onclick = () => pickFile("#wpFile");
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

$("#wfPickBtn").onclick = () => pickFile("#wfFile");
$("#wfFile").onchange = async () => {
  const file = $("#wfFile").files[0];
  if (!file) return;
  SIM.binB64 = null;
  SIM.binPreview = null;
  SIM.binRendered = false;
  SIM.binAnim = null;
  $("#wfInfo").hidden = true;
  try {
    const b64 = await readBase64(file);
    const r = await api("/api/watchface/inspect", { file: b64 });
    SIM.binB64 = b64;
    SIM.binName = file.name;
    $("#wfName").textContent = `${file.name} · ${fmtInt(Math.round(r.size / 1024))} KB`;
    $("#wfName").classList.add("chosen");
    if (r.preview) SIM.binPreview = await loadImage(r.preview);
    if (r.animation) {
      const a = r.animation;
      SIM.binAnim = {
        below: await loadImage(a.below), above: a.above ? await loadImage(a.above) : null,
        items: await Promise.all(a.items.map(async (it) => ({ ...it, frames: await Promise.all(it.frames.map(loadImage)) }))),
      };
    }
    SIM.binRendered = !!r.rendered;
    $("#wfInfo").textContent = r.animation ? t("Đã dựng mặt đồng hồ từ các ảnh trong tệp, kể cả ảnh động.")
      : r.rendered ? t("Đã dựng mặt đồng hồ từ các ảnh trong tệp.")
        : r.preview ? t("Đã đọc ảnh xem trước trong tệp.") : t("Không đọc được ảnh trong tệp này; tệp vẫn cài được.");
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

/* ============================================================ cài đặt chung: lịch đồng bộ, tài khoản, kết nối */

const SYNC_OPTIONS = {
  syncBand: ["band_minutes", [0, 15, 30, 60, 120], (v) => (v ? (v < 60 ? t("Mỗi {n} phút", { n: v }) : v === 60 ? t("Mỗi giờ") : t("Mỗi {n} giờ", { n: v / 60 })) : t("Chỉ khi bấm Đồng bộ"))],
  syncCloud: ["cloud_hours", [0, 1, 3, 6, 12, 24], (v) => (v ? (v === 1 ? t("Mỗi giờ") : v === 24 ? t("Mỗi ngày") : t("Mỗi {n} giờ", { n: v })) : t("Chỉ khi bấm Đồng bộ"))],
  syncRenew: ["renew_hours", [0, 12, 24, 168], (v) => (v ? (v === 24 ? t("Mỗi ngày") : v === 168 ? t("Mỗi tuần") : t("Mỗi {n} giờ", { n: v })) : t("Khi hết hạn"))],
  syncRetry: ["retry_max", [10, 30, 60, 300], (v) => (v < 60 ? t("{n} giây", { n: v }) : t("{n} phút", { n: v / 60 }))],
};

function renderGeneral(st) {
  $("#musicGroup").hidden = META?.platform !== "darwin" || !!st.demo;
  $("#musicPlayer").value = st.settings?.music_player || "off";
  const sync = st.sync || {};
  for (const [id, [key, values, label]] of Object.entries(SYNC_OPTIONS)) {
    const sel = $(`#${id}`);
    const cur = String(sync[key] ?? "");
    sel.textContent = "";
    for (const v of values) mkEl("option", { value: String(v) }, sel).textContent = label(v);
    sel.value = cur;
  }
  $("#keepConn2").checked = st.settings?.keep_connected ?? true;
  const when = (ts) => (ts ? dateTime(ts) : t("chưa có"));
  $("#syncLast").textContent = t("Lần cuối: vòng tay {band} · Mi Fitness {cloud}", { band: when(st.health?.last_sync), cloud: when(sync.cloud_last) });
  const acct = st.account || {};
  $("#acctStatus").textContent = acct.logged_in
    ? t("Đã đăng nhập · phiên lưu lúc {time}", { time: dateTime(acct.saved) }) + (acct.can_renew ? "" : ` · ${t("không tự gia hạn được")}`)
    : t("Chưa đăng nhập");
  $("#acctRenewBtn").disabled = !acct.can_renew;
  $("#acctLogoutBtn").disabled = !acct.logged_in;
  $("#acctLoginBtn").textContent = acct.logged_in ? t("Đăng nhập lại") : t("Đăng nhập");
  $("#syncNowBtn").disabled = !st.connected && !acct.logged_in;
  const rem = st.settings?.rem_mode || "estimate";
  $("#remEst").checked = rem === "estimate";
  $("#remOff").checked = rem === "off";
}

for (const [id, [key]] of Object.entries(SYNC_OPTIONS)) {
  $(`#${id}`).addEventListener("change", (e) => quiet(run(null, async () => {
    applyState((await api("/api/prefs", { sync: { [key]: Number(e.target.value) } })).state);
  }, t("Đã lưu."))));
}
$$('input[name="remMode"]').forEach((el) => el.addEventListener("change", () => quiet(run(null, async () => {
  applyState((await api("/api/prefs", { rem_mode: el.value })).state);
}, el.value === "off" ? t("Đã tắt REM.") : t("Đã bật ước tính REM.")))));
$("#syncNowBtn").onclick = () => quiet(run($("#syncNowBtn"), async () => {
  setSyncActive(true);
  try {
    if (STATE.connected) renderHealthStatus((await api("/api/health/sync", {})).status);
    if (STATE.account?.logged_in) await api("/api/cloud/sync", { job: "workouts" });
  } finally {
    setSyncActive(false);
  }
}, t("Đang đồng bộ ở nền…")));
$("#acctRenewBtn").onclick = () => quiet(run($("#acctRenewBtn"), async () => {
  await api("/api/cloud/renew", {});
}, t("Đã gia hạn phiên đăng nhập.")));
$("#acctLoginBtn").onclick = () => startCloud(true, "workouts");
$("#acctLogoutBtn").onclick = () => quiet(run($("#acctLogoutBtn"), async () => {
  await api("/api/cloud/forget", {});
}, t("Đã đăng xuất khỏi Mi Fitness.")));
$("#musicPlayer").onchange = () => quiet(run($("#musicPlayer"), async () => {
  try {
    applyState((await api("/api/prefs", { music_player: $("#musicPlayer").value })).state);
  } finally {
    $("#musicPlayer").value = STATE.settings?.music_player || "off";
  }
}, t("Đã lưu.")));
$("#liveHrAuto").onchange = () => quiet(run(null, async () => {
  applyState((await api("/api/prefs", { live_hr_auto: $("#liveHrAuto").checked })).state);
}, $("#liveHrAuto").checked ? t("Vòng tay sẽ tự đo nhịp tim liên tục mỗi lần kết nối.") : t("Đã tắt tự đo nhịp tim liên tục.")));
$("#reconnectNowBtn").onclick = () => quiet(run($("#reconnectNowBtn"), async () => {
  applyState((await api("/api/reconnect", {})).state);
}));

/* ============================================================ thời tiết */

let wxCityMode = false;   // đang chọn "Chọn thành phố" nhưng chưa chọn nơi nào
function renderWeather(w) {
  if (!w) return;
  $("#wxOn").checked = !!w.enabled;
  const city = !!w.place || wxCityMode;
  $("#wxAuto").checked = !city;
  $("#wxCity").checked = city;
  $("#wxSearch").hidden = !city;
  const box = $("#wxNow");
  box.textContent = "";
  const line = (text, cls = "") => { const p = mkEl("p", cls ? { class: cls } : {}, box); p.textContent = text; return p; };
  if (w.place) line(t("Thành phố: {name}", { name: [w.place.name, w.place.detail].filter(Boolean).join(", ") }), "wx-place");
  else line(t("Vị trí tự động theo mạng đang dùng (địa chỉ IP)."), "wx-place");
  if (w.state === "running") line(t("Đang gửi thời tiết…"));
  else if (w.state === "error") line(t("Lần gửi trước không thành công: {e}", { e: w.error || "" }), "wx-error");
  if (w.now) {
    const n = w.now;
    const parts = [`${n.place}`, `${n.temp}°`, n.text, t("cao {high}° / thấp {low}°", { high: n.high, low: n.low })];
    if (n.humidity != null) parts.push(t("độ ẩm {h}%", { h: n.humidity }));
    if (n.aqi != null) parts.push(t("AQI {aqi}", { aqi: n.aqi }));
    line(t("Đã gửi lúc {time}: {summary}", { time: dateTime(w.at), summary: parts.join(" · ") }), "wx-sent");
  } else if (w.state !== "running" && w.state !== "error") {
    line(w.enabled ? t("Thời tiết sẽ được gửi khi kết nối vòng tay.") : t("Đang tắt: vòng tay giữ thời tiết đã nhận lần trước."));
  }
  $("#wxSyncBtn").disabled = !STATE.connected || w.state === "running";
}

async function saveWeather(body, okText) {
  try {
    applyState((await api("/api/weather", body)).state);
    if (okText) toast(okText);
  } catch (e) {
    toast(e.message, true);
  }
}

$("#wxOn").addEventListener("change", () => saveWeather({ enabled: $("#wxOn").checked }));
$("#wxAuto").addEventListener("change", () => { wxCityMode = false; saveWeather({ place: null }); });
$("#wxCity").addEventListener("change", () => {
  wxCityMode = true;
  renderWeather(STATE.weather);
  $("#wxQuery").focus();
});
$("#wxSyncBtn").onclick = () => quiet(run($("#wxSyncBtn"), async () => {
  setSyncActive(true);
  try {
    const r = await api("/api/weather/sync", {});
    STATE.weather = r.weather;
    renderWeather(r.weather);
  } finally {
    setSyncActive(false);
  }
}, t("Đã gửi thời tiết tới vòng tay.")));
(() => {
  let timer = null, seq = 0;
  $("#wxQuery").addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = $("#wxQuery").value.trim();
      const my = ++seq;
      const list = $("#wxResults");
      if (q.length < 2) { list.textContent = ""; return; }
      let places = [];
      try {
        places = (await api(`/api/weather/search?q=${encodeURIComponent(q)}`)).places;
      } catch (e) {
        if (my === seq) { list.textContent = ""; mkEl("li", { class: "wx-empty" }, list).textContent = e.message; }
        return;
      }
      if (my !== seq) return;
      list.textContent = "";
      if (!places.length) { mkEl("li", { class: "wx-empty" }, list).textContent = t("Không tìm thấy nơi nào."); return; }
      for (const p of places) {
        const b = mkEl("button", { type: "button" }, mkEl("li", {}, list));
        mkEl("b", {}, b).textContent = p.name;
        if (p.detail) mkEl("span", {}, b).textContent = p.detail;
        b.onclick = () => {
          wxCityMode = false;
          list.textContent = "";
          $("#wxQuery").value = "";
          saveWeather({ place: p }, t("Đã chọn {name}.", { name: p.name }));
        };
      }
    }, 300);
  });
})();

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
let healthTab = "sleep";   // thẻ đang mở của trang Sức khỏe
let healthMap = null;   // bản đồ cần mở sau khi tải xong dữ liệu sức khỏe

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
  $("#ovSyncBtn").disabled = !STATE.connected || st.state === "running";
  renderSyncChip(st);
  updateCornerDot();
}

/** "vừa xong", "5 phút trước", "lúc 08:12" hoặc ngày giờ: lần đồng bộ cuối ở đầu trang Hôm nay. */
function agoText(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 90) return t("vừa xong");
  if (s < 3600) return t("{n} phút trước", { n: Math.round(s / 60) });
  return new Date(ts * 1000).toDateString() === new Date().toDateString() ? t("lúc {time}", { time: hhmm(ts) }) : dateTime(ts);
}

function renderSyncChip(st = STATE.health) {
  const chip = $("#ovSyncChip");
  if (!chip || !st) return;
  if (st.state === "running") {
    chip.dataset.state = "running";
    chip.textContent = t("Đang đồng bộ…");
    chip.title = "";
  } else if (st.last_sync) {
    chip.dataset.state = st.errors?.length ? "error" : "ok";
    chip.textContent = t("Đồng bộ {when}", { when: agoText(st.last_sync) });
    chip.title = st.errors?.length ? t("chưa lấy được: {list}", { list: st.errors.join(", ") }) : dateTime(st.last_sync);
  } else {
    chip.dataset.state = "none";
    chip.textContent = t("Chưa đồng bộ");
    chip.title = "";
  }
}

let healthRequest = 0;
async function loadHealth() {
  // ngày mới hiện ngay trên lịch ở đầu trang; thẻ mờ đi tới khi dữ liệu của ngày đó về
  const seq = ++healthRequest;
  const date = healthDate;
  renderDateNav();
  $("#page-health").classList.toggle("is-loading", !!healthData && healthData.date !== date);
  let r;
  try {
    r = await api(`/api/health?date=${date}`);
  } finally {
    if (seq === healthRequest) $("#page-health").classList.remove("is-loading");
  }
  if (seq !== healthRequest) return;   // đã chọn ngày khác trong lúc chờ: bỏ kết quả cũ
  healthData = r.health;
  renderHealthStatus(r.status);
  renderHealth();
  if (healthMap) {
    openMapFromHash(healthMap);
    healthMap = null;
  }
}

/* Overview has its own today-only snapshot; browsing a past health day must not change it. */
let overviewData = null;
let overviewRequest = 0;

function overviewSummary(H, activity, goal, today) {
  const current = H?.date === today ? H : null;
  const day = current?.day;
  const liveSteps = Number.isFinite(activity?.steps) ? activity.steps : null;
  const storedSteps = current?.has_data && Number.isFinite(day?.steps) ? day.steps : null;
  const steps = liveSteps == null ? storedSteps : Math.max(liveSteps, storedSteps ?? 0);
  const target = Number.isFinite(goal) && goal > 0 ? goal : 8000;
  const days = new Map((current?.steps_days || []).map((d) => [d.date, d.steps]));
  if (steps != null) days.set(today, steps);
  let date = today;
  let streak = 0;
  // Today's incomplete goal does not break the sequence of completed calendar days.
  if ((days.get(date) ?? 0) < target) date = shiftDate(date, -1);
  while ((days.get(date) ?? -1) >= target) { streak++; date = shiftDate(date, -1); }
  return { steps, target, pct: steps == null ? null : Math.min(100, Math.round(100 * steps / target)),
    streak: days.size ? streak : null, day, readiness: current?.insights?.readiness };
}

async function loadOverview() {
  const request = ++overviewRequest;
  const r = await api(`/api/health?date=${todayISO()}`);
  if (request !== overviewRequest) return;
  overviewData = r.health;
  renderHealthStatus(r.status);
  renderOverview();
}

/** Trang Hôm nay hiện cả khi vòng tay chưa kết nối (dữ liệu đã đồng bộ), kèm băng báo kết nối; chỉ màn hình trống
    khi chưa có dữ liệu nào. */
function renderConnBanner() {
  const el = $("#ovConn");
  const has = !!overviewData?.has_data;
  const st = STATE;
  $("#overviewEmpty").hidden = st.connected || has;
  $("#overviewBody").hidden = !(st.connected || has);
  el.hidden = st.connected || !has;
  if (el.hidden) return;
  let mode = "off";
  let text = t("Vòng tay chưa kết nối.");
  if (st.reconnect_stopped) {
    mode = "stopped";
    text = t("Đã ngừng tự kết nối lại: {reason}", { reason: st.reconnect_stopped.message });
  } else if (st.busy) {
    mode = "waiting";
    text = t("Đang kết nối với vòng tay…");
  } else if (st.reconnect) {
    mode = "waiting";
    text = reconnectText(st.reconnect);
  }
  const last = st.health?.last_sync;
  if (last) text += ` ${t("Số liệu dưới đây đồng bộ lúc {when}.", { when: dateTime(last) })}`;
  el.dataset.mode = mode;
  $("#ovConnText").textContent = text;
  $("#ovRetryBtn").hidden = !(st.reconnect_stopped || st.reconnect) || st.busy;
}

const ring = (svg, value, cls = "arc") => {
  svg.textContent = "";
  sv("circle", { cx: 60, cy: 60, r: 50, class: "track" }, svg);
  const len = 2 * Math.PI * 50;
  if (value != null) sv("circle", { cx: 60, cy: 60, r: 50, class: cls, style: `stroke-dasharray: ${(len * value) / 100} ${len}` }, svg);
};

/** Điểm sẵn sàng hôm nay: thẻ đầu tiên của trang, kèm lời khuyên và thời gian hồi phục. */
function renderReadyToday(H) {
  const ins = H?.insights;
  const r = ins?.readiness;
  ring($("#ovReadyRing"), r?.score);
  $("#ovReadyCard").className = `hero-card ready-card${r ? ` lv-${r.status}` : ""}`;
  $("#ovReadyScore").textContent = r ? String(r.score) : "—";
  $("#ovReadyLabel").textContent = r ? r.label : t("Chưa có điểm hôm nay");
  $("#ovReadyPlan").textContent = r ? r.plan : !H?.has_data ? t("Đồng bộ vòng tay để có điểm sẵn sàng.")
    : !ins?.readiness_night ? t("Chưa có giấc ngủ đêm qua: đeo vòng khi ngủ rồi đồng bộ để có điểm của ngày này.")
    : t("Đang học mức nền của bạn: {n}/{need} đêm có nhịp tim khi ngủ.", { n: ins.readiness_progress?.nights ?? 0, need: ins.readiness_progress?.need ?? 8 });
  $("#ovReadyMeta").textContent = !r ? "" : r.recovery_hours >= 1
    ? t("Thời gian hồi phục còn lại: khoảng {h} giờ", { h: Math.round(r.recovery_hours) }) : t("Đã hồi phục sau các buổi tập gần đây.");
  $("#ovReadyCard").setAttribute("aria-label", `${t("Điểm sẵn sàng hôm nay")}: ${r ? `${r.score}/100, ${r.label}` : $("#ovReadyPlan").textContent}`);
}

function sleepStages(sl, bar, legend) {
  bar.replaceChildren();
  legend.replaceChildren();
  for (const [key, name, color] of STAGES) {
    if (!sl?.[key]) continue;
    const label = key === "rem" && sl.rem_estimated ? t("REM (ước tính)") : name();
    mkEl("span", { style: `flex:${sl[key]};background:${color}`, title: `${label}: ${fmtMinutes(sl[key])}` }, bar);
    const li = mkEl("li", {}, legend);
    mkEl("i", { style: `background:${color}` }, li);
    li.append(`${label} `);
    mkEl("b", {}, li).textContent = fmtMinutes(sl[key]);
  }
  bar.setAttribute("aria-label", sl ? legend.textContent : t("Chưa có dữ liệu"));
}

function scorePill(el, score) {
  el.hidden = score == null;
  if (score == null) return;
  el.className = `${el.classList.contains("big") ? "score-pill big" : "score-pill"} lv-${scoreStatus(score)}`;
  el.textContent = `${t("Điểm")} `;
  mkEl("b", {}, el).textContent = String(score);
}

function renderOverview() {
  renderConnBanner();
  const H = overviewData?.date === todayISO() ? overviewData : null;
  const v = overviewSummary(overviewData, STATE.connected ? STATE.live?.activity : null,
    Number(STATE.profile?.goal || 8000), todayISO());
  renderReadyToday(H);

  // giấc ngủ đêm qua
  const sl = v.day?.sleep;
  const night = H?.insights?.last_night;
  $("#ovSleep").textContent = sl ? fmtMinutes(sl.minutes) : "—";
  scorePill($("#ovSleepScore"), sl && night ? night.score : null);
  $("#ovSleepRange").textContent = sl ? t("Ngủ lúc {start}, dậy lúc {end}", { start: hhmm(sl.start), end: hhmm(sl.end) })
    : t("Chưa có giấc ngủ kết thúc hôm nay. Đeo vòng khi ngủ rồi đồng bộ.");
  sleepStages(sl, $("#ovSleepStages"), $("#ovSleepLegend"));
  const plan = H?.insights?.sleep_plan;
  $("#ovSleepPlan").textContent = plan ? t("Tối nay: lên giường lúc {bed} để ngủ đủ {t}", { bed: plan.bedtime, t: fmtMinutes(plan.sleep) }) : "";

  // bước chân
  $("#ovSteps").textContent = fmtInt(v.steps);
  $("#ovGoalTarget").textContent = t("/ {n} bước", { n: fmtInt(v.target) });
  $("#ovGoalRing").style.setProperty("--p", `${(v.pct || 0) * 3.6}deg`);
  $("#ovGoalRing").setAttribute("aria-label", t("Mục tiêu bước: {p}", { p: v.pct == null ? t("Chưa có dữ liệu") : `${v.pct}%` }));
  const meters = STATE.connected ? (live.meters ?? STATE.live?.activity?.meters) : null;
  const calories = STATE.connected ? (live.calories ?? STATE.live?.activity?.calories) : null;
  const stepBits = [];
  if (v.pct != null) stepBits.push(t("{p}% mục tiêu", { p: v.pct }));
  if (meters != null) stepBits.push(`${fmtDec(meters / 1000)}\u00a0km`);   // số và đơn vị không tách dòng
  if (calories != null) stepBits.push(`${fmtInt(calories)}\u00a0kcal`);
  $("#ovStepsSub").textContent = stepBits.join(" · ");

  // nhịp tim: số đo trực tiếp (đang đo / theo dõi liên tục) mới hơn số đã đồng bộ
  const hr = v.day?.hr?.at(-1);
  const liveHr = STATE.connected && live.hr ? live.hr : null;
  $("#ovHr").textContent = liveHr ?? (hr ? hr[1] : "—");
  const hrBits = [];
  if (liveHr) hrBits.push(STATE.live_hr ? t("Trực tiếp") : t("Vừa đo"));
  else if (hr) hrBits.push(t("lúc {time}", { time: hhmm(hr[0]) }));
  if (night?.hr) {
    const d = night.hr_baseline != null ? Math.round(night.hr - night.hr_baseline) : 0;
    hrBits.push(t("Nghỉ {n}", { n: night.hr }) + (d ? ` (${d > 0 ? "+" : ""}${d})` : ""));
  }
  $("#ovHrSub").textContent = hrBits.join(" · ");

  // căng thẳng
  const stress = v.day?.stress?.at(-1);
  $("#ovStress").textContent = stress ? String(stress[1]) : "—";
  $("#ovStressLabel").textContent = stress ? stressLabel(stress[1]) : "";
  const sv_ = (v.day?.stress || []).map((x) => x[1]);
  $("#ovStressSub").textContent = stress
    ? `${t("TB hôm nay {n}", { n: Math.round(sv_.reduce((a, b) => a + b, 0) / sv_.length) })} · ${t("lúc {time}", { time: hhmm(stress[0]) })}`
    : t("Chưa có số đo hôm nay");

  // chu kỳ (hồ sơ nữ đã ghi kỳ kinh)
  const cy = H?.insights?.cycle;
  $("#ovCycleTile").hidden = !cy;
  if (cy) {
    $("#ovCycleDay").textContent = String(cy.day);
    $("#ovCyclePhase").textContent = t("/ {n} ngày", { n: cy.cycle_length });
    $("#ovCycleSub").textContent = [cy.phase ? PHASES[cy.phase]() : "", cycleNext(cy)].filter(Boolean).join(" · ");
  }

  if (!$("#page-overview").hidden && !$("#overviewBody").hidden) {
    const recent = (H?.steps_days || []).slice(-7);
    columnChart($("#ovStepsTrend"), recent.map((d) => ({ key: d.date, label: shortDate(d.date),
      parts: [{ value: d.date === todayISO() ? v.steps ?? d.steps : d.steps, color: "var(--c-steps)" }],
      tip: () => [[fmtInt(d.date === todayISO() ? v.steps ?? d.steps : d.steps), longDate(d.date)]],
    })), { height: 120, label: t("Bước chân 7 ngày đã ghi gần nhất"), empty: t("Chưa có lịch sử bước chân."), valueFmt: compact,
      refs: [{ value: v.target, name: t("Mục tiêu"), text: compact(v.target) }] });
    $("#ovStreak").textContent = v.streak ? t("Đạt mục tiêu {n} ngày liền", { n: v.streak }) : "";
    const nights = (H?.sleep_days || []).slice(-7);
    const slept = nights.filter((d) => d.minutes);
    columnChart($("#ovSleepTrend"), nights.map((d) => ({ key: d.date, label: shortDate(d.date),
      parts: [["deep", d.deep], ["light", d.light], ["rem", d.rem]].map(([k, x]) => ({ value: x / 60, color: stageInfo(k)[2] })),
      tip: () => [[fmtMinutes(d.minutes), longDate(d.date)]],
    })), { height: 120, label: t("Giấc ngủ 7 đêm gần đây"), empty: t("Chưa có dữ liệu giấc ngủ."), yFmt: (x) => `${x}h`,
      band: { from: 7, to: 9, label: t("Khuyến nghị 7–9 giờ") } });
    $("#ovSleepAvg").textContent = slept.length ? t("TB {t}", { t: fmtMinutes(slept.reduce((a, d) => a + d.minutes, 0) / slept.length) }) : "";
    drawSpark();
  }
}

$("#ovSyncBtn").onclick = () => quiet(run($("#ovSyncBtn"), async () => {
  setSyncActive(true);
  try {
    await quiet(api("/api/refresh", {}));   // pin, bước chân, giờ trên vòng tay
    renderHealthStatus((await api("/api/health/sync", {})).status);
  } finally {
    setSyncActive(false);
  }
}));
$("#ovFindBtn").onclick = () => quiet(run($("#ovFindBtn"), () => api("/api/find", { on: true }), t("Vòng tay đang rung.")));
$("#ovRetryBtn").onclick = () => quiet(run($("#ovRetryBtn"), async () => applyState((await api("/api/reconnect", {})).state)));

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
/* ---- ô chọn ngày dùng chung: cùng giao diện với lịch ở đầu trang Sức khỏe (thay lịch của trình duyệt).
   Giữ nguyên <input type="date"> (ẩn) làm nơi chứa giá trị, nên mã đọc / ghi .value như cũ. Bấm tiêu đề để chọn
   tháng, rồi năm (ngày sinh không phải bấm lùi từng tháng). Hộp lịch đặt cố định trên trang để khung có góc bo
   (overflow: hidden) không cắt mất. */
const nativeValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value");
let openPicker = null;

function datePicker(input, opts = {}) {
  const wrap = document.createElement("span");
  wrap.className = "date-field";
  input.replaceWith(wrap);
  input.classList.add("date-native");
  input.tabIndex = -1;
  const btn = mkEl("button", { type: "button", class: "date-btn", "aria-haspopup": "dialog", "aria-expanded": "false" });
  btn.innerHTML = '<svg class="ic"><use href="#i-calendar"/></svg><span class="date-txt"><b></b><span></span></span>';
  wrap.append(input, btn);
  const pop = mkEl("div", { class: "cal-pop date-pop", role: "dialog" }, document.body);
  pop.hidden = true;
  pop.innerHTML = '<div class="cal-head"><button type="button" class="nav-arrow small prev"><svg class="ic"><use href="#i-chev-left"/></svg></button>'
    + '<button type="button" class="cal-title"></button><button type="button" class="nav-arrow small next"><svg class="ic"><use href="#i-chev-right"/></svg></button></div>'
    + '<div class="cal-grid"></div><div class="cal-foot"><span></span><span class="cal-quick"></span></div>';
  const [prev, title, next] = [$(".prev", pop), $(".cal-title", pop), $(".next", pop)];
  let view = "days";
  let cursor = new Date();   // ngày đầu tháng đang xem (view days) / năm đang xem (months, years)

  const dateOf = (iso) => new Date(`${iso}T12:00:00`);
  const max = () => input.max || "9999-12-31";
  const min = () => input.min || "0000-01-01";
  function refresh() {
    const v = nativeValue.get.call(input);
    $("b", btn).textContent = v ? new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "long", year: "numeric" }).format(dateOf(v)) : t("Chọn ngày");
    $(".date-txt span", btn).textContent = v ? new Intl.DateTimeFormat(LOCALE, { weekday: "long" }).format(dateOf(v)) : "";
    btn.classList.toggle("empty", !v);
  }
  // mã khác gán .value (điền hồ sơ, điền sẵn hôm nay): cập nhật chữ trên nút
  Object.defineProperty(input, "value", { configurable: true, get() { return nativeValue.get.call(this); },
    set(v) { nativeValue.set.call(this, v); refresh(); } });

  function cell(grid, text, { disabled, selected, today, onPick, label }) {
    const b = mkEl("button", { type: "button", class: "cal-day" }, grid);
    b.textContent = text;
    b.disabled = disabled;
    b.classList.toggle("today", !!today);
    b.setAttribute("aria-selected", String(!!selected));
    if (label) b.setAttribute("aria-label", label);
    b.onclick = onPick;
    return b;
  }
  function render() {
    const grid = $(".cal-grid", pop);
    grid.textContent = "";
    grid.classList.toggle("cal-wide", view !== "days");
    const value = input.value;
    const now = new Date();
    if (view === "days") {
      title.textContent = new Intl.DateTimeFormat(LOCALE, { month: "long", year: "numeric" }).format(cursor);
      prev.setAttribute("aria-label", t("Tháng trước"));
      next.setAttribute("aria-label", t("Tháng sau"));
      for (const name of weekdays()) mkEl("span", { class: "cal-dow" }, grid).textContent = name;
      for (let i = 0; i < (cursor.getDay() + 6) % 7; i++) grid.append(document.createElement("span"));
      const d = new Date(cursor);
      while (d.getMonth() === cursor.getMonth()) {
        const iso = isoOf(d);
        cell(grid, String(d.getDate()), { disabled: iso > max() || iso < min(), selected: iso === value, today: iso === isoOf(now),
          label: new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(d),
          onPick: () => choose(iso) });
        d.setDate(d.getDate() + 1);
      }
      next.disabled = isoOf(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1)) > max();
    } else if (view === "months") {
      const y = cursor.getFullYear();
      title.textContent = String(y);
      prev.setAttribute("aria-label", t("Năm trước"));
      next.setAttribute("aria-label", t("Năm sau"));
      for (let m = 0; m < 12; m++) {
        const first = new Date(y, m, 1);
        cell(grid, new Intl.DateTimeFormat(LOCALE, { month: "short" }).format(first), {
          disabled: isoOf(first) > max() || isoOf(new Date(y, m + 1, 0)) < min(),
          selected: value && dateOf(value).getFullYear() === y && dateOf(value).getMonth() === m,
          today: now.getFullYear() === y && now.getMonth() === m,
          onPick: () => { cursor = first; view = "days"; render(); } });
      }
      next.disabled = `${y + 1}-01-01` > max();
    } else {
      const start = cursor.getFullYear() - (cursor.getFullYear() % 12);
      title.textContent = `${start} – ${start + 11}`;
      prev.setAttribute("aria-label", t("Các năm trước"));
      next.setAttribute("aria-label", t("Các năm sau"));
      for (let y = start; y < start + 12; y++) {
        cell(grid, String(y), { disabled: `${y}-01-01` > max() || `${y}-12-31` < min(),
          selected: value && dateOf(value).getFullYear() === y, today: now.getFullYear() === y,
          onPick: () => { cursor = new Date(y, 0, 1); view = "months"; render(); } });
      }
      next.disabled = `${start + 12}-01-01` > max();
    }
    title.setAttribute("aria-label", t("Chọn tháng, năm"));
    title.disabled = view === "years";
  }
  function choose(iso) {
    input.value = iso;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    close();
    btn.focus();
  }
  function place() {
    const r = btn.getBoundingClientRect();
    const h = pop.offsetHeight;
    const below = window.innerHeight - r.bottom > h + 12;
    pop.style.top = `${below ? r.bottom + 8 : Math.max(8, r.top - h - 8)}px`;
    pop.style.left = `${Math.max(8, Math.min(window.innerWidth - pop.offsetWidth - 8, r.right - pop.offsetWidth))}px`;
  }
  function open() {
    if (openPicker && openPicker !== close) openPicker();
    const base = input.value ? dateOf(input.value) : dateOf(max() < todayISO() ? max() : todayISO());
    cursor = new Date(base.getFullYear(), base.getMonth(), 1);
    view = opts.startView && !input.value ? opts.startView : "days";
    render();
    pop.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    place();
    openPicker = close;
    ($(".cal-day[aria-selected=true]", pop) || $(".cal-day:not(:disabled)", pop))?.focus();
  }
  function close() {
    if (pop.hidden) return;
    pop.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    if (openPicker === close) openPicker = null;
  }
  title.onclick = () => { view = view === "days" ? "months" : "years"; render(); };
  const shift = (dir) => {
    cursor = view === "days" ? new Date(cursor.getFullYear(), cursor.getMonth() + dir, 1)
      : new Date(cursor.getFullYear() + dir * (view === "months" ? 1 : 12), 0, 1);
    render();
  };
  prev.onclick = () => shift(-1);
  next.onclick = () => shift(1);
  if (opts.today) {
    const quick = $(".cal-quick", pop);
    const b = mkEl("button", { type: "button", class: "btn small" }, quick);
    b.textContent = t("Hôm nay");
    b.onclick = () => choose(todayISO());
  } else {
    $(".cal-foot", pop).remove();
  }
  btn.onclick = () => (pop.hidden ? open() : close());
  document.addEventListener("pointerdown", (e) => { if (!pop.hidden && !pop.contains(e.target) && !btn.contains(e.target)) close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !pop.hidden) { close(); btn.focus(); } });
  window.addEventListener("resize", close);
  $(".main")?.addEventListener("scroll", close, { passive: true });
  refresh();
  return { refresh, close, button: btn };
}

const DATE_PICKERS = [datePicker($("#pBirth"), { startView: "years" }), datePicker($("#bdDate"), { today: true })];

$("#hPrev").onclick = () => { healthDate = shiftDate(healthDate, -1); quiet(loadHealth()); };
$("#hNext").onclick = () => { if (healthDate < todayISO()) { healthDate = shiftDate(healthDate, 1); quiet(loadHealth()); } };
$("#hSyncBtn").onclick = () => quiet(run($("#hSyncBtn"), async () => {
  setSyncActive(true);
  try {
    renderHealthStatus((await api("/api/health/sync", {})).status);
  } finally {
    setSyncActive(false);
  }
}));
// đổi cỡ cửa sổ (hoặc thanh bên thu gọn): vẽ lại biểu đồ của trang đang mở theo bề rộng mới
let resizeTimer, mainWidth = 0;
new ResizeObserver(([entry]) => {
  const w = Math.round(entry.contentRect.width);
  if (Math.abs(w - mainWidth) < 4) return;
  mainWidth = w;
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (!$("#page-health").hidden && healthData) renderHealth();
    if (!$("#page-overview").hidden) { drawSpark(); renderOverview(); }
  }, 120);
}).observe($(".main"));

/* ---- vẽ biểu đồ (SVG thuần) */

const SVGNS = "http://www.w3.org/2000/svg";
/** Tạo phần tử HTML với thuộc tính, gắn vào parent. */
function mkEl(tag, attrs, parent) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  if (parent) parent.append(node);
  return node;
}

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
$(".main")?.addEventListener("scroll", hideTip, { passive: true });
function hoverable(el, rows) {
  el.setAttribute("tabindex", "0");
  el.addEventListener("pointermove", (e) => showTip(e.clientX, e.clientY, rows()));
  el.addEventListener("pointerleave", hideTip);
  el.addEventListener("focus", () => { const b = el.getBoundingClientRect(); showTip(b.right, b.top, rows()); });
  el.addEventListener("blur", hideTip);
}

function chartBox(el, height, label) {
  // Đo trước, rồi thay biểu đồ cũ bằng khung mới (đã có chiều cao) trong một bước. Xóa trước rồi mới đo thì trang
  // ngắn lại giữa chừng; WebKit (ứng dụng macOS) không có scroll anchoring nên kéo trang lên mỗi lần vẽ lại,
  // vd. mỗi số đo khi đang theo dõi nhịp tim liên tục.
  const w = Math.max(240, Math.floor(el.clientWidth || 600));
  const svg = sv("svg", { viewBox: `0 0 ${w} ${height}`, width: w, height, role: "img", "aria-label": label });
  el.replaceChildren(svg);
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

/** Biểu đồ cột (một chuỗi, hoặc chồng nhiều phần). Bấm cột không đổi ngày đang xem: ngày chỉ đổi bằng lịch ở đầu trang.
    items: {key, label, parts: [{value, color}], tip: () => rows}; o: height, label, empty, yFmt, selected,
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
      // cột sát lề phải: canh phải để nhãn số không đè lên nhãn của đường mốc bên lề
      const edge = sx + slot / 2 > padL + iw - 36;
      svText(g, edge ? sx + slot : sx + slot / 2, Math.max(12, y0 - 6), o.valueFmt(total(it)), "value-label", edge ? "end" : "middle");
    }
    if (it.label && (i % every === 0 || isSel)) svText(svg, sx + slot / 2, H - 8, it.label, isSel ? "axis strong" : "axis", "middle");
    const hit = sv("rect", { x: sx, y: padT, width: slot, height: ih, class: "hit" }, g);
    hoverable(hit, it.tip);
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
  // số đo đứng riêng (không có số đo nào gần nó): đường một điểm gần như không thấy, vẽ thành chấm nhỏ
  for (const seg of segs) if (seg.length === 1) dot(seg[0][0], seg[0][1], 3);
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
/* ---------------- giải thích phụ: ẩn mặc định để số liệu và trạng thái nổi bật; bấm (i) ở tiêu đề thẻ để xem.
   Thẻ có thuộc tính data-hints; phần tử giải thích có lớp .hint (đặt sẵn trong HTML hoặc khi vẽ, tùy trạng thái). */

function setupHints() {
  for (const card of $$("[data-hints]")) {
    const h2 = $(".card-head h2", card);
    if (!h2 || $(".hint-btn", card)) continue;
    const b = mkEl("button", { type: "button", class: "hint-btn", "aria-expanded": "false", "aria-label": t("Thông tin thêm"), title: t("Thông tin thêm") });
    b.textContent = "i";
    (h2.nextElementSibling?.classList.contains("est-chip") ? h2.nextElementSibling : h2).after(b);
    b.onclick = () => b.setAttribute("aria-expanded", String(card.classList.toggle("show-hints")));
  }
}
setupHints();

/** Nút (i) chỉ hiện khi thẻ có giải thích để xem (sau mỗi lần vẽ, vì nội dung đổi theo dữ liệu). */
function refreshHints() {
  for (const card of $$("[data-hints]")) {
    const b = $(".hint-btn", card);
    if (b) b.hidden = !$$(".hint", card).some((el) => !el.closest("[hidden]") && el.textContent.trim());
  }
}
const hintIf = (el, on) => { el.classList.toggle("hint", !!on); return el; };
const needsAttention = (status) => status === "watch" || status === "alert";

const STATUS = {
  good: [() => t("Tốt"), "✓"],
  ok: [() => t("Ổn"), "•"],
  watch: [() => t("Nên chú ý"), "!"],
  alert: [() => t("Cần lưu ý"), "!!"],
  none: [() => t("Chưa đủ dữ liệu"), "–"],
};

const SEVERITY = { alert: 0, watch: 1, ok: 2, good: 3 };
const COUNT_LABEL = { alert: () => t("mục cần lưu ý"), watch: () => t("mục nên chú ý"), ok: () => t("mục ổn"), good: () => t("mục tốt") };

function renderAnalysis(a) {
  const list = $("#anList");
  list.textContent = "";
  const counts = $("#anCounts");
  counts.textContent = "";
  if (!a || !a.items.length) {
    hintIf($("#anSub"), false).textContent = t("Chưa đủ dữ liệu để phân tích. Kết nối vòng tay rồi bấm Đồng bộ.");
    return;
  }
  const c = a.counts;
  hintIf($("#anSub"), true).textContent = t("Dựa trên dữ liệu 7–30 ngày gần nhất: {good} mục tốt, {ok} mục ổn, {watch} mục nên chú ý, {alert} mục cần lưu ý.", c);
  for (const s of ["alert", "watch", "ok", "good"]) {
    if (c[s]) chip(mkEl("span", {}, counts), s, `${c[s]} ${COUNT_LABEL[s]()}`, "rd-level");
  }
  // mục cần lưu ý / nên chú ý lên đầu; giữ thứ tự gốc trong cùng mức
  const items = a.items.slice().sort((x, y) => (SEVERITY[x.status] ?? 4) - (SEVERITY[y.status] ?? 4));
  for (const it of items) {
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
    d.className = needsAttention(it.status) ? "ins-detail" : "ins-detail hint";   // mục tốt / ổn: chỉ cần trạng thái và số
    d.textContent = it.detail;
    card.append(chip, h, v, d);
    list.append(card);
  }
}

/* ---------------- mức sẵn sàng, trạng thái tinh thần, cường độ vận động, nhịp sinh học (insights.py) */

const MIND_STATUS = { calm: "good", balanced: "ok", tense: "watch", fatigued: "watch", overloaded: "alert" };
const scoreStatus = (v) => (v >= 80 ? "good" : v >= 60 ? "ok" : v >= 40 ? "watch" : "alert");

function chip(el, status, label, cls) {
  el.className = `${cls} lv-${status}`;
  el.textContent = "";
  const b = mkEl("b", {}, el);
  b.textContent = (STATUS[status] || STATUS.none)[1];
  el.append(label);
}

function renderReadiness(r, history, progress, hasNight) {
  const ring = $("#rdRing");
  ring.textContent = "";
  sv("circle", { cx: 60, cy: 60, r: 50, class: "track" }, ring);
  $("#rdParts").textContent = "";
  $("#rdRecovery").hidden = true;
  const isToday = healthDate === todayISO();
  $("#health-readiness h2").textContent = isToday ? t("Điểm sẵn sàng hôm nay") : t("Điểm sẵn sàng ngày {day}", { day: longDate(healthDate) });
  if (!r) {
    $("#rdScore").textContent = "—";
    $("#rdLevel").className = "rd-level";
    $("#rdLevel").textContent = "";
    $("#rdSub").textContent = t("Cho biết hôm nay nên tập luyện hay nghỉ ngơi, từ giấc ngủ, nhịp tim nghỉ, căng thẳng và tải vận động so với mức nền của bạn.");
    $("#rdPlan").textContent = !hasNight ? t("Chưa có giấc ngủ đêm qua: đeo vòng khi ngủ rồi đồng bộ để có điểm của ngày này.")
      : t("Đang học mức nền của bạn: {n}/{need} đêm có nhịp tim khi ngủ.", { n: progress?.nights ?? 0, need: progress?.need ?? 8 });
    $("#rdAdvice").textContent = t("Đeo vòng khi ngủ ít nhất 8 đêm (bật Hỗ trợ giấc ngủ) để ứng dụng biết nhịp tim nghỉ, giấc ngủ và tải vận động thường ngày của bạn.");
    columnChart($("#rdTrend"), [], { height: 60, empty: t("Chưa có dữ liệu") });
    return;
  }
  const len = 2 * Math.PI * 50;
  sv("circle", { cx: 60, cy: 60, r: 50, class: `arc lv-${r.status}`, style: `stroke: var(--lv); stroke-dasharray: ${(len * r.score) / 100} ${len}` }, ring);
  $("#rdScore").textContent = r.score;
  chip($("#rdLevel"), r.status, r.label, "rd-level");
  $("#rdPlan").textContent = r.plan;
  $("#rdAdvice").textContent = r.advice;
  if (r.recovery_hours != null) {
    $("#rdRecovery").hidden = false;
    $("#rdRecovery").textContent = r.recovery_hours >= 1
      ? t("Thời gian hồi phục còn lại: khoảng {h} giờ", { h: Math.round(r.recovery_hours) })
      : t("Đã hồi phục sau các buổi tập gần đây.");
  }
  $("#rdSub").textContent = t("Từ {n} thành phần so với mức nền của bạn; điểm hôm nay cập nhật theo các buổi tập trong ngày.", { n: r.parts.length });
  for (const p of r.parts) {
    const li = mkEl("li", { class: `lv-${scoreStatus(p.score)}` }, $("#rdParts"));
    mkEl("span", { class: "name" }, li).textContent = p.title;
    mkEl("span", { class: "val" }, li).textContent = `${p.value} · ${p.score}`;
    mkEl("i", { style: `width:${p.score}%` }, mkEl("span", { class: "bar", role: "img", "aria-label": `${p.title}: ${p.score}/100` }, li));
    hoverable(li, () => [[`${p.score}/100`, p.title], [p.detail, ""]]);
  }
  const verdictColor = { train_hard: "var(--mint)", train: "var(--sky)", easy: "var(--amber)", rest: "var(--coral)" };
  columnChart($("#rdTrend"), history.map((h) => ({
    key: h.date, label: shortDate(h.date), parts: [{ value: h.score, color: "var(--c-deep)" }],
    tip: () => [[String(h.score), longDate(h.date)], [READY_LABEL[h.verdict]?.() || "", "", verdictColor[h.verdict]]],
  })), {
    height: 150, label: t("Điểm sẵn sàng 14 ngày gần đây"), empty: t("Chưa có dữ liệu"), yFmt: (v) => String(v),
    selected: healthDate, valueFmt: (v) => String(Math.round(v)),
    refs: [{ value: 60, name: t("Sẵn sàng tập"), text: "60" }],
  });
}
const READY_LABEL = {
  train_hard: () => t("Sẵn sàng tập nặng"), train: () => t("Sẵn sàng tập luyện"), easy: () => t("Nên tập nhẹ"), rest: () => t("Nên nghỉ ngơi"),
};

function renderMind(m, dataUntil) {
  const box = $("#mdState");
  box.textContent = "";
  $("#mdMeters").textContent = "";
  $("#mdFactors").textContent = "";
  $("#mdNotes").textContent = "";
  $("#mdBand").hidden = true;
  // hôm nay: ghi rõ dữ liệu tới lúc nào (vòng tay không kết nối khi ra ngoài, tập luyện…)
  $("#mdSub").textContent = healthDate === todayISO() && dataUntil
    ? t("Ước tính từ dữ liệu cơ thể tới {time}, không phải chẩn đoán.", { time: dateTime(dataUntil) })
    : t("Ước tính từ dữ liệu cơ thể, không phải chẩn đoán.");
  if (!m) {
    mkEl("p", { class: "md-text" }, box).textContent = t("Cần vài ngày dữ liệu giấc ngủ, căng thẳng và nhịp tim để ước tính.");
    return;
  }
  const status = MIND_STATUS[m.state];
  chip(mkEl("span", {}, box), status, m.label, "md-chip");
  mkEl("p", { class: "md-text" }, box).textContent = m.text;
  const s = m.stress;
  if (s) {   // đúng những gì vòng tay đo được, để đối chiếu với thẻ Căng thẳng
    const bits = [t("Vòng tay đo: trung bình {v} ({label}) từ {n} số đo trong 3 ngày", { v: s.avg, label: stressLabel(s.avg), n: s.n })];
    if (s.today_n) bits.push(t("hôm nay {v} ({n} số đo)", { v: s.today_avg, n: s.today_n }));
    if (s.usual != null) bits.push(t("thường ngày {v}", { v: s.usual }));
    $("#mdBand").textContent = bits.join(" · ");
    $("#mdBand").hidden = false;
  }
  for (const note of m.notes || []) mkEl("li", {}, $("#mdNotes")).textContent = note;
  const meter = (name, value, st) => {
    const row = mkEl("div", { class: `md-meter lv-${st}` }, $("#mdMeters"));
    mkEl("span", {}, row).textContent = name;
    mkEl("i", { style: `width:${value}%` }, mkEl("span", { class: "bar", role: "img", "aria-label": `${name}: ${value}/100` }, row));
    mkEl("b", {}, row).textContent = String(value);
  };
  meter(t("Áp lực tổng"), m.strain, scoreStatus(100 - m.strain));
  meter(t("Căng (thần kinh)"), m.tension, scoreStatus(100 - m.tension));
  meter(t("Mệt (thiếu ngủ)"), m.fatigue, scoreStatus(100 - m.fatigue));
  hintIf($("#mdFactors"), !needsAttention(status));   // trạng thái tốt: lý do nằm trong phần giải thích
  for (const f of m.factors) {
    const li = mkEl("li", { class: `lv-${scoreStatus(100 - f.level)}` }, $("#mdFactors"));
    mkEl("span", {}, li).textContent = f.text;
    mkEl("i", { style: `width:${Math.max(4, f.level)}%` }, mkEl("span", { class: "bar", "aria-hidden": "true" }, li));
  }
  mkEl("li", { class: "md-conf" }, $("#mdFactors")).textContent = t("Độ tin cậy: {c}", { c: m.confidence_label });
}

/* ---------------- tín hiệu cơ thể: nhịp tim khi ngủ so với mức nền và mô hình cá nhân (insights.body_signals) */

const signedNum = (v, d = 1) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${fmtDec(Math.abs(v), d)}`;
const noonTs = (iso) => new Date(`${iso}T12:00:00`).getTime() / 1000;

function renderBody(b) {
  const box = $("#bsState");
  box.textContent = "";
  $("#bsCauses").textContent = "";
  $("#bsEffects").textContent = "";
  $("#bsModel").textContent = "";
  $("#bsLegend").textContent = "";
  if (!b) {
    mkEl("p", { class: "md-text" }, box).textContent = t("Cần ít nhất 8 đêm có nhịp tim khi ngủ để biết mức thường của bạn.");
    statsList($("#bsStats"), []);
    emptyChart($("#bsChart"), 80, t("Chưa có dữ liệu"));
    return;
  }
  chip(mkEl("span", {}, box), b.status, b.label, "md-chip");
  hintIf(mkEl("p", { class: "md-text" }, box), !needsAttention(b.status)).textContent = b.text;
  hintIf($("#bsCauses"), !needsAttention(b.status));
  const l = b.last;
  const stats = [[t("Đêm {day}", { day: shortDate(l.date) }), String(l.hr), t("nhịp/phút")],
    [t("Mức thường của bạn"), fmtDec(l.baseline, 0), `± ${fmtDec(l.sd, 1)}`]];
  if (l.expected != null) {
    stats.push([t("Mô hình dự đoán"), fmtDec(l.baseline + l.expected, 0), t("nhịp/phút")],
      [t("Chưa giải thích được"), signedNum(l.unexplained), t("nhịp/phút")]);
  }
  statsList($("#bsStats"), stats);
  const pts = b.series.map((s) => [noonTs(s.date), s.hr]);
  const vals = pts.map((p) => p[1]);
  const lo = l.baseline - 2 * l.sd, hi = l.baseline + 2 * l.sd;
  lineChart($("#bsChart"), pts, {
    t0: pts[0][0] - 43200, t1: pts[pts.length - 1][0] + 43200, color: "var(--c-hr)", unit: t("nhịp/phút"), gap: 1.5 * 86400,
    yMin: Math.floor(Math.min(lo, ...vals) - 3), yMax: Math.ceil(Math.max(hi, ...vals) + 3), height: 190,
    dots: b.series.filter((s) => s.high).map((s) => [noonTs(s.date), s.hr]),
    zones: [{ from: lo, to: hi, label: "", tint: true }],   // nhãn nằm ở chú giải, không đè lên đường
    timeFmt: (ts) => longDate(isoOf(new Date(ts * 1000))), label: t("Nhịp tim khi ngủ các đêm gần đây"),
    xTicks: [[pts[0][0], shortDate(b.series[0].date)], [pts[pts.length - 1][0], shortDate(l.date)]],
  });
  for (const [cls, text] of [["k-zone", t("Mức thường của bạn (± 2 độ lệch chuẩn)")], ["k-high", t("Đêm cao hơn mức thường")]]) {
    const li = mkEl("li", {}, $("#bsLegend"));
    mkEl("i", { class: cls }, li);
    li.append(text);
  }
  for (const c of l.causes || []) mkEl("li", {}, $("#bsCauses")).textContent = c;
  const m = b.model;
  $("#bsModel").textContent = [m?.text, m?.since ? t("Dữ liệu học từ đêm {date}.", { date: longDate(m.since) }) : ""].filter(Boolean).join(" ");
  for (const e of m?.effects || []) mkEl("li", {}, $("#bsEffects")).textContent = e;
  renderCurve(m?.curve || []);
}

/** Sai số của mô hình cá nhân khi chỉ học từ 1 tuần, 1 tháng, 3 tháng, 6 tháng, 1 năm dữ liệu (models.learning_curve). */
const CURVE_LABEL = { 7: () => t("1 tuần"), 30: () => t("1 tháng"), 90: () => t("3 tháng"), 180: () => t("6 tháng"), 365: () => t("1 năm") };
function renderCurve(curve) {
  const bpm = (v) => `${fmtDec(v, 1)} ${t("nhịp/phút")}`;
  tableRows($("#bsCurve"), curve.map((c) => [
    (CURVE_LABEL[c.days] || (() => t("{n} ngày", { n: c.days })))(),
    c.status === "ok" ? `${bpm(c.mae)} · ${t("{n} đêm", { n: c.nights })}`
      : c.status === "too_few" ? t("quá ít đêm để học (cần 21)") : t("cần thêm dữ liệu"),
    c.status === "ok" ? bpm(c.mae_null) : "—",
  ]), t("Cần ít nhất 21 đêm có nhịp tim khi ngủ."), 3);
}

/* ---------------- nguy cơ bệnh: mô hình máy học học từ NHANES (risk.py), hiệu chỉnh cho người châu Á */

const RISK_INPUT_NAME = { pulse: () => t("nhịp tim lúc nghỉ"), sleep: () => t("giấc ngủ"), active: () => t("vận động") };

function renderRisk(r) {
  const list = $("#rkList");
  list.textContent = "";
  $("#rkInputs").hidden = true;
  $("#rkModel").textContent = "";
  if (!r?.available) {
    const why = !r ? t("Chưa có dữ liệu")
      : r.reason === "profile" ? t("Nhập ngày sinh, giới tính, chiều cao và cân nặng ở Cài đặt vòng tay → Hồ sơ để ước tính.")
        : r.reason === "age" ? t("Mô hình chỉ dành cho người từ 18 tuổi.")
          : t("Chưa có tệp mô hình: chạy tools/train_risk_models.py để tạo.");
    mkEl("p", { class: "md-text" }, list).textContent = why;
    return;
  }
  const i = r.inputs;
  const bits = [t("{n} tuổi", { n: i.age }), i.sex === "male" ? t("Nam") : t("Nữ"), `${fmtInt(i.height)} cm`, `BMI ${fmtDec(i.bmi, 1)}`,
    t("nhịp tim lúc nghỉ {n}", { n: i.pulse }), t("ngủ {h} giờ mỗi đêm", { h: fmtDec(i.sleep, 1) }), t("vận động {n} ngày mỗi tuần", { n: i.active })];
  let text = t("Dựa trên: {list}.", { list: bits.join(" · ") });
  if (i.days) text += ` ${t("Số đo của vòng tay: trung bình {n} ngày gần nhất.", { n: i.days })}`;
  if (r.estimated.length) {
    text += ` ${t("Chưa đủ số đo của vòng tay cho {list}: dùng mức trung bình cùng giới.", { list: r.estimated.map((k) => RISK_INPUT_NAME[k]()).join(", ") })}`;
  }
  $("#rkInputs").textContent = text;
  $("#rkInputs").hidden = false;
  for (const c of r.conditions) {
    const item = mkEl("div", { class: `rk-item lv-${c.status}` }, list);
    const head = mkEl("div", { class: "rk-head" }, item);
    mkEl("h3", {}, head).textContent = c.title;
    chip(mkEl("span", {}, head), c.status, c.level, "rd-level");
    mkEl("b", { class: "rk-risk" }, item).textContent = c.risk_text;
    // thang tương đối: vạch trắng là mức của người cùng tuổi, giới có các chỉ số lành mạnh
    const top = Math.max(0.1, c.risk, c.reference) * 1.25;
    const bar = mkEl("span", { class: "rk-bar", role: "img", "aria-label": `${c.title}: ${c.risk_text}`,
      title: t("Thanh màu: nguy cơ của bạn. Vạch trắng: người cùng tuổi, giới có các chỉ số ở mức lành mạnh.") }, item);
    mkEl("i", { style: `width:${(c.risk / top) * 100}%` }, bar);
    mkEl("b", { style: `left:${(c.reference / top) * 100}%` }, bar);
    mkEl("p", { class: "hint" }, item).textContent = c.what;
    mkEl("p", { class: "rk-compare" }, item).textContent = c.compare;
    if (c.factors.length) {
      mkEl("p", {}, item).textContent = t("Yếu tố làm nguy cơ cao hơn:");
      const ul = mkEl("ul", {}, item);
      for (const f of c.factors) mkEl("li", {}, ul).textContent = f.text;
    }
    mkEl("p", {}, item).textContent = c.advice;
    const m = c.metrics;
    mkEl("p", { class: "rk-metric hint", title: t("AUC: khả năng mô hình xếp người mắc bệnh cao hơn người không mắc; 0,5 là đoán ngẫu nhiên, 1 là hoàn hảo.") }, item)
      .textContent = t("Độ chính xác khi kiểm chứng: AUC {auc} (người châu Á {asian})", { auc: fmtDec(m.auc, 2), asian: fmtDec(m.asian_auc, 2) });
  }
  $("#rkModel").textContent = t("Mô hình: cây tăng cường độ dốc, học từ {n} người lớn trong {data} ({asian} người châu Á), kiểm chứng trên chu kỳ khảo sát sau và hiệu chỉnh cho người châu Á. Không cần mạng: mọi phép tính chạy trên máy này.",
    { n: fmtInt(r.model.adults), data: r.model.data, asian: fmtInt(r.model.asian_adults) });
}

/* ---------------- giấc ngủ tối nay (insights.sleep_plan): chỉ khi xem hôm nay */

function renderSleepPlan(p) {
  const card = $("#health-plan");
  card.hidden = !p || healthDate !== todayISO();
  if (card.hidden) return;
  const now = Date.now() / 1000;
  const due = now >= p.bedtime_ts && now < p.wake_ts;
  statsList($("#plStats"), [
    [t("Lên giường"), p.bedtime, due ? t("đã tới giờ") : ""],
    [t("Ngủ đủ"), fmtMinutes(p.sleep), p.extra ? t("gồm {m} bù", { m: fmtMinutes(p.extra) }) : ""],
    [t("Dậy lúc"), p.wake, p.free ? t("ngày nghỉ") : t("ngày làm việc")],
  ]);
  $("#plText").textContent = p.text;
}

const INTENSITY = [
  ["light", () => t("Nhẹ (20–99 bước/phút)"), "var(--c-int-light)"],
  ["moderate", () => t("Vừa (100–129 bước/phút)"), "var(--c-int-moderate)"],
  ["vigorous", () => t("Mạnh (từ 130 bước/phút)"), "var(--c-int-vigorous)"],
];

function renderIntensity(a) {
  const legend = $("#aiLegend");
  legend.textContent = "";
  if (!a) {
    $("#aiRatio").textContent = "—";
    $("#aiRatioLabel").textContent = "";
    hintIf($("#aiSub"), false).textContent = t("Chưa đủ dữ liệu vận động 7 ngày.");
    $("#aiDetail").textContent = "";
    emptyChart($("#aiChart"), 80, t("Chưa có dữ liệu"));
    return;
  }
  $("#aiRatio").textContent = `${a.ratio}%`;
  $("#aiRatioLabel").textContent = t("vừa + mạnh, 7 ngày");
  hintIf($("#aiSub"), true).textContent = t("Tỉ lệ cường độ vận động: phút vừa + mạnh trên tổng phút vận động.");
  hintIf($("#aiDetail"), a.level === "good").textContent = a.detail;
  for (const [key, name, color] of INTENSITY) {
    const li = mkEl("li", {}, legend);
    mkEl("i", { style: `background:${color}` }, li);
    li.append(`${name()} `);
    mkEl("b", {}, li).textContent = fmtMinutes(a[key]);
  }
  columnChart($("#aiChart"), a.days.map((d) => ({
    key: d.date, label: shortDate(d.date),
    parts: INTENSITY.map(([k, , color]) => ({ value: d[k], color })),
    tip: () => [[fmtMinutes(d.light + d.moderate + d.vigorous), longDate(d.date)], ...INTENSITY.map(([k, name, color]) => [fmtMinutes(d[k]), name(), color])],
  })), { height: 170, label: t("Phút vận động theo cường độ, 7 ngày"), empty: t("Chưa có dữ liệu"), yFmt: (v) => `${v}′` });
}

const CIRC_STATUS = { low: "good", moderate: "watch", high: "alert" };

function renderCircadian(c) {
  $("#ciLegend").textContent = "";
  $("#ciNotes").textContent = "";
  const pill = $("#ciStrain");
  pill.hidden = !c;
  if (!c) {
    hintIf($("#ciSub"), false).textContent = t("Cần ít nhất 5 đêm dữ liệu giấc ngủ.");
    statsList($("#ciStats"), []);
    emptyChart($("#ciChart"), 80, t("Chưa có dữ liệu"));
    return;
  }
  hintIf($("#ciSub"), true).textContent = t("Áp lực nhịp sinh học: {s}/100 ({label}), từ giờ ngủ {n} đêm gần nhất.", { s: c.strain, label: c.label, n: c.nights.length });
  const status = CIRC_STATUS[c.level] || "ok";
  pill.className = `score-pill lv-${status}`;
  pill.textContent = t("Áp lực");
  mkEl("b", {}, pill).textContent = String(c.strain);
  pill.append(`· ${c.label}`);
  hintIf($("#ciNotes"), !needsAttention(status));
  const stats = [];
  if (c.sjl != null) stats.push([t("Lệch múi giờ xã hội"), fmtMinutes(c.sjl), ""]);
  stats.push([t("Giữa giấc ngày nghỉ (chronotype)"), c.chronotype_clock, ""]);
  if (c.sri != null) stats.push([t("Độ đều đặn giấc ngủ (SRI)"), String(c.sri), "/100"]);
  if (c.cpd != null) stats.push([t("Độ lệch pha (CPD)"), fmtMinutes(c.cpd * 60), ""]);
  statsList($("#ciStats"), stats);
  for (const n of c.notes) mkEl("li", {}, $("#ciNotes")).textContent = n;
  for (const [cls, name] of [["bar-work", t("Đêm trước ngày làm việc")], ["bar-free", t("Đêm trước ngày nghỉ")]]) {
    const li = mkEl("li", {}, $("#ciLegend"));
    mkEl("i", { style: `background:${cls === "bar-work" ? "var(--c-deep)" : "var(--c-steps)"}` }, li);
    li.append(name);
  }
  sleepTimingChart($("#ciChart"), c);
}

/** Giờ ngủ từng đêm: cột từ lúc ngủ tới lúc dậy (trục dọc là giờ trong ngày, sớm ở trên), chấm là giữa giấc;
    đường đứt là giữa giấc trung bình ngày làm việc / ngày nghỉ. */
function sleepTimingChart(el, c) {
  const H = 230;
  const nights = c.nights;
  const { svg, w } = chartBox(el, H, t("Giờ ngủ các đêm gần đây"));
  const padL = 48, padR = 104, padT = 10, padB = 26;
  const iw = w - padL - padR, ih = H - padT - padB;
  const lo = Math.floor((Math.min(...nights.map((n) => n.start)) - 30) / 120) * 120;
  const hi = Math.ceil((Math.max(...nights.map((n) => n.end)) + 30) / 120) * 120;
  const Y = (m) => padT + ((m - lo) / (hi - lo)) * ih;
  const hm = (m) => { const v = ((Math.round(m) % 1440) + 1440) % 1440; return `${pad(Math.floor(v / 60))}:${pad(v % 60)}`; };
  for (let m = lo; m <= hi; m += 120) {
    const y = Math.round(Y(m)) + 0.5;
    sv("line", { x1: padL, x2: w - padR, y1: y, y2: y, class: "grid" }, svg);
    svText(svg, padL - 8, y + 4, hm(m), "axis", "end");
  }
  const g = sv("g", { class: "ci-chart" }, svg);
  const slot = iw / nights.length;
  const bw = Math.max(3, Math.min(14, slot * 0.6));
  const every = Math.max(1, Math.ceil(nights.length / Math.max(2, Math.floor(iw / 56))));
  nights.forEach((n, i) => {
    const x = padL + i * slot + (slot - bw) / 2;
    sv("rect", { x, y: Y(n.start), width: bw, height: Math.max(2, Y(n.end) - Y(n.start)), rx: Math.min(4, bw / 2), class: n.free ? "bar-free" : "bar-work" }, g);
    sv("circle", { cx: x + bw / 2, cy: Y(n.mid), r: 3.5, class: "mid" }, g);
    if (i % every === 0) svText(svg, padL + i * slot + slot / 2, H - 8, shortDate(n.date), "axis", "middle");
    const hit = sv("rect", { x: padL + i * slot, y: padT, width: slot, height: ih, class: "hit" }, svg);
    hoverable(hit, () => [[`${hm(n.start)} – ${hm(n.end)}`, longDate(n.date)], [hm(n.mid), t("Giữa giấc")],
      [n.free ? t("Đêm trước ngày nghỉ") : t("Đêm trước ngày làm việc"), ""]]);
  });
  const ref = (m, cls, name, labelY) => {
    const y = Math.round(Y(m)) + 0.5;
    sv("line", { x1: padL, x2: w - padR + 4, y1: y, y2: y, class: cls }, g);
    svText(svg, w - padR + 8, labelY - 2, name, "ref-name");
    svText(svg, w - padR + 8, labelY + 11, hm(m), "ref-label");
  };
  // hai nhãn gần nhau thì tách ra (ngày làm ở trên, ngày nghỉ ở dưới) để không chồng chữ
  const yw = c.msw != null ? Y(c.msw) : null, yf = c.msf != null ? Y(c.msf) : null;
  let lw = yw, lf = yf;
  if (yw != null && yf != null && Math.abs(yw - yf) < 30) {
    const mid = (yw + yf) / 2;
    [lw, lf] = c.msw <= c.msf ? [mid - 15, mid + 15] : [mid + 15, mid - 15];
  }
  if (yw != null) ref(c.msw, "ref-work", t("Ngày làm"), lw);
  if (yf != null) ref(c.msf, "ref-free", t("Ngày nghỉ"), lf);
}

/** Hiện đúng thẻ của trang Sức khỏe: thẻ Chu kỳ / Sinh lý theo giới tính trong hồ sơ; Tập luyện không cần chọn ngày. */
function showHealthTab() {
  if (!tabAllowed(healthTab)) healthTab = "sleep";
  $$(".htabs button").forEach((b) => {
    b.hidden = !tabAllowed(b.dataset.htab);
    b.setAttribute("aria-selected", String(b.dataset.htab === healthTab));
  });
  $$("#page-health .hpanel").forEach((el) => (el.hidden = el.id !== `htab-${healthTab}`));
  $("#hDayNav").hidden = healthTab === "workouts" || healthTab === "body";   // hai thẻ này không theo ngày đang xem
}

function renderHealth() {
  const H = healthData;
  renderDateNav();
  showHealthTab();
  $("#hEmpty").hidden = !!H?.has_data;
  const draw = { sleep: renderSleepTab, activity: renderActivityTab, heart: renderHeartTab, body: renderBodyTab, workouts: renderWorkoutsTab,
    cycle: renderCycleTab, intimacy: renderIntimacyTab, trends: renderTrendsTab, insights: renderInsightsTab }[healthTab];
  draw?.(H);
  refreshHints();
}

const dayLabelOf = () => (healthDate === todayISO() ? t("Hôm nay") : longDate(healthDate));
const dayBounds = () => { const t0 = new Date(`${healthDate}T00:00:00`).getTime() / 1000; return [t0, t0 + 86400]; };

function renderSleepTab(H) {
  const sl = H?.day?.sleep;
  const night = H?.insights?.last_night;
  renderSleepPlan(H?.insights?.sleep_plan);
  $("#health-sleep h2").textContent = healthDate === todayISO() ? t("Giấc ngủ đêm qua") : t("Giấc ngủ");
  $("#slRange").textContent = sl ? t("Ngủ lúc {start}, dậy lúc {end}", { start: hhmm(sl.start), end: hhmm(sl.end) })
    : t("Không có giấc ngủ kết thúc vào {day}.", { day: dayLabelOf().toLowerCase() });
  scorePill($("#slScore"), sl && night ? night.score : null);
  const inBed = sl ? sl.minutes + sl.awake : 0;
  statsList($("#slStats"), sl ? [
    [t("Thời gian ngủ"), fmtMinutes(sl.minutes), ""],
    [t("Ngủ sâu"), String(Math.round((sl.deep * 100) / sl.minutes)), "%"],
    [t("Liền mạch"), String(Math.round((sl.minutes * 100) / inBed)), "%"],
    ...(night?.hr ? [[t("Nhịp tim khi ngủ"), String(night.hr), t("nhịp/phút")]] : []),
  ] : []);
  const hasRem = (H?.sleep_days || []).some((d) => d.rem > 0);   // Mi Band 6 không ghi REM: chỉ có khi ứng dụng ước tính
  const remName = H?.insights?.rem_estimated || sl?.rem_estimated ? () => t("REM (ước tính)") : () => t("REM");
  const rows = STAGES.filter(([key]) => key !== "rem" || hasRem).map(([k, name, c]) => [k, k === "rem" ? remName : name, c]);
  if (sl) sleepChart($("#slChart"), sl, rows); else emptyChart($("#slChart"), 60, t("Chưa có dữ liệu giấc ngủ cho ngày này."));
  const legend = $("#slLegend");
  legend.textContent = "";
  for (const [key, name, color] of rows) {
    const li = mkEl("li", {}, legend);
    mkEl("i", { style: `background:${color}` }, li);
    li.append(`${name()} `);
    mkEl("b", {}, li).textContent = sl ? fmtMinutes(sl[key]) : "—";
  }
  $("#slNotes").textContent = night?.notes?.length ? t("Lưu ý: {notes}.", { notes: night.notes.join("; ") }) : "";
  hintIf($("#slNotes"), !(night && needsAttention(scoreStatus(night.score))));
  renderSleepReference(sl, H?.sleep_check);
  const days = H?.sleep_days || [];
  const slept = days.filter((d) => d.minutes);
  const avgSleep = slept.length ? slept.reduce((a, d) => a + d.minutes, 0) / slept.length : 0;
  columnChart($("#slHistory"), days.map((d) => ({
    key: d.date, label: shortDate(d.date),
    parts: [["deep", d.deep], ["light", d.light], ["rem", d.rem]].map(([k, v]) => ({ value: v / 60, color: stageInfo(k)[2] })),
    tip: () => [[fmtMinutes(d.minutes), longDate(d.date)], ...["deep", "light", "rem", "awake"].filter((k) => k !== "rem" || hasRem).map((k) => [fmtMinutes(d[k]), stageInfo(k)[1](), stageInfo(k)[2]])],
  })), {
    height: 210, label: t("Thời gian ngủ 14 ngày gần đây"), empty: t("Chưa có dữ liệu giấc ngủ."), yFmt: (v) => `${v}h`,
    selected: healthDate, valueFmt: (v) => fmtMinutes(v * 60),
    band: { from: 7, to: 9, label: t("Khuyến nghị 7–9 giờ") },
    refs: avgSleep ? [{ value: avgSleep / 60, name: t("Trung bình"), text: fmtMinutes(avgSleep) }] : [],
  });
  renderCircadian(H?.insights?.circadian);
}

/** Giấc ngủ của Mi Fitness cùng đêm (nếu đã lấy từ tài khoản) và độ khớp của thuật toán với Mi Fitness. */
function renderSleepReference(sl, check) {
  const ref = sl?.reference;
  const el = $("#slRef");
  el.hidden = !ref;
  el.textContent = "";
  if (ref) {
    const parts = [t("{start}–{end}", { start: hhmm(ref.start), end: hhmm(ref.end) }), fmtMinutes(ref.minutes)];
    if (ref.deep != null) parts.push(t("ngủ sâu {t}", { t: fmtMinutes(ref.deep) }));
    if (ref.rem) parts.push(t("REM {t}", { t: fmtMinutes(ref.rem) }));
    if (ref.score) parts.push(t("điểm {n}", { n: ref.score }));
    mkEl("b", {}, el).textContent = t("Mi Fitness:");
    el.append(` ${parts.join(" · ")}. `);
    el.append(sl.stage_source === "mifitness" ? t("Ứng dụng dùng đúng số phút ngủ sâu của Mi Fitness (cả REM khi Mi Fitness có REM); vị trí trên biểu đồ, giờ ngủ, giờ dậy và các lần thức do ứng dụng tính.") : "");
  }
  const v = check?.validation;
  const c = $("#slCheck");
  c.hidden = !v && !(sl && sl.stage_source === "calibrated");
  const lines = [];
  if (v) {
    lines.push(t("Thuật toán so với Mi Fitness ({n} đêm, chưa hiệu chỉnh): giờ ngủ lệch trung bình {a} phút, giờ dậy {b} phút, thời lượng {c} phút, ngủ sâu {d} phút.",
      { n: v.nights, a: fmtMin1(v.start), b: fmtMin1(v.end), c: fmtMin1(v.minutes), d: fmtMin1(v.deep) }));
  }
  if (sl?.stage_source === "calibrated" && check?.calibration) {
    lines.push(t("Đêm này chưa có báo cáo Mi Fitness: ngủ sâu, REM theo tỉ lệ học từ {n} đêm Mi Fitness gần nhất.", { n: check.calibration.nights }));
  }
  c.textContent = lines.join(" ");
}
const fmtMin1 = (x) => (x == null ? "—" : Number(x).toLocaleString(LOCALE, { maximumFractionDigits: 1 }));

/* ---------------- Xu hướng: thay đổi gần đây, 7 ngày qua, hôm nay so với thường lệ (trends.py) */

const TREND_COLOR = { sleep: "var(--c-rem)", bedtime: "var(--c-rem)", wake: "var(--c-rem)", deep: "var(--c-deep)",
  sleep_hr: "var(--c-hr)", steps: "var(--c-steps)", calories: "var(--c-awake)", active: "var(--c-light)", stress: "var(--c-stress)" };
const TREND_STATUS = { good: "good", watch: "watch", neutral: "ok" };

function renderTrendsTab(H) {
  const tr = H?.trends;
  const changes = tr?.changes || [];
  hintIf($("#trSub"), !!tr).textContent = tr ? t("Trong 30 ngày và 26 tuần tới {day}.", { day: dayLabelOf().toLowerCase() }) : t("Chưa có dữ liệu");
  const counts = $("#trCounts");
  counts.textContent = "";
  if (changes.length) {   // không có thay đổi: câu bên dưới đã nói, không cần ba số 0
    const add = (n, label) => { if (!n) return; const s = mkEl("span", {}, counts); mkEl("b", {}, s).textContent = String(n); s.append(` ${label}`); };
    add(changes.length, t("thay đổi"));
    add(tr.counts.watch, t("mục nên chú ý"));
    add(tr.counts.good, t("mục tốt"));
  }
  const list = $("#trChanges");
  list.textContent = "";
  if (tr && !changes.length) mkEl("p", { class: "tr-empty" }, list).textContent = t("Không có thay đổi rõ: các chỉ số vẫn quanh mức thường lệ của bạn.");
  for (const c of changes) list.append(trendCard(c, c.scope === "weeks"
    ? [t("Trung bình {n} tuần trước đó", { n: c.base_n }), t("Trung bình {n} tuần gần đây", { n: c.recent_n })]
    : [t("Trung bình {n} ngày trước đó", { n: c.base_n }), t("Trung bình {n} ngày gần đây", { n: c.recent_n })], t("so với trước đó")));
  const hl = $("#trHighlights");
  hl.textContent = "";
  for (const h of tr?.highlights || []) hl.append(trendCard(h, h.key === "wake" ? null : [t("7 ngày trước đó"), t("7 ngày qua")], t("so với 7 ngày trước đó")));
  const today = $("#trToday");
  today.textContent = "";
  for (const u of tr?.today || []) today.append(usualCard(u));
  if (tr && !(tr.today || []).length) mkEl("p", { class: "tr-empty" }, today).textContent = t("Cần ít nhất 7 ngày đeo vòng trước đó để so.");
}

/** Đầu thẻ một chỉ số: trạng thái, tên, số chính thật lớn kèm chênh lệch nhỏ; câu đầy đủ nằm trong phần giải thích. */
function trendHead(card, item, value, note) {
  card.dataset.status = item.status === "neutral" ? "ok" : item.status;
  const [label, icon] = STATUS[TREND_STATUS[item.status] || "ok"];
  const chipEl = mkEl("span", { class: "ins-status" }, card);
  mkEl("b", {}, chipEl).textContent = icon;
  chipEl.append(item.status === "neutral" ? t("Bình thường") : label());
  mkEl("h3", {}, card).textContent = item.title;
  const v = mkEl("p", { class: "tr-value" }, card);
  v.textContent = value;
  if (note) mkEl("span", { class: "tr-delta" }, v).textContent = note;
  mkEl("p", { class: "tr-text hint" }, card).textContent = item.text;
}

/** Chênh lệch giữa phần gần đây và phần trước đó, có dấu (giờ đi ngủ / thức dậy tính bằng phút). */
function trendDelta(item) {
  if (item.base == null) return "";
  const d = item.recent - item.base;
  const txt = item.unit === "clock" || item.unit === "min" ? fmtMinutes(Math.abs(d)) : trendValue(item, Math.abs(d));
  return `${Math.round(d) === 0 ? "±" : d > 0 ? "+" : "−"}${txt}`;
}

/** Thẻ một chỉ số: cột từng ngày / tuần (phần trước xám, phần gần đây có màu) và đường trung bình mỗi phần. */
function trendCard(item, footer, vs) {
  const card = mkEl("div", { class: "insight tr-item" });
  // giờ thức dậy: độ lệch quanh giờ dậy trung bình (độ đều đặn), không phải chênh lệch với tuần trước
  const delta = item.key === "wake" ? `±${fmtMinutes(item.sd ?? 0)}` : trendDelta(item);
  trendHead(card, item, item.recent_text, item.key !== "wake" && delta && vs ? `${delta} ${vs}` : delta);
  const box = mkEl("div", { class: "chart" }, card);
  requestAnimationFrame(() => trendChart(box, item));
  if (footer) {
    const f = mkEl("div", { class: "tr-foot hint" }, card);
    mkEl("span", {}, f).textContent = item.base_text ? `${footer[0]}: ${item.base_text}` : "";
    mkEl("span", {}, f).textContent = `${footer[1]}: ${item.recent_text}`;
  }
  return card;
}

function trendChart(el, item) {
  const pts = item.series || [];
  const H = 96, top = 14, bottom = 14;
  const { svg, w } = chartBox(el, H, item.title);
  const vals = pts.map((p) => p.value).filter((v) => v != null);
  if (!vals.length) { svText(svg, w / 2, H / 2, t("Chưa có dữ liệu"), "empty-msg", "middle"); return; }
  const color = TREND_COLOR[item.key] || "var(--accent)";
  const line = item.unit === "clock";   // giờ đi ngủ / thức dậy: đường nối các điểm
  let lo = line ? Math.min(...vals) : 0, hi = Math.max(...vals, item.base ?? 0, item.recent ?? 0);
  if (line) { lo = Math.min(lo, item.base ?? lo, item.recent ?? lo) - 15; hi += 15; }
  const Y = (v) => top + (H - top - bottom) * (1 - (v - lo) / Math.max(1e-9, hi - lo));
  const step = w / pts.length;
  const X = (i) => step * i + step / 2;
  const recentFrom = pts.findIndex((p) => p.recent);
  if (line) {
    let d = "";
    pts.forEach((p, i) => { if (p.value != null) d += `${d ? "L" : "M"}${X(i)},${Y(p.value)}`; });
    sv("path", { d, fill: "none", stroke: color, "stroke-width": 2, opacity: 0.8 }, svg);
    pts.forEach((p, i) => {
      if (p.value == null) return;
      const c = sv("circle", { cx: X(i), cy: Y(p.value), r: 3.5, fill: "var(--surface)", stroke: p.recent || recentFrom < 0 ? color : "var(--muted)", "stroke-width": 2 }, svg);
      hoverable(c, () => [[trendValue(item, p.value), trendLabel(item, p.label)]]);
    });
  } else {
    const bw = Math.max(2, Math.min(18, step * 0.62));
    pts.forEach((p, i) => {
      if (p.value == null) return;
      const y = Y(p.value);
      const r = sv("rect", { x: X(i) - bw / 2, y, width: bw, height: Math.max(2, H - bottom - y), rx: Math.min(4, bw / 2),
        class: p.recent || recentFrom < 0 ? "mark" : "mark tr-base" }, svg);
      if (p.recent || recentFrom < 0) r.setAttribute("fill", color);
      hoverable(r, () => [[trendValue(item, p.value), trendLabel(item, p.label)]]);
    });
  }
  const avg = (v, from, to, cls) => {
    if (v == null) return;
    sv("line", { x1: X(from) - step / 2 + 2, x2: X(to) + step / 2 - 2, y1: Y(v), y2: Y(v), class: `tr-avg ${cls}`,
      stroke: cls === "recent" ? color : "var(--muted)" }, svg);
  };
  if (recentFrom > 0) {
    avg(item.base, 0, recentFrom - 1, "base");
    avg(item.recent, recentFrom, pts.length - 1, "recent");
  } else {
    avg(item.recent, 0, pts.length - 1, "recent");
  }
  svText(svg, 0, H - 1, trendLabel(item, pts[0].label), "axis");
  svText(svg, w, H - 1, trendLabel(item, pts[pts.length - 1].label), "axis", "end");
}

function trendValue(item, v) {
  if (item.unit === "clock") { const m = ((Math.round(v) % 1440) + 1440) % 1440; return `${pad(Math.floor(m / 60))}:${pad(m % 60)}`; }
  if (item.unit === "min") return fmtMinutes(v);
  if (item.unit === "pct") return `${Math.round(v)}%`;
  if (item.unit === "bpm") return t("{n} nhịp/phút", { n: Math.round(v) });
  if (item.unit === "steps") return t("{n} bước", { n: fmtInt(Math.round(v)) });
  if (item.unit === "kcal") return `${fmtInt(Math.round(v))} kcal`;
  return fmtInt(Math.round(v));
}
const trendLabel = (item, label) => (item.scope === "weeks" ? t("Tuần từ {d}", { d: shortDate(label) }) : shortDate(label));

/** Hôm nay so với thường lệ: đường cộng dồn thường lệ (cả ngày, xám) và hôm nay tới giờ này (có màu). */
function usualCard(u) {
  const card = mkEl("div", { class: "insight tr-item" });
  trendHead(card, u, u.now_text, t("Thường lệ: {v}", { v: u.usual_text }));
  const box = mkEl("div", { class: "chart" }, card);
  requestAnimationFrame(() => usualChart(box, u));
  return card;
}

function usualChart(el, u) {
  const H = 110, top = 16, bottom = 16;
  const { svg, w } = chartBox(el, H, u.title);
  const color = TREND_COLOR[u.key];
  const hi = Math.max(1, ...u.usual_curve, ...u.today);
  const X = (q) => (w * q) / 96;
  const Y = (v) => top + (H - top - bottom) * (1 - v / hi);
  const path = (vals) => vals.map((v, q) => `${q ? "L" : "M"}${X(q + 1)},${Y(v)}`).join("");
  sv("path", { d: path(u.usual_curve), class: "tr-usual" }, svg);
  sv("path", { d: path(u.today), class: "tr-now", stroke: color }, svg);
  const x = X(u.upto), y = Y(u.now);
  sv("line", { x1: x, x2: x, y1: top - 6, y2: H - bottom, class: "crosshair" }, svg);
  sv("circle", { cx: x, cy: y, r: 4.5, fill: color }, svg);
  svText(svg, Math.min(w - 4, x + 6), Math.max(12, y - 6), trendValue(u, u.now), "value-label");
  svText(svg, 0, H - 1, "0:00", "axis");
  svText(svg, w, H - 1, "24:00", "axis", "end");
  hoverable(sv("rect", { x: 0, y: 0, width: w, height: H, class: "hit" }, svg),
    () => [[trendValue(u, u.now), t("Hôm nay")], [trendValue(u, u.usual_curve[u.upto - 1]), t("Thường lệ cùng giờ")]]);
}

function renderActivityTab(H) {
  const isToday = healthDate === todayISO();
  const goal = Number(STATE.profile?.goal || 8000);
  const liveSteps = isToday && STATE.connected ? STATE.live?.activity?.steps : null;
  const day = H?.day;
  const steps = Math.max(day?.steps ?? 0, liveSteps ?? 0);
  $("#stTotal").textContent = fmtInt(steps);
  $("#stSub").textContent = t("{p}% mục tiêu {goal} bước", { p: Math.round((steps / goal) * 100), goal: fmtInt(goal) });
  columnChart($("#stHourly"), (day?.steps_hourly || []).map((v, h) => ({
    key: h, label: h % 3 === 0 ? `${pad(h)}:00` : "", parts: [{ value: v, color: "var(--c-steps)" }],
    tip: () => [[t("{n} bước", { n: fmtInt(v) }), `${pad(h)}:00–${pad((h + 1) % 24)}:00`]],
  })), { height: 180, label: t("Bước chân theo giờ"), empty: t("Không có bước chân nào được ghi trong ngày này."), valueFmt: fmtInt });
  const days = (H?.steps_days || []).map((d) => ({ ...d }));
  if (liveSteps != null) {
    const today = days.find((d) => d.date === healthDate);
    if (today) today.steps = Math.max(today.steps, liveSteps); else days.push({ date: healthDate, steps: liveSteps });
  }
  columnChart($("#stHistory"), days.map((d) => ({
    key: d.date, label: shortDate(d.date), parts: [{ value: d.steps, color: "var(--c-steps)" }],
    tip: () => [[t("{n} bước", { n: fmtInt(d.steps) }), longDate(d.date)], [d.steps >= goal ? t("Đạt mục tiêu") : t("Chưa đạt mục tiêu"), ""]],
  })), {
    height: 210, label: t("Bước chân mỗi ngày"), empty: t("Chưa có lịch sử bước chân."), selected: healthDate,
    valueFmt: fmtInt, refs: [{ value: goal, name: t("Mục tiêu"), text: fmtInt(goal) }],
  });
  tableRows($("#stTable"), days.slice().reverse().map((d) => [longDate(d.date), fmtInt(d.steps)]), t("Chưa có dữ liệu"), 2);
  renderIntensity(H?.insights?.intensity);
  const pai = H?.pai || { latest: null, days: [] };
  if (pai.latest) statsList($("#paiStats"), [[t("Tổng 7 ngày"), fmtInt(Math.round(pai.latest.total)), ""], [t("Thêm hôm đó"), `+${fmtInt(Math.round(pai.latest.today))}`, ""]]);
  else statsList($("#paiStats"), []);
  columnChart($("#paiChart"), pai.days.map((d) => ({
    key: d.date, label: shortDate(d.date), parts: [{ value: d.total, color: "var(--c-pai)" }],
    tip: () => [[`${fmtInt(Math.round(d.total))} PAI`, longDate(d.date)], [`+${fmtInt(Math.round(d.today))}`, t("trong ngày")]],
  })), {
    height: 200, label: t("PAI các ngày gần đây"), empty: t("Chưa có dữ liệu PAI."), valueFmt: (v) => fmtInt(Math.round(v)),
    refs: [{ value: 100, name: t("Mục tiêu"), text: "100" }],
  });
}

/** Số đo nhịp tim trực tiếp vào biểu đồ Tim mạch của hôm nay ngay lúc đo, không chờ lần đồng bộ vòng tay: phút đang đo
    gộp tại chỗ từ từng số đo (exact = false), phút đã trọn do server gửi (hr_minute, exact = true). Điểm trực tiếp có
    phần tử thứ ba = 1, như server trả về; phút đã có số của vòng tay thì giữ số của vòng tay. */
const liveMinute = { ts: 0, sum: 0, n: 0 };
let liveRedrawAt = 0;
function liveHrToHealth(ts, bpm, exact = false) {
  const day = healthData?.day;
  if (!day || healthData.date !== todayISO() || !(bpm >= 30 && bpm <= 220)) return;
  const minute = ts - (ts % 60);
  let value = bpm;
  if (!exact) {
    if (liveMinute.ts !== minute) Object.assign(liveMinute, { ts: minute, sum: 0, n: 0 });
    liveMinute.sum += bpm;
    liveMinute.n += 1;
    value = Math.round(liveMinute.sum / liveMinute.n);
  }
  const hr = day.hr || (day.hr = []);
  const i = hr.findIndex((p) => p[0] >= minute);
  if (i >= 0 && hr[i][0] === minute) {
    if (hr[i][2] !== 1) return;   // phút đã có số của vòng tay
    hr[i] = [minute, value, 1];
  } else {
    hr.splice(i < 0 ? hr.length : i, 0, [minute, value, 1]);
    day.hr_live = (day.hr_live || 0) + 1;
  }
  if (!$("#page-health").hidden && healthTab === "heart" && Date.now() - liveRedrawAt > 3000) {
    liveRedrawAt = Date.now();
    renderHeartTab(healthData);
  }
}

/** Trung bình theo thời gian: mỗi số đo đại diện cho khoảng tới số đo kế tiếp, tối đa 10 phút (như tải TRIMP), để một
    lúc theo dõi trực tiếp (mỗi phút một số) không lấn át cả ngày đo 10 phút một lần. */
function timeMean(points) {
  let sum = 0, weight = 0;
  points.forEach((p, i) => {
    const w = Math.min(600, Math.max(60, (points[i + 1]?.[0] ?? p[0] + 60) - p[0]));
    sum += p[1] * w;
    weight += w;
  });
  return weight ? sum / weight : null;
}

function renderHeartTab(H) {
  const [t0, t1] = dayBounds();
  const day = H?.day || { hr: [], stress: [] };
  const sl = day.sleep;
  const night = H?.insights?.last_night;
  const hr = day.hr || [];
  const hrQuality = H?.quality?.hr?.counts;
  const hrFlagged = (hrQuality?.suspect || 0) + (hrQuality?.invalid || 0) > 0;
  $("#hrBadge").textContent = hrFlagged ? t("Cần kiểm tra tín hiệu") : day.hr_live ? t("Gồm số đo trực tiếp")
    : hr.length ? t("Dữ liệu đã đồng bộ") : t("Chưa có dữ liệu");
  $("#hrBadge").classList.toggle("quality-attention", hrFlagged);
  const stats = [];
  if (hr.length) {
    const v = hr.map((p) => p[1]);
    stats.push([t("Thấp nhất"), fmtInt(Math.min(...v)), t("nhịp/phút")], [t("Trung bình"), fmtInt(Math.round(timeMean(hr))), t("nhịp/phút")], [t("Cao nhất"), fmtInt(Math.max(...v)), t("nhịp/phút")]);
  }
  if (night?.hr) {
    const d = night.hr_baseline != null ? Math.round(night.hr - night.hr_baseline) : null;
    stats.push([t("Nhịp tim nghỉ (khi ngủ)"), String(night.hr), d ? `${t("nhịp/phút")} (${d > 0 ? "+" : ""}${d})` : t("nhịp/phút")]);
  }
  statsList($("#hrStats"), stats);
  lineChart($("#hrChart"), hr, {
    t0, t1, color: "var(--c-hr)", unit: t("nhịp/phút"), label: t("Nhịp tim trong ngày"), xTicks: dayTicks(t0), extremes: true,
    shade: [sl, ...(day.naps || [])].filter(Boolean).map((s) => ({ from: s.start, to: s.end, label: t("Ngủ") })),
    empty: t("Không có số đo nhịp tim trong ngày này."),
  });
  const stress = day.stress || [];
  const autoS = stress.filter((s) => s[2]).map((s) => [s[0], s[1]]);
  const manualS = stress.filter((s) => !s[2]).map((s) => [s[0], s[1]]);
  const sv_ = stress.map((s) => s[1]);
  if (sv_.length) {
    const avg = Math.round(sv_.reduce((a, b) => a + b, 0) / sv_.length);
    statsList($("#ssStats"), [[t("Trung bình"), String(avg), stressLabel(avg)], [t("Cao nhất"), String(Math.max(...sv_)), ""]]);
  } else statsList($("#ssStats"), []);
  lineChart($("#ssChart"), autoS, {
    t0, t1, yMin: 0, yMax: 100, yStep: 20, color: "var(--c-stress)", unit: "", dots: manualS, gap: 1800, xTicks: dayTicks(t0),
    zones: [{ from: 80, to: 100, label: t("Cao"), tint: true }, { from: 60, to: 80, label: t("Trung bình") },
      { from: 40, to: 60, label: t("Bình thường"), tint: true }, { from: 0, to: 40, label: t("Thư giãn") }],
    label: t("Mức căng thẳng trong ngày"),
    empty: manualS.length ? t("Chỉ có lần đo tay.") : t("Không có số đo căng thẳng. Bật Theo dõi căng thẳng trong Cài đặt vòng tay → Sức khỏe."),
  });
  const sp = H?.spo2_recent || [];
  const spQuality = H?.quality?.spo2?.counts;
  const spFlagged = (spQuality?.suspect || 0) + (spQuality?.invalid || 0) > 0;
  $("#spBadge").textContent = spFlagged ? t("Cần kiểm tra tín hiệu") : sp.length ? t("Đo từng lần") : t("Chưa có dữ liệu");
  $("#spBadge").classList.toggle("quality-attention", spFlagged);
  if (sp.length) statsList($("#spStats"), [[t("Lần đo gần nhất · {when}", { when: dateTime(sp[0][0]) }), String(sp[0][1]), "%"]]);
  else statsList($("#spStats"), []);
  tableRows($("#spTable"), sp.map(([ts, v, auto]) => [dateTime(ts), `${v}%`, auto ? t("Tự động") : t("Đo tay")]), t("Chưa có lần đo SpO2 nào. Đo trên vòng tay rồi đồng bộ lại."), 3);
  // cách vòng tay đang đo (chỉ biết khi đã lưu từ ứng dụng này)
  const s = STATE.settings || {};
  const unknown = t("Chưa đồng bộ");
  const facts = [
    `${t("Nhịp tim")}: ${s.hr_interval == null ? unknown : hrIntervalLabel(s.hr_interval)}`,
    `${t("Căng thẳng")}: ${s.stress == null ? unknown : s.stress ? t("Bật") : t("Tắt")}`,
    `SpO2: ${t("Đo trên vòng tay")}`,
  ];
  $("#measureFacts").textContent = `${t("Đo tự động")} · ${facts.join(" · ")}. ${t("Mi Band 6 chỉ đo SpO2 khi bạn mở mục SpO2 trên vòng tay và bấm đo; kết quả hiện ở đây sau lần đồng bộ kế tiếp. Đổi chu kỳ đo ở Cài đặt vòng tay → Sức khỏe.")}`;
}

/* ---------------- cơ thể: cân nặng, chiều cao theo thời gian (personal.body_trend) */

const BODY_SOURCE = { app: () => t("Ứng dụng này"), mifitness: () => "Mi Fitness", profile: () => t("Hồ sơ") };
let bodyFormFor = null;   // lần ghi đã điền sẵn vào ô nhập: không điền lại khi số liệu không đổi
const kgText = (v) => `${fmtDec(v, 1)} kg`;
const signedKg = (v) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${fmtDec(Math.abs(v), 1)} kg`;

function renderBodyTab(H) {
  const body = H?.body || { entries: [], trend: null };
  const tr_ = body.trend;
  $("#bdWeight").textContent = tr_ ? kgText(tr_.weight) : "";
  $("#bdWeight").hidden = !tr_;
  $("#bdSub").textContent = tr_
    ? [t("Lần ghi gần nhất: {when}", { when: longDate(tr_.date) }), tr_.height ? t("chiều cao {n} cm", { n: fmtInt(tr_.height) }) : ""].filter(Boolean).join(" · ")
    : "";   // biểu đồ trống đã nói chưa có lần ghi
  $("#health-body-log").hidden = !body.entries.length;
  const pill = $("#bdBmi");
  pill.hidden = !tr_?.bmi;
  if (tr_?.bmi) {
    pill.className = `score-pill lv-${tr_.bmi_status}`;
    pill.textContent = "BMI ";
    mkEl("b", {}, pill).textContent = fmtDec(tr_.bmi, 1);
    pill.append(` · ${tr_.bmi_label}`);
  }
  const stats = [];
  if (tr_?.change_30) stats.push([t("So với 30 ngày trước"), signedKg(tr_.change_30.kg), ""]);
  if (tr_?.change_90) stats.push([t("So với 90 ngày trước"), signedKg(tr_.change_90.kg), ""]);
  if (tr_?.rate != null) stats.push([t("Xu hướng"), `${tr_.rate > 0 ? "+" : tr_.rate < 0 ? "−" : ""}${fmtDec(Math.abs(tr_.rate), 2)}`, t("kg/tuần")]);
  statsList($("#bdStats"), stats);
  $("#bdNotes").textContent = tr_?.notes?.length ? tr_.notes.join(" ")
    : body.entries.length ? t("Ghi cân nặng thêm vài lần, cách nhau ít nhất 2 tuần, để xem xu hướng.") : "";
  $("#bdNotes").className = `journal-effect${tr_ && tr_.status !== "good" ? ` warn lv-${tr_.status}` : ""}`;
  hintIf($("#bdNotes"), !(tr_?.notes?.length && tr_.status !== "good"));   // chỉ cảnh báo xu hướng luôn hiện
  const pts = body.entries.filter((e) => e.weight).map((e) => [new Date(`${e.date}T12:00:00`).getTime() / 1000, e.weight]);
  const now = Date.now() / 1000;
  const t0 = Math.min(pts[0]?.[0] ?? now, now - 30 * 86400);
  lineChart($("#bdChart"), pts, {
    t0, t1: now + 86400, color: "var(--sky)", unit: "kg", dots: pts, gap: 1e12, height: 200, label: t("Cân nặng theo thời gian"),
    timeFmt: (ts) => longDate(isoOf(new Date(ts * 1000))), xTicks: [[t0, shortDate(isoOf(new Date(t0 * 1000)))], [now, t("Hôm nay")]],
    yMin: pts.length ? Math.floor(Math.min(...pts.map((p) => p[1])) - 3) : undefined,
    empty: t("Chưa có lần ghi nào. Ghi cân nặng để theo dõi xu hướng."),
  });
  const key = `${tr_?.date}|${tr_?.weight}|${tr_?.height}`;
  if (bodyFormFor !== key) {   // điền sẵn hôm nay và số mới nhất
    bodyFormFor = key;
    $("#bdDate").value = todayISO();
    $("#bdDate").max = todayISO();
    $("#bdKg").value = tr_?.weight ?? STATE.profile?.weight ?? "";
    $("#bdCm").value = tr_?.height ?? STATE.profile?.height ?? "";
  }
  const rows = body.entries.slice().reverse();
  tableRows($("#bdTable"), rows.map((e) => [longDate(e.date), e.weight ? kgText(e.weight) : "—",
    e.height ? `${fmtInt(e.height)} cm` : "—", (BODY_SOURCE[e.source] || (() => e.source || "—"))(), ""]),
  t("Chưa có lần ghi nào. Ghi cân nặng để theo dõi xu hướng."), 5);
  $$("#bdTable tr").forEach((row, i) => {
    const e = rows[i];
    if (!e) return;
    const b = mkEl("button", { type: "button", class: "icon-btn", "aria-label": t("Xóa lần ghi ngày {day}", { day: longDate(e.date) }) }, row.lastElementChild);
    b.innerHTML = '<svg class="ic"><use href="#i-trash"/></svg>';
    b.onclick = () => quiet(saveBody({ date: e.date, delete: true }));
  });
}

async function saveBody(data) {
  const r = await run($("#bdSaveBtn"), () => api("/api/body", data), data.delete ? t("Đã xóa lần ghi.") : t("Đã lưu cân nặng."));
  STATE.profile = r.state.profile;
  bodyFormFor = null;
  await loadHealth();
}
$("#bdSaveBtn").onclick = () => {
  const kg = Number($("#bdKg").value);
  if (!$("#bdDate").value || !(kg >= 20 && kg <= 250)) {
    toast(t("Nhập cân nặng từ 20 đến 250 kg."), true);
    $("#bdKg").focus();
    return;
  }
  quiet(saveBody({ date: $("#bdDate").value, weight: kg, height: $("#bdCm").value ? Number($("#bdCm").value) : null }));
};

function renderWorkoutsTab(H) {
  const workouts = H?.workouts || [];
  $("#woSub").textContent = t("{n} buổi tập", { n: workouts.length });
  tableRows($("#woTable"), workouts.map((w) => [
    workoutName(w), dateTime(w.start), fmtMinutes(((w.active_seconds || (w.end - w.start)) / 60)),
    w.distance ? `${fmtDec(w.distance / 1000)} km` : "—", w.calories ? `${fmtInt(w.calories)} kcal` : "—",
    w.avg_hr ? t("{n} nhịp/phút", { n: w.avg_hr }) : "—", w.steps ? fmtInt(w.steps) : "—",
    w.source === "mifitness" ? "Mi Fitness" : t("Vòng tay"), "",
  ]), t("Chưa có buổi tập nào. Bấm Lấy lịch sử từ Mi Fitness để lấy các buổi cũ."), 9);
  // nút Bản đồ cho buổi chạy / đạp xe ngoài trời có lộ trình GPS (Mi Fitness ghi từ GPS của điện thoại)
  const anyGps = workouts.some((w) => w.gps);
  $("#woMapAllBtn").hidden = !anyGps;
  $(".wo-table").classList.toggle("no-map", !anyGps);   // không buổi nào có lộ trình: bỏ cột Bản đồ
  $$("#woTable tr").forEach((tr, i) => {
    const w = workouts[i];
    if (!w?.gps) return;   // không có lộ trình GPS (bài tập trong nhà, hoặc tệp lộ trình trống): không có nút
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn small wo-map";
    b.innerHTML = '<svg class="ic"><use href="#i-route"/></svg><span></span>';
    $("span", b).textContent = t("Bản đồ");
    b.onclick = () => openMap(w);
    tr.lastElementChild.append(b);
  });
}

function renderInsightsTab(H) {
  renderAnalysis(H?.analysis);
  const ins = H?.insights;
  renderReadiness(ins?.readiness, ins?.readiness_history || [], ins?.readiness_progress, ins?.readiness_night);
  renderMind(ins?.mental, ins?.data_until);
  renderBody(ins?.body);
  renderRisk(ins?.risk);
}

/* ---------------- nhật ký riêng: chu kỳ kinh nguyệt (hồ sơ nữ), xuất tinh (hồ sơ nam). Chỉ lưu trên máy này. */

const PHASES = {
  menstrual: () => t("hành kinh"), follicular: () => t("nang noãn"), ovulation: () => t("rụng trứng (ước tính)"), luteal: () => t("hoàng thể"),
};
const cycleNext = (cy) => (cy.late ? t("Trễ {n} ngày so với dự đoán", { n: cy.late })
  : cy.days_to_next === 0 ? t("Kỳ kinh có thể bắt đầu hôm nay") : t("Kỳ kinh tiếp theo sau khoảng {n} ngày", { n: cy.days_to_next }));
const journalMonth = { cycle: null, intimacy: null };

/** Lịch tháng của nhật ký: bấm một ngày (không sau hôm nay) để ghi hoặc bỏ ghi. marks(iso) trả {cls: [], count}. */
function journalGrid(grid, month, marks, onPick) {
  grid.textContent = "";
  for (const name of weekdays()) mkEl("span", { class: "cal-dow" }, grid).textContent = name;
  const lead = (month.getDay() + 6) % 7;
  for (let i = 0; i < lead; i++) grid.append(document.createElement("span"));
  const today = todayISO();
  const d = new Date(month);
  while (d.getMonth() === month.getMonth()) {
    const iso = isoOf(d);
    const m = marks(iso);
    const b = mkEl("button", { type: "button", class: ["cal-day", ...m.cls, iso === today ? "today" : ""].join(" ").trim() }, grid);
    b.textContent = String(d.getDate());
    if (m.count > 1) mkEl("span", { class: "cnt" }, b).textContent = `×${m.count}`;
    b.disabled = iso > today;
    b.setAttribute("aria-pressed", String(m.cls.includes("logged")));
    b.setAttribute("aria-label", new Intl.DateTimeFormat(LOCALE, { weekday: "long", day: "numeric", month: "long" }).format(d));
    b.onclick = () => onPick(iso);
    d.setDate(d.getDate() + 1);
  }
}

async function saveJournal(kind, date, value) {
  await run(null, () => api("/api/journal", { kind, date, value }));
  await loadHealth();
  if (!$("#page-overview").hidden) quiet(loadOverview());
}

function monthOf(kind) {
  if (!journalMonth[kind]) { const d = new Date(`${healthDate}T12:00:00`); journalMonth[kind] = new Date(d.getFullYear(), d.getMonth(), 1); }
  return journalMonth[kind];
}
const monthTitle = (m) => new Intl.DateTimeFormat(LOCALE, { month: "long", year: "numeric" }).format(m);

function renderCycleTab(H) {
  const cy = H?.insights?.cycle;
  const logged = H?.journal?.kind === "period" ? H.journal.days : {};
  const isToday = healthDate === todayISO();
  $("#cySub").textContent = cy ? t("Tính từ {n} kỳ kinh đã ghi; dự đoán theo lịch.", { n: Object.keys(logged).length ? cy.cycles + 1 : 0 })
    : t("Ghi các ngày có kinh để ứng dụng tính chu kỳ, dự đoán kỳ tiếp theo và hiểu nhịp tim nghỉ thay đổi theo chu kỳ.");
  $("#cyDay").textContent = cy ? `${t("Ngày {n}", { n: cy.day })}${cy.phase ? ` · ${PHASES[cy.phase]()}` : ""}` : "—";
  statsList($("#cyStats"), cy ? [
    [cycleNext(cy), new Intl.DateTimeFormat(LOCALE, { day: "numeric", month: "short" }).format(new Date(`${cy.next_start}T12:00:00`)), ""],
    [t("Chu kỳ trung bình"), String(cy.cycle_length), t("ngày")],
    [t("Kỳ kinh"), String(cy.period_length), t("ngày")],
  ] : []);
  const notes = [];
  if (cy?.phase === "luteal") {
    notes.push(t("Pha hoàng thể: nhịp tim nghỉ thường cao hơn khoảng {d} nhịp/phút; điểm sẵn sàng đã trừ phần này khi so với mức nền.", { d: fmtDec(cy.rhr_offset, 1) }));
  } else if (cy?.phase === "menstrual") {
    notes.push(t("Đang hành kinh: mệt hơn và ngủ kém hơn một chút là bình thường; vận động nhẹ có thể giúp giảm đau bụng kinh."));
  }
  if (cy?.rhr_offset_personal) notes.push(t("Mức chênh nhịp tim theo chu kỳ tính từ dữ liệu của chính bạn."));
  if (cy?.irregular) notes.push(t("Các chu kỳ gần đây chênh nhau hơn 7 ngày nên dự đoán kém chính xác."));
  $("#cyEffect").textContent = notes.join(" ");
  const todayOn = !!logged[todayISO()];
  $("#cyTodayBtn").setAttribute("aria-pressed", String(todayOn));
  $("#cyTodayBtn").textContent = todayOn ? t("Bỏ đánh dấu hôm nay") : t("Hôm nay có kinh");
  $("#cyTodayBtn").hidden = !isToday;
  const pred = new Set(cy?.predicted_period || []);
  const fertile = new Set(cy?.predicted_fertile || []);
  const month = monthOf("cycle");
  $("#cyMonth").textContent = monthTitle(month);
  journalGrid($("#cyGrid"), month, (iso) => ({
    cls: [logged[iso] ? "logged" : "", !logged[iso] && pred.has(iso) ? "pred" : "", fertile.has(iso) ? "fertile" : "",
      cy && iso === cy.ovulation ? "ovu" : ""].filter(Boolean),
    count: 0,
  }), (iso) => quiet(saveJournal("period", iso, logged[iso] ? 0 : 1)));
}

function renderIntimacyTab(H) {
  const ej = H?.insights?.ejaculation;
  const logged = H?.journal?.kind === "ejaculation" ? H.journal.days : {};
  $("#ejSub").textContent = ej?.last ? t("Lần gần nhất: {when}", { when: ej.days_since === 0 ? t("hôm nay") : ej.days_since === 1 ? t("hôm qua") : t("{n} ngày trước", { n: ej.days_since }) })
    : t("Chưa có lần nào được ghi.");
  statsList($("#ejStats"), ej ? [
    [t("7 ngày qua"), String(ej.count_7), t("lần")],
    [t("30 ngày qua"), String(ej.count_30), t("lần")],
    [t("Trung bình 4 tuần"), fmtDec(ej.per_week, 1), t("lần/tuần")],
  ] : []);
  $("#ejTodayBtn").hidden = healthDate !== todayISO();
  const today = logged[todayISO()] || 0;
  $("#ejTodayBtn").textContent = today ? t("Ghi thêm hôm nay (đã có {n})", { n: today }) : t("Ghi hôm nay");
  const box = $("#ejCompare");
  box.textContent = "";
  const cmp = ej?.sleep;
  if (!cmp) {
    mkEl("p", { class: "compare-empty" }, box).textContent = t("Cần ít nhất {n} đêm sau ngày có ghi và {n} đêm khác có dữ liệu giấc ngủ (hiện có {k}).", { n: ej?.need ?? 3, k: ej?.nights_after ?? 0 });
  } else {
    const table = mkEl("table", { class: "data-table" }, box);
    const head = mkEl("tr", {}, mkEl("thead", {}, table));
    for (const h of ["", t("Đêm sau ngày có ghi ({n})", { n: cmp.after.n }), t("Các đêm khác ({n})", { n: cmp.other.n })]) mkEl("th", {}, head).textContent = h;
    const body = mkEl("tbody", {}, table);
    const row = (label, a, b) => { const tr = mkEl("tr", {}, body); for (const c of [label, a, b]) mkEl("td", {}, tr).textContent = c; };
    row(t("Thời gian ngủ"), fmtMinutes(cmp.after.minutes), fmtMinutes(cmp.other.minutes));
    row(t("Ngủ sâu"), `${fmtDec(cmp.after.deep_pct, 1)}%`, `${fmtDec(cmp.other.deep_pct, 1)}%`);
    row(t("Thức giấc"), fmtMinutes(cmp.after.awake), fmtMinutes(cmp.other.awake));
    row(t("Giờ đi ngủ trung bình"), cmp.after.bedtime, cmp.other.bedtime);
    if (cmp.after.hr && cmp.other.hr) row(t("Nhịp tim khi ngủ"), fmtDec(cmp.after.hr, 1), fmtDec(cmp.other.hr, 1));
  }
  const month = monthOf("intimacy");
  $("#ejMonth").textContent = monthTitle(month);
  journalGrid($("#ejGrid"), month, (iso) => ({ cls: logged[iso] ? ["logged"] : [], count: logged[iso] || 0 }),
    (iso) => quiet(saveJournal("ejaculation", iso, logged[iso] ? 0 : 1)));
}

$("#cyTodayBtn").onclick = () => { const on = $("#cyTodayBtn").getAttribute("aria-pressed") === "true"; quiet(saveJournal("period", todayISO(), on ? 0 : 1)); };
$("#ejTodayBtn").onclick = () => quiet(saveJournal("ejaculation", todayISO(), ((healthData?.journal?.days || {})[todayISO()] || 0) + 1));
for (const [kind, prev, next] of [["cycle", "#cyPrevM", "#cyNextM"], ["intimacy", "#ejPrevM", "#ejNextM"]]) {
  $(prev).onclick = () => { const m = monthOf(kind); journalMonth[kind] = new Date(m.getFullYear(), m.getMonth() - 1, 1); renderHealth(); };
  $(next).onclick = () => { const m = monthOf(kind); journalMonth[kind] = new Date(m.getFullYear(), m.getMonth() + 1, 1); renderHealth(); };
}

/* ============================================================ bản đồ lộ trình */

/* Bản đồ nền: ô ảnh chuẩn của OpenStreetMap (CSS làm tối cho hợp giao diện); lộ trình vẽ bằng SVG lên trên.
   Theo chính sách dùng ô ảnh của OpenStreetMap: có ghi nguồn, chỉ tải phần đang xem.
   Phép chiếu Web Mercator; MAP.cx/cy là tâm khung nhìn tính bằng điểm ảnh ở mức phóng to MAP.z. */
/* Bản đồ lộ trình: Apple Maps (MapKit) gốc của ứng dụng macOS, nằm đè đúng khung #map trong hộp thoại; trang chỉ báo vị
   trí khung và các lộ trình (window.webkit.messageHandlers.nativeMap). Trên trình duyệt không có Apple Maps: khung bản đồ
   báo cần mở ứng dụng, kèm nút mở đúng bản đồ đó trong ứng dụng (miband6://open?page=health/map:…).
   mode "one": một buổi tập (điểm bắt đầu, kết thúc); mode "all": mọi nơi đã chạy, đi bộ, đạp xe, tô màu theo loại. */
const MAP = { mode: "one", routes: [], hidden: new Set(), seq: 0, place: "", stats: [] };
const NATIVE_MAP = window.webkit?.messageHandlers?.nativeMap || null;
const ROUTE_KINDS = ["run", "walk", "ride"];
const routeKindName = (k) => ({ run: t("Chạy bộ"), walk: t("Đi bộ"), ride: t("Đạp xe") })[k];
const placeOk = (r) => !MAP.place || (MAP.place.startsWith("c:") ? r.place?.cc === MAP.place.slice(2)
  : `p:${r.place?.cc}|${r.place?.city}` === MAP.place);
const visibleRoutes = () => MAP.routes.filter((r) => !MAP.hidden.has(r.kind) && placeOk(r));
let nativeShown = false;

function nativePost(msg) {
  try { NATIVE_MAP.postMessage(msg); } catch { /* cửa sổ đang đóng */ }
}
function nativeRect() {
  // phần khung bản đồ đang thấy được trong hộp thoại (hộp thoại có thể cuộn khi cửa sổ thấp)
  const m = $("#map").getBoundingClientRect();
  const d = $("#mapDialog").getBoundingClientRect();
  const x0 = Math.max(m.left, d.left), y0 = Math.max(m.top, d.top);
  const x1 = Math.min(m.right, d.right, window.innerWidth), y1 = Math.min(m.bottom, d.bottom, window.innerHeight);
  return { x: x0, y: y0, width: Math.max(0, x1 - x0), height: Math.max(0, y1 - y0) };
}
/** Vẽ (lại) bản đồ gốc: fit = vừa khung với mọi lộ trình đang hiện. */
function mapRender(fit) {
  if (!NATIVE_MAP || !MAP.routes.length) { nativeHide(); return; }
  const list = MAP.mode === "one" ? MAP.routes.slice(0, 1) : visibleRoutes();
  const routes = list.map((r) => ({ id: r.start, kind: r.kind, points: r.pts }));
  nativePost({ action: nativeShown ? "routes" : "show", rect: nativeRect(), mode: MAP.mode, routes, fit: fit || !nativeShown });
  nativeShown = true;
}
function nativeHide() {
  if (NATIVE_MAP && nativeShown) nativePost({ action: "hide" });
  nativeShown = false;
}
window.nativeMapClick = (id) => {   // bấm vào một lộ trình trên bản đồ tổng (gọi từ ứng dụng)
  const r = MAP.routes.find((x) => x.start === id);
  if (r?.w) openMap(r.w, true);
};

function mapMessage(text) {
  $("#mapMsg").textContent = text;
  $("#mapMsg").hidden = !text;
  if (text) nativeHide();   // thông báo nằm trong khung: cất bản đồ gốc đi để thấy chữ
}
/** Trình duyệt: khung bản đồ báo cần ứng dụng macOS; target là giờ bắt đầu buổi tập hoặc "all". */
function mapNeedApp(target) {
  $("#mapNeedApp").hidden = false;
  $("#mapOpenApp").href = `miband6://open?page=${encodeURIComponent(`health/map:${target}`)}`;
}

function mapOpenDialog(title, sub) {
  const dlg = $("#mapDialog");
  $("#mapTitle").textContent = title;
  $("#mapSub").textContent = sub;
  $("#mapNeedApp").hidden = true;
  MAP.seq++;
  nativeHide();
  mapMessage("");
  if (!dlg.open) dlg.showModal();
  return MAP.seq;
}

function legendOne() {
  const box = $("#mapLegend");
  box.textContent = "";
  if (!NATIVE_MAP) return;
  for (const [cls, label] of [["start", t("Bắt đầu")], ["end", t("Kết thúc")]]) {
    const s = mkEl("span", {}, box);
    mkEl("i", { class: `dot ${cls}` }, s);
    s.append(label);
  }
}

/** Bản đồ một buổi tập. back: mở từ bản đồ tổng (hiện nút quay lại). */
async function openMap(w, back = false) {
  const seq = mapOpenDialog(workoutName(w), dateTime(w.start));
  MAP.mode = "one";
  MAP.routes = [];
  $("#mapBack").hidden = !back;
  $("#mapPlace").hidden = true;
  legendOne();
  MAP.stats = workoutStats(w);
  statsList($("#mapStats"), MAP.stats);
  if (!NATIVE_MAP) { mapNeedApp(String(w.start)); return; }
  mapMessage(t("Đang tải lộ trình…"));
  try {
    const r = await api(`/api/workouts/${w.start}/track`);
    if (seq !== MAP.seq) return;   // người dùng đã mở bản đồ khác
    if (r.points.length < 2) { mapMessage(t("Buổi tập này không có điểm GPS nào.")); return; }
    MAP.routes = [{ start: w.start, kind: "run", w, pts: r.points.map(([, lat, lon]) => [lat, lon]) }];
    mapMessage("");
    mapRender(true);
  } catch (e) {
    if (seq === MAP.seq) mapMessage(e.message);
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
/** Bản đồ "những nơi đã đến": mọi lộ trình đã có trên máy; phần còn thiếu được tải ở nền rồi tự hiện thêm. */
async function openAllMaps(refresh = false) {
  const seq = refresh ? MAP.seq : mapOpenDialog(t("Những nơi bạn đã đến"), "");
  if (!refresh) {
    MAP.mode = "all";
    MAP.routes = [];
    $("#mapBack").hidden = true;
    if (NATIVE_MAP) mapMessage(t("Đang tải lộ trình…")); else mapNeedApp("all");
  }
  let r;
  try {
    r = await api("/api/tracks");
  } catch (e) {
    if (seq === MAP.seq && !refresh && NATIVE_MAP) mapMessage(e.message);
    return;
  }
  if (seq !== MAP.seq || MAP.mode !== "all") return;
  const byStart = new Map((healthData?.workouts || []).map((w) => [w.start, w]));
  const first = !MAP.routes.length;
  MAP.routes = r.routes.map((x) => ({ ...x, w: byStart.get(x.start) || null, pts: x.points }))
    .sort((a, b) => a.start - b.start);
  renderPlaceFilter();
  renderAllLegend();
  renderAllStats();
  $("#mapSub").textContent = r.pending ? t("Đang tải thêm {n} lộ trình từ Mi Fitness…", { n: r.pending }) : allSubtitle();
  if (!NATIVE_MAP) return;
  if (!MAP.routes.length) {
    mapMessage(r.pending ? t("Đang tải lộ trình từ Mi Fitness, lần đầu có thể mất vài phút…")
      : t("Chưa có buổi tập nào có lộ trình GPS. Bấm Lấy lịch sử từ Mi Fitness để lấy các buổi chạy, đi bộ, đạp xe ngoài trời."));
    return;
  }
  mapMessage("");
  mapRender(first);
}

function renderAllLegend() {
  const box = $("#mapLegend");
  box.textContent = "";
  for (const kind of ROUTE_KINDS) {
    const n = MAP.routes.filter((r) => r.kind === kind).length;
    if (!n) continue;
    const b = mkEl("button", { type: "button", class: "legend-toggle", "aria-pressed": String(!MAP.hidden.has(kind)) }, box);
    mkEl("i", { class: `swatch ${kind}` }, b);
    b.append(`${routeKindName(kind)} · ${n}`);
    b.onclick = () => {
      if (MAP.hidden.has(kind)) MAP.hidden.delete(kind); else MAP.hidden.add(kind);
      b.setAttribute("aria-pressed", String(!MAP.hidden.has(kind)));
      renderAllStats();
      mapRender(false);
    };
  }
  if (NATIVE_MAP) mkEl("span", { class: "legend-hint" }, box).textContent = t("Bấm vào một lộ trình để xem chi tiết.");
}

/** Lọc "những nơi đã đến" theo quốc gia hoặc thành phố (tên nơi tra từ điểm đầu mỗi lộ trình). */
function renderPlaceFilter() {
  const sel = $("#mapPlace");
  const countries = new Map();
  for (const r of MAP.routes) {
    if (!r.place) continue;
    const c = countries.get(r.place.cc) || { name: r.place.country, n: 0, cities: new Map() };
    c.n += 1;
    c.cities.set(r.place.city, (c.cities.get(r.place.city) || 0) + 1);
    countries.set(r.place.cc, c);
  }
  const cityCount = [...countries.values()].reduce((a, c) => a + c.cities.size, 0);
  sel.hidden = cityCount < 2;
  if (sel.hidden) { MAP.place = ""; return; }
  sel.textContent = "";
  mkEl("option", { value: "" }, sel).textContent = t("Mọi nơi ({n})", { n: MAP.routes.length });
  for (const [cc, c] of [...countries].sort((a, b) => b[1].n - a[1].n)) {
    const group = mkEl("optgroup", { label: c.name }, sel);
    if (countries.size > 1 || c.cities.size > 1) mkEl("option", { value: `c:${cc}` }, group).textContent = t("Cả {country} ({n})", { country: c.name, n: c.n });
    for (const [city, n] of [...c.cities].sort((a, b) => b[1] - a[1])) {
      mkEl("option", { value: `p:${cc}|${city}` }, group).textContent = `${city} (${n})`;
    }
  }
  if (![...sel.options].some((o) => o.value === MAP.place)) MAP.place = "";
  sel.value = MAP.place;
}

function allSubtitle() {
  const shown = visibleRoutes();
  if (!shown.length) return "";
  const where = MAP.place ? $("#mapPlace").selectedOptions[0]?.textContent.replace(/ \(\d+\)$/, "") : t("Mọi nơi");
  return `${where} · ${shortDate(H_date(shown[0].start))} – ${shortDate(H_date(shown[shown.length - 1].start))}`;
}
const H_date = (ts) => { const d = new Date(ts * 1000); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };

function renderAllStats() {
  const shown = visibleRoutes();
  const km = shown.reduce((a, r) => a + (r.w?.distance || 0), 0) / 1000;
  const secs = shown.reduce((a, r) => a + (r.w ? r.w.active_seconds || r.w.end - r.w.start : 0), 0);
  const days = new Set(shown.map((r) => new Date(r.start * 1000).toDateString())).size;
  MAP.stats = [
    [t("Số lộ trình"), fmtInt(shown.length), ""],
    [t("Quãng đường"), fmtDec(km, 1), "km"],
    [t("Thời gian"), fmtMinutes(secs / 60), ""],
    [t("Số ngày"), fmtInt(days), ""],
  ];
  statsList($("#mapStats"), MAP.stats);
}

/** Mở bản đồ theo địa chỉ trang (#health/map:all, #health/map:<giờ bắt đầu>), ví dụ khi trình duyệt chuyển sang ứng dụng. */
function openMapFromHash(target) {
  if (target === "all") { openAllMaps(); return; }
  const w = (healthData?.workouts || []).find((x) => String(x.start) === target);
  if (w) openMap(w);
}

$("#mapClose").onclick = () => $("#mapDialog").close();
$("#mapPlace").onchange = () => {
  MAP.place = $("#mapPlace").value;
  renderAllStats();
  $("#mapSub").textContent = allSubtitle();
  mapRender(true);
};
$("#mapShare").hidden = !NATIVE_MAP;
$("#mapShare").onclick = () => {
  if (!nativeShown) { toast(t("Mở bản đồ có lộ trình trước khi chia sẻ."), true); return; }
  const b = $("#mapShare").getBoundingClientRect();
  const kinds = new Set(visibleRoutes().map((r) => r.kind));
  nativePost({
    action: "export", title: $("#mapTitle").textContent,
    subtitle: MAP.mode === "all" ? allSubtitle() : $("#mapSub").textContent,
    stats: MAP.stats, legend: MAP.mode === "all" ? ROUTE_KINDS.filter((k) => kinds.has(k)).map((k) => [routeKindName(k), k]) : [],
    anchor: { x: b.left, y: b.top, width: b.width, height: b.height },
  });
};
window.nativeMapExported = (r) => {
  if (r.error) toast(t("Không xuất được ảnh bản đồ: {e}", { e: r.error }), true);
  else toast(t("Đã lưu ảnh vào thư mục Tải về: {name}", { name: r.name }));
};
$("#mapDialog").addEventListener("close", () => { MAP.seq++; nativeHide(); });
$("#mapBack").onclick = () => openAllMaps();
$("#woMapAllBtn").onclick = () => openAllMaps();
if (NATIVE_MAP) {
  // giữ bản đồ gốc trùng khung khi cửa sổ đổi cỡ hoặc hộp thoại cuộn
  let pending = 0;
  const sync = () => {
    cancelAnimationFrame(pending);
    pending = requestAnimationFrame(() => { if (nativeShown) nativePost({ action: "rect", rect: nativeRect() }); });
  };
  new ResizeObserver(sync).observe($("#map"));
  window.addEventListener("resize", sync);
  $("#mapDialog").addEventListener("scroll", sync);
}

/** Vẽ lại các phần có chữ ghép với số liệu, ngày giờ (không đụng tới giá trị đang sửa trong các ô nhập). */
function rerenderLanguage() {
  if (!META) return;
  const steps = [
    () => applyState(STATE),
    () => { relabelOptions($("#hInterval"), hrIntervalLabel); relabelOptions($("#hThreshold"), hrThresholdLabel); },
    renderAlarms,
    drawSpark,
    renderOverview,
    // trang ẩn thì để lúc mở trang (route -> loadHealth) vẽ lại, tránh vẽ biểu đồ khi chưa có kích thước
    () => { if (healthData && !$("#page-health").hidden) { renderDateNav(); renderHealth(); } },
    () => { if (SIM) drawSim(); },
    () => DATE_PICKERS.forEach((p) => p.refresh()),
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
  updateCornerDot();
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
$("#cloudDialog").addEventListener("close", () => { if (cloudOpen) cancelCloud(); });

// Bấm ra ngoài hộp thoại (vào backdrop) để đóng
document.querySelectorAll("dialog").forEach((dlg) => {
  let startedOutside = false;
  dlg.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    if (e.target !== dlg) { startedOutside = false; return; }
    const r = dlg.getBoundingClientRect();
    startedOutside = e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
  });
  dlg.addEventListener("click", (e) => {
    if (e.button !== 0 || !startedOutside || e.target !== dlg || !dlg.open) return;
    const r = dlg.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) {
      dlg.close();
    }
    startedOutside = false;
  });
  dlg.addEventListener("pointercancel", () => { startedOutside = false; });
});

$("#nativeAppNotice").hidden = !!window.webkit?.messageHandlers?.nativeMap || localStorage.getItem("mb6_hide_app_notice") === "1";
$("#nativeAppClose").onclick = () => {
  $("#nativeAppNotice").hidden = true;
  try { localStorage.setItem("mb6_hide_app_notice", "1"); } catch { /* bỏ qua */ }
};
init();
