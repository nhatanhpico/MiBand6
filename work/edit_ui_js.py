from pathlib import Path
p=Path('src/miband6/web/static/app.js')
s=p.read_text()
s=s.replace('  window.scrollTo({ top: 0 });','  window.scrollTo({ top: 0 });\n  if (page === "overview") quiet(loadOverview());',1)
s=s.replace('  drawBand();\n}\n\n/* ============================================================ trạng thái */','  drawBand();\n  renderOverview();\n}\n\n/* ============================================================ trạng thái */',1)
s=s.replace('      case "health_data": if (!$("#page-health").hidden) quiet(loadHealth()); break;', '      case "health_data":\n        if (!$("#page-health").hidden) quiet(loadHealth());\n        if (!$("#page-overview").hidden) quiet(loadOverview());\n        break;')
s=s.replace('  $("#hSyncBtn").disabled = !STATE.connected || st.state === "running";', '  $("#hSyncBtn").disabled = !STATE.connected || st.state === "running";\n  $("#ovSyncBtn").disabled = !STATE.connected || st.state === "running";\n  $("#ovSync").textContent = line.textContent;')
anchor='/* ---- chọn ngày */'
new='''/* Overview has its own today-only snapshot; browsing a past health day must not change it. */
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

function renderOverview() {
  const v = overviewSummary(overviewData, STATE.connected ? STATE.live?.activity : null,
    Number(STATE.profile?.goal || 8000), todayISO());
  $("#ovGoal").textContent = v.pct == null ? "—" : `${v.pct}%`;
  $("#ovReady").textContent = v.readiness?.score == null ? "—" : `${v.readiness.score}/100`;
  $("#ovStreak").textContent = v.streak == null ? "—" : fmtInt(v.streak);
  $("#ovSteps").textContent = fmtInt(v.steps);
  $("#ovGoalTarget").textContent = t("/ {n} bước", { n: fmtInt(v.target) });
  $("#ovGoalRing").style.setProperty("--progress", `${(v.pct || 0) * 3.6}deg`);
  $("#ovGoalRing").setAttribute("aria-label", t("Mục tiêu bước: {p}", { p: v.pct == null ? t("Chưa có dữ liệu") : `${v.pct}%` }));
  const calories = STATE.connected ? STATE.live?.activity?.calories : null;
  $("#ovCalories").textContent = calories == null ? "—" : `${fmtInt(calories)} kcal`;
  const hr = v.day?.hr?.at(-1);
  const stress = v.day?.stress?.at(-1);
  $("#ovHr").textContent = hr ? `${hr[1]} ${t("nhịp/phút")}` : "—";
  $("#ovHrTime").textContent = hr ? dateTime(hr[0]) : t("Chưa có dữ liệu");
  $("#ovStress").textContent = stress ? `${stress[1]}/100 · ${stressLabel(stress[1])}` : "—";
  $("#ovStressTime").textContent = stress ? dateTime(stress[0]) : t("Chưa có dữ liệu");
  $("#ovRhr").textContent = v.readiness?.parts?.find((p) => p.key === "rhr")?.value || "—";
  const sl = v.day?.sleep;
  $("#ovSleep").textContent = sl ? fmtMinutes(sl.minutes) : "—";
  $("#ovSleepScore").textContent = v.readiness?.parts?.find((p) => p.key === "sleep")?.score ?? "—";
  $("#ovSleepRange").textContent = sl ? t("Ngủ lúc {start}, dậy lúc {end}", { start: hhmm(sl.start), end: hhmm(sl.end) }) : t("Giấc ngủ kết thúc hôm nay");
  const segments = $("#ovSleepStages");
  const legend = $("#ovSleepLegend");
  segments.replaceChildren(); legend.replaceChildren();
  for (const [key, name, color] of STAGES) {
    if (!sl?.[key]) continue;
    const label = key === "rem" && sl.rem_estimated ? t("REM (ước tính)") : name();
    const segment = mkEl("span", { style: `flex:${sl[key]};background:${color}` }, segments);
    segment.title = `${label}: ${fmtMinutes(sl[key])}`;
    const li = mkEl("li", {}, legend);
    mkEl("i", { style: `background:${color}` }, li);
    li.append(`${label} ${fmtMinutes(sl[key])}`);
  }
  segments.setAttribute("aria-label", sl ? legend.textContent : t("Chưa có dữ liệu"));
  if (!$("#page-overview").hidden) {
    const recent = (overviewData?.date === todayISO() ? overviewData?.steps_days || [] : []).slice(-7);
    columnChart($("#ovStepsTrend"), recent.map((d) => ({ key: d.date, label: shortDate(d.date),
      parts: [{ value: d.date === todayISO() ? v.steps ?? d.steps : d.steps, color: "var(--c-steps)" }],
      tip: () => [[fmtInt(d.steps), longDate(d.date)]],
    })), { height: 100, label: t("Bước chân 7 ngày đã ghi gần nhất"), empty: t("Chưa có lịch sử bước chân."), valueFmt: fmtInt });
  }
}

$("#ovSyncBtn").onclick = () => quiet(run($("#ovSyncBtn"), async () => {
  renderHealthStatus((await api("/api/health/sync", {})).status);
}));
$("#ovMeasureBtn").onclick = () => {
  $(".device-details").open = true;
  $("#hrMeasureBtn").click();
  $(".tile-hr").scrollIntoView({ block: "center", behavior: "smooth" });
};
$("#ovFindBtn").onclick = () => quiet(run($("#ovFindBtn"), () => api("/api/find", { on: true })));

// Graphs need a new layout pass when their initially collapsed detail is opened.
$$(".metric-details").forEach((el) => el.addEventListener("toggle", () => {
  if (el.open && healthData && !$("#page-health").hidden) renderHealth();
}));
$(".device-details").addEventListener("toggle", () => { if ($(".device-details").open) drawSpark(); });

'''
s=s.replace(anchor,new+anchor,1)
s=s.replace('    if (!$("#page-overview").hidden) drawSpark();', '    if (!$("#page-overview").hidden) { drawSpark(); renderOverview(); }',1)
s=s.replace('  $("#hrSub").textContent = dayLabel;', '  $("#hrSub").textContent = dayLabel;\n  $("#hrBadge").textContent = hr.length ? t("Dữ liệu đã đồng bộ") : t("Chưa có dữ liệu");',1)
s=s.replace('  const sp = H.spo2_recent;', '''  const sp = H.spo2_recent;
  $("#spBadge").textContent = sp.length ? t("Đo từng lần") : t("Chưa có dữ liệu");''',1)
s=s.replace('    drawSpark,\n    // trang ẩn', '    drawSpark,\n    renderOverview,\n    // trang ẩn',1)
p.write_text(s)
