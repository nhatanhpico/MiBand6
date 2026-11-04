# Mi Band 6 algorithm validation and calibration

Status: engineering protocol and working offline benchmark tool; no new human-subject accuracy results have been collected. Research checked 3 November 2026. Passing software tests verifies calculations and data handling, not sensor accuracy. The limits below are proposed product acceptance targets, not clinical standards or proof that Mi Band 6 meets them.

## Evidence and capability boundaries

Xiaomi identifies six-axis motion sensing, PPG, whole-day/manual/resting HR, stress, PAI, and deep/light/REM/nap reporting. Its documented SpO₂ measurement is a 25–50 second spot measurement affected by motion and fit. A feature available in the companion app does not establish that this project's BLE decoder can retrieve its proprietary result. Preserve the distinction between vendor-reported REM, locally estimated REM, and unavailable data. [Xiaomi Mi Smart Band 6 FAQ](https://www.mi.com/sg/support/faq/details/KA-07049/)

A 2025 Mi Band 6 six-minute-walk validation reported better agreement for HR than oxygen saturation and variable distance estimation. A 2026 study in 35 children/adolescents with severe cerebral palsy also cautions against treating the band as a clinical monitor. Those populations and test conditions do not justify a universal accuracy claim for this app, high-intensity exercise, overnight sleep, or every firmware revision. [Six-minute walk study](https://www.mdpi.com/1424-8220/25/8/2621), [Cerebral palsy study](https://pmc.ncbi.nlm.nih.gov/articles/PMC12899449/)

The H10 is a useful ECG-based field comparator for HR/RR. A study of 25 participants compared it with ECG at rest and during incremental exercise; this does not turn every H10 recording into an error-free clinical reference. Capture signal quality and inspect artifacts on both devices. [H10 validation](https://pmc.ncbi.nlm.nih.gov/articles/PMC9459793/)

For absolute SpO₂ accuracy, arterial co-oximetry is the laboratory comparator; comparison with a medical finger oximeter establishes inter-device agreement only. Skin pigmentation, perfusion, temperature, and motion can affect oximetry. Do not induce desaturation for informal product testing. [FDA pulse oximeter information](https://www.fda.gov/medical-devices/products-and-medical-procedures/pulse-oximeters), [FDA performance discussion](https://www.fda.gov/media/173905/download)

PSG is the sleep-stage reference. A primary study of six other wearables used PSG/ECG, stage-by-stage agreement and kappa, illustrating that good sleep/wake agreement does not imply accurate staging. That study did **not** test Mi Band 6 and its results must not be transferred to this device. [Wearable sleep validation methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC9412437/)

## Runnable benchmark

Run from the project directory:

```sh
.venv/bin/python -m miband6.validation reference.csv band.csv --tolerance 5 > benchmark.json
```

Both CSV files use exactly these required column names; extra metadata columns are permitted but are not consumed:

```csv
participant,session,metric,timestamp,value
p01,rest-01,hr,1793692800,65
p01,rest-01,hr,1793692860,66
p01,sleep-01,sleep_stage,1793664000,light
```

- `timestamp`: UTC Unix seconds, including fractional seconds if needed. Convert local time using the recorded offset before export. Record both clocks' pre-session and post-session offsets in the study manifest.
- `participant` and `session`: pseudonymous identifiers. Never combine unrelated people, firmware, or recording conditions into a session.
- `metric`: `hr` in bpm, `spo2` in percentage points, `steps` per fixed comparison window, `sleep_duration` in minutes, or `sleep_stage` using `awake`, `light`, `deep`, `rem`. Numeric metrics may use other names if both files use the same unit.
- Export the exact same averaging windows from both instruments first. A five-minute HR setting is not five one-minute observations. Do not duplicate a measurement to improve coverage.
- Alignment is chronological and one-to-one: earliest eligible pair within the declared tolerance. No reference observation is reused, no timestamps are shifted to maximize agreement, and no gaps are interpolated. This is not nearest-neighbor optimization. Use a tolerance below half the comparison window; for one-minute exports, 5 seconds is a starting target after clock correction.
- Invalid/missing values, blank identities/timestamps, NaN and infinity are counted and excluded. Identical timestamp duplicates are counted once per participant/session/metric; conflicting duplicates stop the run so the source must be resolved explicitly.
- Output contains per-session metrics, unmatched counts on both sides, and input exclusions. Metrics are descriptive; no pass/fail or clinical conclusion is automatically inferred. Preserve and report excluded raw rows separately. A nonfinite numeric value is invalid; a very low but finite SpO₂ value is not silently discarded by this tool.

For sleep, export common 30-second epochs only if the band source actually has that resolution. For minute-only band data, predefine a 60-second comparison, map PSG N1+N2 to light and N3 to deep, and state the rule for discordant paired PSG epochs (e.g. mark mixed and exclude with a separate count). Do not duplicate minute labels into two apparently independent epochs. Label estimated REM as a separate algorithm/source, never as the vendor's result.

## Statistics and interpretation

For paired reference `xᵢ` and band `yᵢ`, `dᵢ = yᵢ − xᵢ`:

| Statistic | Definition | Guardrail |
|---|---|---|
| MAE | mean(`abs(dᵢ)`) | Same units as the metric |
| MAPE | `100 × mean(abs(dᵢ/xᵢ))` | Zero references excluded only from MAPE; count reported; all-zero reference gives null |
| RMSE | `sqrt(mean(dᵢ²))` | SpO₂ expressed in percentage points, not relative percent |
| Pearson r | covariance divided by product of SDs | Null for <2 pairs or a constant series; correlation does not prove agreement |
| Bland–Altman bias | mean(`dᵢ`) | Sign is band minus reference |
| 95% limits of agreement | bias ± `1.96 × sample_SD(dᵢ)` | Null for <2 pairs; limits are not confidence intervals |
| Sleep classification | Confusion matrix, accuracy, per-stage precision/recall/F1, macro F1, Cohen's κ | Matrix rows are reference, columns band; absent stages and undefined κ are explicit nulls |

Bland–Altman normal-error limits are exploratory for small, skewed, or heteroscedastic samples. Inspect difference-versus-mean plots before interpreting them. Multiple epochs from one person do not create independent subjects. The CLI intentionally reports each participant/session separately. A release study additionally needs participant-clustered bootstrap confidence intervals or a repeated-measures agreement model, preregistered strata, and a held-out participant set. Those inferential analyses are not implemented in this small CLI.

## Proposed acceptance targets

These are initial engineering gates for a wellness UI, chosen for development planning. Freeze targets and analysis rules before collecting validation data; revise only with documented rationale. Passing an aggregate must not hide failure in a subgroup or activity condition.

| Outcome | Proposed gate | Required comparison/conditions |
|---|---|---|
| HR at rest | MAE ≤5 bpm, MAPE ≤5%, RMSE ≤7 bpm; LoA within −10 to +10 bpm | Simultaneous reviewed H10/ECG; seated and standing |
| HR during steady activity | MAE ≤10 bpm, MAPE ≤10%, RMSE ≤12 bpm; LoA within −20 to +20 bpm | Walking, running, cycling separately; interval exercise is a separate stratum |
| SpO₂ spot agreement | MAE ≤2 percentage points, RMSE ≤3 points; absolute bias ≤1.5 points; LoA within ±4 points | Stable simultaneous medical-oximeter comparisons; report observed saturation range and subgroup results |
| Steps | MAPE ≤5% at usual pace; ≤10% at slow pace | Video/manual counted standardized walks; fixed window totals |
| Nonwalking false steps | Median ≤10 false steps per 10-minute typing/driving/passive-arm trial | Ground-truth steps zero: use absolute error, never MAPE |
| Sleep duration | MAE ≤30 minutes; absolute bias ≤15 minutes per night | Concurrent PSG, plus naps separately |
| Sleep staging | Macro F1 ≥0.60, κ ≥0.40, each supported stage recall ≥0.50 | PSG blinded scoring; report stage prevalence and uncertainty |
| Availability | ≥90% expected samples/windows in eligible wear periods | Report total collection coverage and valid-pair coverage separately |

`r` is reported rather than used as a standalone gate. Tight physiological ranges can yield low r despite useful absolute agreement. HRV acceptance remains blocked until actual beat-to-beat RR with validated timing is available; minute HR changes are not HRV. Stress and PAI are vendor indices; they have no direct ECG/PSG equivalent and must not receive fabricated MAPE-to-clinical-reference results.

## Study and calibration procedure

1. Run an initial feasibility pilot (suggestion: 12–20 adults, at least two sessions per condition), then power the release study from the observed participant-level error and desired precision. A pilot is not certification. Include variation in age, skin pigmentation, wrist size, fit, movement intensity, and recording settings.
2. Record device model/firmware, companion app and version, parser/algorithm version, sampling mode, wrist, fit, skin-tone method, reference instrument/calibration, clock offset/drift, and signal-quality exclusions. Keep the pseudonym key separately from measurements.
3. Collect seated rest, walking, stairs, running, cycling, vigorous wrist motion, loose-fit, and nonwalking trials. Record motion labels independently. For sleep, include multiple nights and naps; do not tune and evaluate the same night.
4. Split by participant into development and held-out validation sets. Learn calibration only on development subjects. Keep the uncorrected series and compare both pipelines on the identical held-out pairs.
5. If justified, fit `corrected = a + b × device` separately for the relevant metric/condition. Report coefficients, training population, fit uncertainty, held-out bias/LoA, and calibration version. No blanket subtraction from low SpO₂ readings and no firmware-wide offset borrowed from another device.
6. Publish coverage, missingness, subgroup errors, rejected/flagged counts, and failure cases beside average accuracy. Retest after firmware, parsing, filtering, or score formula changes.

## Conservative quality and custom-score policy

Keep immutable decoded values and reason codes. Invalid encodings, out-of-range stress (>100), SpO₂ outside 1–100, and the device's known missing HR sentinels are excluded from aggregates. HR outside the project's 30–220 bpm display envelope is a quality flag rather than proof of physiological impossibility. A jump >50 bpm in one minute at reported rest is suspect, not automatically overwritten. Low SpO₂ is retained with a fit/recheck cue; abrupt changes are marked uncertain, not averaged into reassuring values.

A three-sample moving median may be used for a separately labeled HR trend only after quality gating and within contiguous sampling intervals. Do not use a band-pass or Kalman filter on minute HR to imply recovery of raw PPG or beat timing. False steps from typing/driving cannot be reliably removed from already accumulated steps without validated motion/context inputs; retain original totals and flag uncertain intervals. These are proposed quality rules; the telemetry module's actual reason codes are the implementation source of truth.

An interpretable candidate readiness formula, **not a clinically validated score and not a replacement of the app's existing formula**, is:

```text
baseline_RHR = median(valid nighttime/resting HR from previous 14 eligible days)
R = clamp(100 - 5 × max(0, today_RHR - baseline_RHR), 0, 100)
S = clamp(100 × last_night_sleep_minutes / personal_sleep_target_minutes, 0, 100)
load = sum(valid minute intensity) / covered_wear_minutes
baseline_load = median(load from previous 14 eligible days)
A = clamp(100 - 40 × max(0, load / baseline_load - 1), 0, 100)
readiness_candidate = round(0.40 × R + 0.40 × S + 0.20 × A)
```

Intensity is a device-specific proxy, not calibrated acceleration. Require at least seven eligible baseline days, adequate nighttime HR and wear coverage, complete sleep, and positive baseline load; otherwise withhold the candidate score rather than substitute zeros or silently renormalize weights. Use a declared personal sleep target, expose contributing values, and label this as an experimental day-over-day trend. Cap sleep contribution at its target, but do not imply excess sleep is clinically good or bad. Validate sensitivity to missingness before release.

Prefer reported band calories with their source attached. If a custom exercise estimate is needed, a separately labeled MET estimate can use `kcal = MET × 3.5 × weight_kg / 200 × minutes`; active calories subtract the 1-MET baseline. Map movement intensity to MET only after calibration against indirect calorimetry for the intended activities. Do not derive clinical energy expenditure from uncalibrated intensity counts. Keep vendor stress separate from any custom readiness proxy and never label either as real-time without a fresh measurement timestamp.

## In-app checks that run on the user's own data

These run automatically and are reported in the UI. They check internal consistency and personal-model usefulness; they are not clinical validation.

- **Sleep vs Mi Fitness** (`HealthDB.sleep_validation`, shown under the Sleep card): after a Mi Fitness import, each night of at least 3 hours is recomputed *without* that night's Mi Fitness numbers and without calibration, and the mean absolute error of bedtime, wake time, duration, deep and REM minutes is reported. Mi Fitness is itself a wearable estimate, so this measures agreement with the vendor, not accuracy against PSG.
- **Personal resting-HR model** (`models.rhr_model`, shown in the Body signals card): a ridge regression of each night's sleeping-HR deviation from its baseline on four known causes (previous day's training load, load in the 4 hours before sleep, later bedtime, shorter sleep). It is evaluated by leave-one-out cross-validation against an intercept-only model on the same nights, and used only with at least 21 training nights and a leave-one-out MAE at least 5% lower. Nights more than 3.5 robust SDs away (usually illness) are excluded from training, the 3 most recent nights are never in the training set, and a learned effect is shown only when its coefficient has |t| >= 2. The UI states when the model is not used and why.
- **Mental state is anchored to the band's own index**: tension is derived only from the band's stress readings (automatic and manual, last 72 h). Sleeping heart rate is never converted into "stress"; without stress readings it is capped below the "tense" threshold and shown as a physical sign. This keeps the card consistent with what the band displays, rather than inferring HRV that the band does not expose.
- **Heart rate at rest** (`health.rest_hr_events`): Apple-style episodes (>= 120 or < 40 bpm for >= 10 minutes while awake, still and outside workouts). The app only reports "nothing unusual" when the week has enough closely spaced resting readings (>= 144 readings no more than 10 minutes apart); sparse sampling cannot rule out a 10-minute episode. Arm movement without steps can produce artifacts, which the text says.

## Completion evidence and remaining work

Implemented: a standard-library CLI with guarded numeric statistics, epoch sleep confusion/kappa, deterministic non-reusing alignment, duplicate protection, explicit missingness, and regression tests. The in-app checks above (sleep vs Mi Fitness, personal-model cross-validation, stress-anchored mental state, resting-HR episode coverage) also run with regression tests. Test fixtures are synthetic and are not evidence of device accuracy.

Not performed: simultaneous Mi Band 6/H10 recordings, clinical oximeter comparison, PSG collection, participant study, calibration learned against a reference instrument, regulatory validation, or any check of the mental-state, body-signal or resting-HR thresholds against real outcomes (self-reported mood, diagnosed illness, ECG). No threshold has been claimed as empirically achieved. A release decision requires the held-out evidence above.
