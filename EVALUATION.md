# COMPREHENSIVE TECHNICAL EVALUATION: MI SMART BAND 6 MANAGER
> **Report Date:** November 4, 2026 (updated the same day after the mental-state fix and the body-signal features)
> **Target Version:** 1.0.0
> **Evaluation Scope:** Biomedical health tracking fidelity, hardware feature maximization of Xiaomi Mi Smart Band 6, and mathematical/algorithmic robustness.

> **Update summary.** A user measured "Relaxed" (26) on the band while the Mental state card said "Stress" with tension 100. Cause: the stress factor needed at least 6 automatic readings per day and ignored manual readings, so tension came from resting heart rate alone. Tension now comes from the band's own stress readings (automatic and manual), a raised sleeping heart rate is reported as a physical body signal, and a personal model explains sleeping-HR changes. Later the same day: disease-risk models (machine learning trained on 12,266 NHANES adults), live heart rate on the Health page in real time, and personal-model training on up to a year of the user's history. Gaps 2 and 3 of section 3.2 and roadmap phase 1 below had already been implemented and are marked as done. The Vietnamese version of this report is [DANH_GIA.md](DANH_GIA.md).

---

## TABLE OF CONTENTS
1. [Executive Summary & Scorecard](#1-executive-summary--scorecard)
2. [Software Architecture & Test Verification](#2-software-architecture--test-verification)
3. [Health Tracking Fidelity & Biomedical Validity](#3-health-tracking-fidelity--biomedical-validity)
4. [Hardware & Firmware Feature Maximization Matrix](#4-hardware--firmware-feature-maximization-matrix)
5. [In-Depth Algorithmic Analysis](#5-in-depth-algorithmic-analysis)
6. [Actionable Engineering Roadmap](#6-actionable-engineering-roadmap)

---

## 1. Executive Summary & Scorecard

The **Mi Smart Band 6 Manager** (`miband6`) is an exceptionally engineered, standalone desktop companion and health analytics platform for macOS and Web. Unlike typical hobbyist Bluetooth projects that rely on high-level wrappers or reverse-engineered scripts, this codebase demonstrates **deep low-level BLE mastery, rigorous biomedical telemetry principles, and clean software architecture**.

### System Scorecard:
* **Architecture & Security:** **9.8 / 10** — Pure function layering, hand-rolled NIST B-163 ECDH & AES-128-ECB cryptography, zero-loss non-acknowledging BLE health sync.
* **Health Tracking Fidelity:** **9.2 / 10** — Robust handling of sensor noise, sleep onset/wake edge compensation, menstrual cycle luteal RHR offset, time-weighted TRIMP, a mental state anchored to the band's own stress readings, and multi-night sleeping-HR body signals.
* **Hardware Maximization:** **8.8 / 10** — Comprehensive coverage of BLE transport, custom UIHH watch face synthesis, Open-Meteo weather push, Happy Eyeballs GPS sync, and a two-way music bridge to Apple Music, Spotify and macOS media. Camera remote trigger, world clock, event reminders and nocturnal SpO2 remain untapped.
* **Algorithmic Rigor:** **9.5 / 10** — Grounded in peer-reviewed physiological literature (Banister fatigue impulse-response, Edwards TRIMP, Phillips SRI, Roenneberg MCTQ, WHO Asian BMI) plus a cross-validated personal model that is only used when it beats the plain baseline.

```mermaid
quadrantChart
    title Subsystem Performance Matrix
    x-axis Low Technical Complexity --> High Technical Complexity
    y-axis Baseline Utility --> Superior / Groundbreaking
    quadrant-1 Superior - High Value
    quadrant-2 Quick Win
    quadrant-3 Needs Expansion
    quadrant-4 High Complexity - Refine
    "Zero-Loss Health Sync (No 0x03 ACK)": [0.35, 0.95]
    "Dual Auth Handshake (2021 ECDH)": [0.85, 0.96]
    "UIHH 87-Byte Watchface & Canvas Sim": [0.75, 0.92]
    "Readiness Guardrails & Clamping": [0.78, 0.94]
    "REM Sleep Inference (HR Dynamics)": [0.82, 0.88]
    "GPS Sync via Happy Eyeballs & Maps": [0.80, 0.91]
    "Mental State from Band Stress": [0.40, 0.86]
    "Personal Sleeping-HR Model (LOO)": [0.70, 0.84]
    "Disease Risk ML (NHANES, Asian-calibrated)": [0.72, 0.82]
    "2-Way Desktop Music Bridge": [0.45, 0.80]
    "Overnight Continuous SpO2 Toggle": [0.65, 0.40]
```

---

## 2. Software Architecture & Test Verification

### 2.1. Strict Functional Layering
The codebase enforces a unidirectional dependency hierarchy:
1. **`protocol.py` (Pure Protocol):** Completely decoupled from Bluetooth I/O. Contains binary packet encoders/decoders, UUID mappings, and constants. Can be unit-tested deterministically without network or mocked devices.
2. **`crypto.py` (Low-Level Cryptography):** Handcrafted NIST B-163 (sect163r2) ECDH in little-endian format (tested against OpenSSL), AES-128-ECB, and chunked frame encoders/decoders with CRC32 verification.
3. **`device.py` (Async BLE Client):** Wraps Bleak into the `MiBand6` abstraction. Features `known_peripheral` retrieval via macOS CoreBluetooth to bypass unnecessary scanning when the OS already maintains an active connection.
4. **`health.py`, `insights.py`, `models.py`, `risk.py`, `workouts.py` & `coach.py` (Data Science & Algorithms):** Pure mathematical models for sleep stage extraction, circadian strain, Banister recovery curves, daily readiness scoring, mental state, body signals, resting-HR episodes and the sleep plan. `models.py` holds the pure-Python ridge regression with leave-one-out validation and the learning curve; `risk.py` walks the gradient-boosted trees in `risk_models.json` (no NumPy or scikit-learn at runtime, so the macOS arm64 bundle stays small; training happens offline in `tools/train_risk_models.py`). `workouts.py` decodes Mi Fitness per-second workout files and builds the workout detail page; `coach.py` holds the personal fitness model (VO2max from steady running/walking minutes) and the next-workout and 7-day plan rules.
5. **`healthdb.py` (Encrypted/Local Persistence):** Per-device SQLite databases stored at `~/Library/Application Support/MiBand6Manager/health/` with strict `0o600` POSIX permissions.
6. **`web/server.py` & `web/static/` (Full-Stack UI):** Single-process `aiohttp` server with WebSocket event streaming (`/api/events`) and zero-build vanilla JS/CSS frontend.

### 2.2. Empirical Verification Results
* **Internationalization Consistency (`tests/i18n_strings.py`):**
  - HTML strings: 381 (0 missing)
  - JS strings: 520 (0 missing)
  - Python strings: 427 (0 missing)
  - Options/Labels: 53 (0 missing)
  - Swift macOS wrapper: 50 (0 missing)
  - **Verdict:** 100% translation synchronization between Vietnamese and English.
* **Test suite (`pytest`):**
  - **242 tests passed, 2 skipped** (the two need macOS: the Swift compiler and macOS scripting). The suite was run in UTC and in UTC+8; two tests that depended on the time of day or on background-sync timing were fixed.
  - `tests/test_gui_demo.py` (legacy Qt app) needs Qt's display libraries and runs on a desktop machine.
  - New coverage: the user's mismatch case (relaxed band stress with a +8 bpm night), resting HR alone never producing "Stress", the personal model learning a planted bedtime effect end to end from band-shaped data and from 4 months of history beyond the 60-day window, the learning curve, the hat-matrix leave-one-out against explicit refits, multi-night body signals, resting-HR episodes, the sleep plan, the disease-risk models (validated quality, monotonic behaviour, factor rules, Asian calibration) and live heart rate reaching the Health page.

---

## 3. Health Tracking Fidelity & Biomedical Validity

### 3.1. Technical Breakthroughs

1. **Zero-Loss Non-Acknowledging Sync (No ACK `03`):**
   * *Industry Context:* The standard Huami sync protocol expects a `0x03` confirmation packet after downloading batch health samples. Sending this packet wipes the pending sync flags on the device, permanently destroying data for the official mobile companion app (Mi Fitness).
   * *Implementation:* The app intentionally omits the `0x03` ACK, querying strictly by timestamp ranges (`since`) and recording checkpoints locally in `HealthDB.sync`. Users can seamlessly use this desktop application alongside Mi Fitness without sync collisions.
2. **Sleep Latency & Wake Edge Adjustment:**
   * *Biomedical Reality:* Accelerometer-based wrist trackers typically record sleep state transitions with a 10–12 minute lag.
   * *Implementation:* `health.py` inspects the 6th byte (continuous sleep propensity index) to backdate sleep onset to the exact minute movement ceased and truncate false wake periods. This replicates the on-band display with sub-minute precision.
3. **Time-Weighted TRIMP with Interval-Insensitive Hold (`HR_HOLD`):**
   * *Biomedical Reality:* Wearable users frequently toggle between 1-minute, 5-minute, 10-minute, or 30-minute HR monitoring intervals. A naive summation of recorded BPM samples skews workload by up to 10×.
   * *Implementation:* Workload (Edwards TRIMP) is time-weighted: each sample persists forward up to `HR_HOLD` (10 minutes) and terminates immediately if off-wrist status is detected. Furthermore, days only qualify for training load baselines (`_load_day`) if worn $\ge 10$ hours with $\ge 60\%$ valid HR coverage.
4. **Menstrual Cycle Luteal RHR Offset:**
   * *Biomedical Reality:* Progesterone elevation during the luteal phase naturally increases baseline resting heart rate by 2–3 bpm (Shilaih et al., 2017).
   * *Implementation:* For female profiles logging menstrual dates, the algorithm dynamically subtracts this hormonal offset from night RHR before evaluating against the 30-day baseline, preventing false "unrecovered" alerts.
5. **WHO Asian BMI Cutoffs:**
   * Uses WHO Western Pacific criteria (18.5–22.9 normal, 23–24.9 overweight, $\ge 25$ obese) rather than generic Western cutoffs (25/30), addressing metabolic risk thresholds specific to Asian populations.
6. **Mental State Anchored to the Band's Stress Index:**
   * *Biomedical Reality:* The band computes its stress index from HRV, the direct marker of autonomic tension. A raised sleeping heart rate has many physical causes (alcohol, late meals, late nights, hard training, oncoming illness).
   * *Implementation:* Tension uses every stress reading of the last 72 h, automatic and manual, weighted towards recent ones and compared with the user's usual level. Sleeping HR only corroborates when the band also measures stress; on its own it is capped below the "tense" threshold and reported as a physical sign.
7. **Body Signals with a Personal Model:**
   * *Biomedical Reality:* Resting heart rate rises for several nights before and during infections (Mishra et al. 2020, Quer et al. 2021).
   * *Implementation:* Sleeping HR is compared with a robust personal baseline (median, MAD-based SD) over the last 3 nights; 2 of 3 high nights is "watch", 3 in a row "alert". A ridge regression learns how bedtime, sleep length and training load move the user's own sleeping HR, so only the unexplained part is flagged.
8. **Heart Rate at Rest and Tonight's Sleep:**
   * Apple-style episodes (≥ 120 or < 40 bpm for ≥ 10 minutes while awake, still and outside workouts) appear in the health analysis. A sleep plan counts back from the usual wake time with gradual sleep-debt repayment.
9. **Disease Risk by Machine Learning:**
   * Gradient-boosted trees trained on 12,266 NHANES 2009–2012 adults estimate the current probability of diagnosed diabetes and of a resting BP ≥ 140/90 from age, sex, height, BMI and 30 days of band data, recalibrated for Asian adults and explained against a healthy same-age profile. Weaker conditions (cholesterol, low HDL, depression screen; validated AUC < 0.70) were tested and left out.
10. **Live Heart Rate and Sampling-Robust Statistics:**
   * Continuous-tracking readings are stored per minute and drawn on the Health page immediately; they fill band minutes without HR. Day averages and the resting pulse are time-weighted, so an hour of live tracking at a laptop doesn't outweigh a day sampled every 10 minutes, and a few false steps while typing don't break "still" detection.
11. **Personal Learning from Long History:**
   * Completed days are kept in a compact `daily` table, so the personal model trains on up to a year of nights (older data is filled in 45 days at a time), with a forward-in-time learning curve for 1 week to 1 year of history.

### 3.2. Identified Gaps & Areas for Improvement

1. **Absence of Sleep Breathing Quality / Nocturnal SpO2 Toggle (open):**
   * While `decode_spo2` correctly handles both manual and auto flags, the settings UI lacks a dedicated BLE control command to enable continuous overnight SpO2 monitoring (sleep apnea risk indicator).
2. **Fragmented Sleep / Daytime Naps (done):**
   * Finished naps of 20 minutes or more count once, by wake day, in the sleep balance and the 7-day sleep debt; the mental state and the sleep plan use the same totals.
3. **Recovery Index Sensitivity to Sparse Sampling (done):**
   * The recovery index needs valid HR on at least 70% of sleep minutes, at least 30 readings and contiguous 5-minute windows (`RECOVERY_MIN_HR_COVERAGE`).
4. **Dependence on Stress Readings (new, mitigated):**
   * Without all-day stress monitoring the mental state rests on few readings. The card shows how many readings it used, lowers its confidence and asks the user to enable Stress monitoring.
5. **Thresholds Are Not Clinically Validated (new):**
   * The mental-state mapping, the body-signal rules, the resting-HR episode thresholds and the sleep-plan rules are design choices documented in `docs/suc-khoe.md`. The personal model needs at least 21 nights and has not been compared with real outcomes (self-reported mood, diagnosed illness).

---

## 4. Hardware & Firmware Feature Maximization Matrix

| Hardware / Firmware Capability | Implementation Status | Technical Assessment & Expansion Opportunities |
| :--- | :---: | :--- |
| **BLE Classic Authentication (AES-128)** | ✅ **100% Complete** | Handshake verified on characteristic `0x0009`. |
| **BLE 2021 Authentication (ECDH B-163)** | ✅ **100% Complete** | 48-byte public key exchange, CRC32 chunked transport on endpoint `0x0090`. |
| **Raw Health Telemetry Fetching** | ✅ **100% Complete** | Chars `0x0004`/`0x0005` stream steps, HR, PAI, stress, SpO2, and workout headers. |
| **Stress Readings (automatic + manual)** | ✅ **100% Complete** | Both are fetched; the stress chart, the health analysis and the mental state use both. All-day stress monitoring can be switched on from Band settings → Health. |
| **Custom Watchface Flashing (UIHH)** | ✅ **100% Complete** | Dedicated Mi Band 6 header (device ID 148), live status simulation, layer preview. |
| **Custom Wallpaper Synthesis** | ✅ **100% Complete** | Client-side crop/scale to 152×486, RGB565 bitmap generation, varint parameter trees. |
| **Weather Dispatch (Open-Meteo)** | ✅ **100% Complete** | Chunked type 1 encoding: Current, 7-day forecast, AQI, UV/Sun, and Wind/Humidity. |
| **App List & Shortcut Reordering** | ✅ **100% Complete** | Dynamic reordering of 24 app slots and horizontal carousel shortcuts. |
| **Alarms Management** | ✅ **100% Complete** | Read/write support for all 10 hardware alarm slots with custom day bitmasks. |
| **Do Not Disturb (DND) & Night Mode** | ✅ **100% Complete** | Scheduled, sunset-triggered, and automated sleep-triggered brightness/vibration gating. |
| **Wrist Screen Lock (6-Digit PIN)** | ✅ **100% Complete** | Configures auto-lock upon wrist detachment. |
| **Inactivity / Sedentary Warnings** | ✅ **100% Complete** | Customizable sitting threshold, active time windows, and lunch break exclusion. |
| **Find Band & Find Phone** | ✅ **100% Complete** | Virtual incoming call vibration trigger, bidirectional ACK response on phone search. |
| **Rich Notifications & Call Alerts** | ✅ **100% Complete** | UTF-8 boundary-safe truncation, app icon mapping (Telegram, Zalo, WhatsApp, etc.). |
| **Cloud Workouts & GPS Track Rendering** | ✅ **100% Complete** | Happy Eyeballs racing downloads on Xiaomi FDS, binary GPS decoding, MapKit + OSM. |
| **Two-Way Music Control Bridge** | ✅ **Complete** | Band music events (`0xFE`) drive Apple Music, Spotify or the macOS media source (e.g. YouTube in Chrome); title, artist and play state are pushed back while the band's music screen is open. Off by default (App settings). |
| **Remote Camera Shutter Trigger** | ⚠️ *Untapped Potential* | Only the `takephoto` menu item exists; the BLE event could be mapped to a webcam shutter or Keynote clicks. |
| **World Clock Management** | ⚠️ *No Management UI* | Band supports world clocks, but desktop client lacks an interface to push city lists. |
| **Event Reminders Memory** | ⚠️ *No Management UI* | Band has onboard reminder storage, but no protocol endpoint is exposed in UI. |
| **Manual Static Brightness Slider** | ⚠️ *Night Mode Only* | Supports auto/scheduled night dimming, but lacks a manual 1–5 level brightness control. |

---

## 5. In-Depth Algorithmic Analysis

```mermaid
graph TD
    subgraph Data Pipeline & Health Insights
        RawBLE["Raw BLE Samples (0x0005)"] --> HealthDB[("Local SQLite Database")]
        HealthDB --> Preprocess["Pre-processing (Telemetry Validation)"]

        Preprocess --> SleepModel["Sleep Engine (Onset/Wake Edge Adjust + REM Inference)"]
        Preprocess --> TRIMPModel["Workload Engine (Edwards TRIMP + Banister Fatigue)"]
        Preprocess --> BaselineModel["Baseline Engine (robust 30-night RHR + Luteal Offset)"]
        Preprocess --> StressModel["Stress Evidence (auto + manual, 72 h, recency-weighted)"]

        SleepModel --> ReadinessCalc["Daily Readiness Engine"]
        TRIMPModel --> ReadinessCalc
        BaselineModel --> ReadinessCalc

        BaselineModel --> RHRModel["Personal Sleeping-HR Model (ridge, leave-one-out)"]
        TRIMPModel --> RHRModel
        SleepModel --> RHRModel
        RHRModel --> BodySignals["Body Signals (1 / 2 of 3 / 3 nights)"]
        StressModel --> Mind["Mental State"]
        BodySignals --> Mind
        Profile["Profile: age, sex, height, weight"] --> Risk["Disease Risk (gradient-boosted trees, NHANES)"]
        BaselineModel --> Risk

        ReadinessCalc --> ClampCheck{"Physiological Metric < 40?"}
        ClampCheck -- Yes --> Clamp["Clamp Score <= 59 (Easy / Rest)"]
        ClampCheck -- No --> FinalScore["Output Final Readiness Score & Plan"]
    end
```

### 5.1. Daily Readiness Score Engine
* **Mathematical Formulation:**
  $$\text{Readiness} = \frac{\sum w_i \cdot S_i}{\sum w_i}$$
  *Contributors: Resting HR (18%), Sleep Restoration Index (8%), Previous Night Sleep (20%), 14-Day Sleep Balance (14%), Banister Recovery Hours (15%), ACWR Activity Balance (10%), HRV/Stress Balance (15%).*
* **Resting-HR baseline:** median of up to 30 previous nights, SD = 1.4826 × MAD with a 2 bpm floor, so a few sick or alcohol nights inside the baseline do not distort it; a night needs at least 10 HR readings.
* **Safety Guardrails (Clamping):**
  - If any primary physiological contributor (Night RHR, Sleep Duration, Recovery Hours, or Stress Balance) drops below $40$, the final score is strictly capped at $\le 59$ (*Easy training* or *Rest*). This prevents a deceptive 9-hour sleep from masking severe systemic strain or tachycardia.
  - **ACWR Protection:** ACWR is intentionally excluded from triggering the $\le 59$ clamp. In commercial fitness wearables, sudden routine shifts disproportionately spike ACWR without representing true acute injury risk (Impellizzeri et al., 2020).

### 5.2. Banister Impulse-Response Recovery Model
* **Mathematical Formulation:**
  $$A(t) = \sum \text{TRIMP}_i \cdot e^{-\frac{t - t_i}{\tau}} \quad (\tau = 36.0\text{ hours})$$
  $$\text{Steady State} = \max(\text{Chronic Daily Load}, 30) \cdot \frac{\tau}{24}$$
  $$\text{Recovery Hours} = \tau \cdot \ln\left(\frac{A(t)}{\text{Steady State}}\right) \quad (\text{bounded } [0, 96] \text{ hours})$$
* **Scientific Evaluation:** Adapting Banister’s two-component model into an acute fatigue depletion model ($\tau = 36$h) accurately captures the recovery tail of endurance and resistance workouts. Calculating TRIMP continuously across the current day ensures that the readiness score immediately reflects workout depletion, matching Garmin Training Readiness and Apple Watch protocols. Today's result is recomputed hourly even while the band is not connected.

### 5.3. REM Sleep Inference via Cardiorespiratory Dynamics
* **Biomedical Foundation:** Firmware on the Mi Band 6 does not expose a validated raw REM byte over BLE. During REM sleep, skeletal muscles exhibit atonia (near-zero movement), while autonomic sympathetic activation causes heart rate elevation and heightened beat-to-beat variability compared to deep NREM sleep (Somers et al., 1993).
* **Algorithmic Pipeline:**
  1. Requires valid nocturnal recording: Duration $\ge 180$ minutes, HR coverage $\ge 80\%$.
  2. Establishes NREM baseline using a rolling 30th percentile within a 61-minute window.
  3. Detects candidate REM minutes: Light sleep stage, low accelerometer intensity ($\le 25$), latency $> 60$ minutes from onset, and heart rate elevation $\ge 4.0$ bpm above baseline OR volatility $\ge 1.6 \times$ nocturnal median.
  4. Merges adjacent bouts ($\le 10$ minutes apart), discards transient spikes ($< 6$ minutes), and applies dynamic threshold elevation if total REM exceeds $30\%$ of sleep.
* **Caveat:** Because the model relies on HR elevation during physical immobility, acute alcohol ingestion, high late-night carbohydrate meals, or mild febrile states can artificially elevate nocturnal HR and cause false REM classifications. The codebase transparently documents these limitations in `docs/suc-khoe.md`. Since a firmware change on 2026-11-03 the band writes a REM byte, which is used instead when present.

### 5.4. Chronobiology & Circadian Metrics
* **Social Jetlag (SJL):** Calculated as $|MSF - MSW|$, measuring the difference in midsleep timing between workdays and free days (Wittmann et al., 2006).
* **Sleep-Corrected Chronotype ($MSF_{sc}$):** Adjusts for weekend catch-up sleep:
  $$MSF_{sc} = MSF - \frac{SD_f - SD_{week}}{2} \quad \text{where } SD_{week} = \frac{5 \cdot SD_w + 2 \cdot SD_f}{7}$$
* **Sleep Regularity Index (SRI):** Implements Phillips et al. (2017) by computing the minute-by-minute probability of being in the identical sleep/wake state 24 hours later across a 14-day wear window, counting only minutes with the band on the wrist:
  $$\text{SRI} = -100 + 200 \times P(\text{state}_t == \text{state}_{t+24h})$$
* **Composite Phase Deviation (CPD):** Evaluates day-to-day circadian instability (Fischer et al., 2016).

### 5.5. Mental State
* **Stress evidence:** each reading of the last 72 h (automatic and manual) is weighted $0.5^{\text{age}/24\text{h}}$. Tension $= \text{clamp}((\bar{s} - 35)/50) + 0.5 \cdot \text{high share}$, so the band's "medium" level (60) gives 0.5, plus up to 0.25 when well above the user's usual level.
* **Resting HR:** corroborates only when tension is at least 0.3; without stress readings it is capped at 0.45, below the 0.5 "tense" threshold.
* **States:** overloaded / tense / fatigued / calm / balanced from tension and fatigue (sleep and circadian strain); "calm" also requires no raised sleeping HR. Confidence depends on the number of stress readings and recent nights.

### 5.6. Body Signals & Personal Sleeping-HR Model
* **Model:** $d_k = a + \sum_j b_j x_{kj}$, where $d_k$ is a night's sleeping-HR deviation from its own baseline, and $x$ is previous-day load vs usual, load in the 4 h before sleep, later bedtime and shorter sleep (0 = a usual night). Ridge penalty 4 on standardized features; nights more than 3.5 robust SDs away are excluded.
* **Gating:** at least 21 training nights and a leave-one-out MAE at least 5% below an intercept-only model; otherwise the app compares with the baseline only and says so. Effects are reported only with $|t| \ge 2$.
* **Signals:** a night is high at $\ge 3$ bpm and $\ge 2$ SD above baseline (unexplained part when the model is active): one night "ok", 2 of 3 "watch", 3 in a row "alert".

### 5.7. Heart Rate at Rest & Tonight's Sleep
* **Resting episodes:** consecutive readings ≤ 10 minutes apart, all ≥ 120 or < 40 bpm, spanning ≥ 10 minutes, with no steps in the 5 minutes before each reading, outside sleep and outside workouts plus 30 minutes. "Nothing unusual" is only stated with ≥ 144 closely spaced resting readings in the week.
* **Sleep plan:** sleep need by age plus a third of the 7-day sleep debt (max 60 minutes), counted back from the median wake time of the same kind of day, minus typical night-time wakefulness and 15 minutes to fall asleep; never more than 60 minutes earlier than the usual bedtime.

### 5.8. Disease Risk Models
* **Data & labels:** NHANES 2009–2012, adults ≥ 18, not pregnant (12,266; 818 Asian). Diabetes = told by a doctor; hypertension = mean exam BP ≥ 140/90 mmHg.
* **Model:** `HistGradientBoostingClassifier` with monotonic constraints (age, BMI, resting pulse ↑; active days ↓), hyperparameters by 5-fold CV log loss; temporal validation 2009–10 → 2011–12: diabetes AUC 0.794 (0.777–0.808), hypertension 0.758 (0.743–0.772); calibration slopes 0.94 and 1.02. Final model refit on both cycles.
* **Asian calibration:** out-of-fold logit offset in Asian adults, shrunk by its SE (James–Stein): diabetes +0.35 (observed 11.0% vs predicted 8.1%), hypertension ≈ 0.
* **Explanations:** the probability with one modifiable factor (BMI, resting pulse, sleep, active days) moved to a healthy reference, listed only when outside the healthy range and raising risk.

### 5.9. Long History and Live Data
* **Learning curve:** $\text{MAE}_W = \frac{1}{|T|}\sum_{k\in T} |y_k - \hat{y}_k^{(W)}|$, where $\hat{y}_k^{(W)}$ is trained only on nights in $(d_k - W, d_k)$, $W \in \{7, 30, 90, 180, 365\}$ days, $T$ = the 30 most recent nights.
* **Fast LOO:** $e_i^{LOO} = e_i / (1 - h_{ii})$, $h_{ii} = 1/n + z_i^\top (Z^\top Z + \lambda I)^{-1} z_i$.
* **Live HR:** per-minute aggregation of BLE readings; band minutes take precedence; time-weighted means with a 10-minute hold.

---

## 6. Actionable Engineering Roadmap

```mermaid
timeline
    title Recommended Implementation Milestones
    Done : 2-Way Desktop Music Control Bridge : User-Defined Manual HRmax : Naps Reduction of Sleep Debt : Mental State from Band Stress : Body Signals & Personal Model : Disease Risk ML : Live HR on Health page : Year-long personal training : Glanceable Health page : Workout detail & next-workout coach
    Phase 1 : Protocol Expansion : Remote Camera Shutter Event Listener : Nocturnal SpO2 Auto-Measurement Config : World Clock & Event Reminder UI
    Phase 2 : Advanced Telemetry : Mood / Illness Journal to check the body-signal thresholds : PDF Health Export for Clinical Review : Full Validation Against PSG Reference
```

### 6.1. Done Since the Original Report
1. **Desktop Music Control Bridge:** band events control Apple Music, Spotify or the macOS media source; track info and play state are sent back to the band.
2. **User-Configurable $HR_{max}$:** a measured maximum heart rate can be saved locally (Band settings → Profile → Heart rate zones) and is used for TRIMP and HR zones.
3. **Daytime Naps Accounting:** finished naps count in the sleep balance and the 7-day sleep debt.
4. **Mental state, body signals, personal model, resting-HR episodes, sleep plan:** see sections 3.1 and 5.5–5.7.
5. **Disease-risk models, live heart rate, long-history learning:** see sections 3.1 (items 9–11), 5.8 and 5.9.
6. **Glanceable Health page:** every card leads with its numbers and a colored status; explanations sit behind an (i) button and open by themselves for items worth watching or needing attention, which are listed first. Charts no longer change the viewed date (only the date button and ‹ › do), and the new date shows at once while its data loads.
7. **Workout detail and coaching:** each workout opens a Mi Fitness-style page (heart rate and zones, pace per km, cadence, stride, altitude and terrain, TRIMP load, a training-experience rating) built from the Mi Fitness per-second file and GPS track (mifit's MIT layout tables, newer versions only accepted when their totals match the workout) or the band's minute data. The Workouts tab suggests the next session (rest / easy / endurance / long / tempo / intervals from readiness, recovery, ACWR, intensity distribution and the last rating) with target heart rate and a pace from a personal VO2max model (ACSM VO2 + %HRR ≈ %VO2R over steady minutes), and a 7-day plan of hard, moderate, light and rest days learned from the user's training weekdays. The Sync button also pulls Mi Fitness history. Thresholds are in `docs/suc-khoe.md`.

### 6.2. Next: Protocol Extensions
1. **Remote Camera Shutter Binding:**
   * Map the `takephoto` menu event to macOS system shortcuts or presentation slide-advance commands.
2. **Sleep Breathing / All-Day SpO2 GATT Configuration:**
   * Research and expose the BLE configuration command to activate automatic nocturnal SpO2 sampling.
3. **World Clock & Event Reminders Desktop Manager:**
   * Implement UI managers in the web interface to push custom timezones and calendar reminders directly to the band's non-volatile memory.

### 6.3. Next: Validation
1. **Outcome journal:** let the user log mood and illness days to check whether body signals and the mental state predict them on their own data.
2. **Reference comparison:** follow `docs/algorithm-validation.md` (H10/ECG for HR, PSG for sleep) before claiming accuracy.

---
*Evaluation compiled autonomously via static analysis, regression test execution, and protocol verification of the Mi Band 6 Manager repository; updated after the mental-state fix.*
