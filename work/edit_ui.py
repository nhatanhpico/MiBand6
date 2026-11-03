from pathlib import Path
p=Path('src/miband6/web/static/index.html')
s=p.read_text()
start='''      <div id="overviewBody" hidden>
'''
new='''      <div id="overviewBody" hidden>
        <section class="daily-summary" aria-label="Tóm tắt hôm nay">
          <div class="summary-heading"><p class="eyebrow">MI BAND 6 · HÔM NAY</p><h2>Mỗi ngày, hiểu cơ thể hơn.</h2><p id="ovSync" class="muted">Chưa đồng bộ dữ liệu sức khỏe.</p></div>
          <div class="summary-metrics">
            <a href="#health/steps"><b id="ovGoal">—</b><span>Mục tiêu bước</span></a>
            <a href="#health/readiness"><b id="ovReady">—</b><span>Sẵn sàng · ước tính</span></a>
            <a href="#health/steps"><b id="ovStreak">—</b><span>Chuỗi ngày đạt mục tiêu</span></a>
          </div>
        </section>
        <div class="quick-actions" aria-label="Thao tác nhanh">
          <button id="ovSyncBtn" class="btn primary" data-conn><svg class="ic"><use href="#i-refresh"/></svg><span>Đồng bộ vòng tay</span></button>
          <button id="ovMeasureBtn" class="btn" data-conn><svg class="ic"><use href="#i-heart"/></svg><span>Đo nhịp tim</span></button>
          <button id="ovFindBtn" class="btn" data-conn><svg class="ic"><use href="#i-band"/></svg><span>Tìm vòng tay</span></button>
          <a class="btn" href="#health">Xem sức khỏe</a>
        </div>
        <div class="glance-grid">
          <article class="card goal-glance">
            <header class="card-head"><h2>Mục tiêu hôm nay</h2><p class="card-sub">Dữ liệu vận động từ vòng tay</p></header>
            <div class="goal-glance-body"><div class="goal-orbit" id="ovGoalRing" role="img" aria-label="Tiến độ mục tiêu bước"><div><b id="ovSteps">—</b><span id="ovGoalTarget">—</span></div></div>
              <dl class="glance-facts"><div><dt>Năng lượng</dt><dd id="ovCalories">—</dd><small>Ước tính của vòng tay</small></div><div><dt>Giờ đứng</dt><dd>—</dd><small>Chưa có trường dữ liệu được xác minh</small></div></dl>
            </div>
            <div class="chart" id="ovStepsTrend"></div>
            <a class="hero-link" href="#health/steps">Xem lịch sử bước chân</a>
          </article>
          <article class="card vitals-glance">
            <header class="card-head"><h2>Chỉ số gần nhất</h2><p class="card-sub">Số đo đã đồng bộ, không phải theo dõi trực tiếp</p></header>
            <dl class="glance-vitals"><div><dt>Nhịp tim</dt><dd id="ovHr">—</dd><small id="ovHrTime">—</small></div><div><dt>Căng thẳng</dt><dd id="ovStress">—</dd><small id="ovStressTime">—</small></div><div><dt>Nhịp tim nghỉ</dt><dd id="ovRhr">—</dd><small>Ước tính từ nhịp tim khi ngủ</small></div></dl>
            <a class="hero-link" href="#health/hr">Xem chi tiết chỉ số</a>
          </article>
          <article class="card sleep-glance">
            <header class="card-head"><h2>Giấc ngủ &amp; hồi phục</h2><p class="card-sub" id="ovSleepRange">Giấc ngủ kết thúc hôm nay</p></header>
            <div class="sleep-glance-top"><p class="card-value" id="ovSleep">—</p><p class="sleep-score"><b id="ovSleepScore">—</b><span>Điểm ngủ · ước tính</span></p></div>
            <div class="sleep-segments" id="ovSleepStages" role="img" aria-label="Các giai đoạn giấc ngủ"></div><ul class="legend" id="ovSleepLegend"></ul>
            <p class="card-sub">REM chỉ hiện khi có dữ liệu; REM do ứng dụng suy ra được ghi là ước tính. Chưa có dữ liệu chất lượng hô hấp.</p>
            <a class="hero-link" href="#health/sleep">Xem giấc ngủ</a>
          </article>
        </div>
        <details class="device-details"><summary>Thiết bị &amp; đo trực tiếp</summary>
'''
s=s.replace(start,new,1)
s=s.replace('''      </div>
    </section>

    <!-- ============================================================ Sức khỏe -->''','''        </details>
      </div>
    </section>

    <!-- ============================================================ Sức khỏe -->''',1)
# Vitals first in physical reading/focus order, preserving all element IDs.
a=s.index('        <article class="card" id="health-hr">')
b=s.index('        <article class="card" id="health-stress">',a)
hr=s[a:b]; s=s[:a]+s[b:]
a=s.index('        <article class="card" id="health-spo2">')
b=s.index('        <article class="card wide" id="health-workouts">',a)
sp=s[a:b]; s=s[:a]+s[b:]
hr=hr.replace('<h2>Nhịp tim</h2>', '<h2>Nhịp tim</h2><span class="metric-badge" id="hrBadge">Chưa có dữ liệu</span>')
hr=hr.replace('<div class="chart" id="hrChart"></div>', '<details class="metric-details"><summary>Xem biểu đồ trong ngày</summary><div class="chart" id="hrChart"></div></details>')
sp=sp.replace('<h2>SpO2</h2>', '<h2>SpO2</h2><span class="metric-badge" id="spBadge">Đo từng lần</span>')
sp=sp.replace('<div class="table-scroll">','<details class="metric-details"><summary>Xem từng lần đo</summary><div class="table-scroll">').replace('</table></div>', '</table></div></details>')
s=s.replace('      <div class="hgrid">','      <div class="hgrid">\n'+hr+sp,1)
s=s.replace('<ul class="rd-parts" id="rdParts"></ul>\n          <div class="chart" id="rdTrend"></div>', '<p class="card-sub estimate-note">Điểm do ứng dụng ước tính; chưa được kiểm chứng lâm sàng.</p><details class="metric-details"><summary>Thành phần &amp; xu hướng</summary><ul class="rd-parts" id="rdParts"></ul>\n          <div class="chart" id="rdTrend"></div></details>')
# Hide secondary detail without removing analytical features.
for ident in ('health-analysis','health-mind','health-circadian'):
    a=s.index('        <article ',s.index('      <div class="hgrid">')) if False else s.index('id="'+ident+'"')
    head_end=s.index('</header>',a)+len('</header>')
    article_end=s.index('</article>',head_end)
    s=s[:head_end]+'<details class="metric-details"><summary>Xem phân tích</summary>'+s[head_end:article_end]+'</details>'+s[article_end:]
p.write_text(s)
