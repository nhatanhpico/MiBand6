"""Offline agreement analysis; no BLE access and no clinical certification.

CSV columns: participant,session,metric,timestamp,value. Timestamps are UTC
Unix seconds. Inputs must already use identical units and averaging windows.
Run: python -m miband6.validation reference.csv band.csv --tolerance 5
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

STAGES = ('awake', 'light', 'deep', 'rem')


def numeric_metrics(pairs: list[tuple[float, float]]) -> dict:
    """Pairs are (reference, band); differences and bias are band - reference."""
    if any(not math.isfinite(v) for pair in pairs for v in pair):
        raise ValueError('Metrics require finite values')
    n = len(pairs)
    differences = [band - ref for ref, band in pairs]
    mape = [abs((band - ref) / ref) * 100 for ref, band in pairs if ref != 0]
    bias = statistics.mean(differences) if n else None
    loa = None
    r = None
    if n > 1:
        sd = statistics.stdev(differences)
        loa = [bias - 1.96 * sd, bias + 1.96 * sd]
        refs, bands = zip(*pairs)
        if min(refs) != max(refs) and min(bands) != max(bands):
            r = statistics.correlation(refs, bands)
    return {
        'n': n, 'mae': statistics.mean(map(abs, differences)) if n else None,
        'rmse': math.sqrt(statistics.mean(d * d for d in differences)) if n else None,
        'mape_pct': statistics.mean(mape) if mape else None, 'mape_n': len(mape),
        'mape_zero_reference_excluded': n - len(mape),
        'pearson_r': r, 'bias': bias, 'loa95': loa,
    }


def sleep_metrics(pairs: list[tuple[str, str]]) -> dict:
    """Epoch-level confusion matrix: rows reference, columns band."""
    matrix = {ref: {band: 0 for band in STAGES} for ref in STAGES}
    for ref, band in pairs:
        if ref not in STAGES or band not in STAGES:
            raise ValueError('Unknown sleep stage')
        matrix[ref][band] += 1
    n = len(pairs)
    actual = {s: sum(matrix[s].values()) for s in STAGES}
    predicted = {s: sum(matrix[r][s] for r in STAGES) for s in STAGES}
    accuracy = sum(matrix[s][s] for s in STAGES) / n if n else None
    chance = sum(actual[s] * predicted[s] for s in STAGES) / (n * n) if n else None
    per_stage = {}
    for s in STAGES:
        tp = matrix[s][s]
        denom = actual[s] + predicted[s]
        per_stage[s] = {'support': actual[s],
                        'precision': tp / predicted[s] if predicted[s] else None,
                        'recall': tp / actual[s] if actual[s] else None,
                        'f1': 2 * tp / denom if denom else None}
    f1s = [v['f1'] for v in per_stage.values() if v['f1'] is not None]
    return {'n': n, 'confusion': matrix, 'accuracy': accuracy,
            'kappa': (accuracy - chance) / (1 - chance) if n and chance < 1 else None,
            'per_stage': per_stage, 'macro_f1': statistics.mean(f1s) if f1s else None}


def align(reference: list[tuple], band: list[tuple], tolerance: float) -> tuple:
    """Chronological one-to-one matching, earliest eligible pair first.

    Never reuses samples, interpolates, shifts time, or optimizes agreement.
    Pre-aggregate both instruments to identical windows before matching.
    """
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError('Tolerance must be finite and nonnegative')
    reference, band = sorted(reference), sorted(band)
    i = j = 0
    pairs = []
    while i < len(reference) and j < len(band):
        rt, rv = reference[i]
        bt, bv = band[j]
        if abs(rt - bt) <= tolerance:
            pairs.append((rv, bv))
            i += 1
            j += 1
        elif rt < bt:
            i += 1
        else:
            j += 1
    return pairs, len(reference) - len(pairs), len(band) - len(pairs)


def load_csv(path: Path) -> tuple[dict, dict]:
    groups = defaultdict(dict)
    counts = dict(rows=0, valid=0, invalid=0, duplicates=0)
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        required = {'participant', 'session', 'metric', 'timestamp', 'value'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f'{path}: required columns: {", ".join(sorted(required))}')
        for line, row in enumerate(reader, 2):
            counts['rows'] += 1
            try:
                key = tuple((row[name] or '').strip() for name in ('participant', 'session', 'metric'))
                ts = float(row['timestamp'])
                value = row['value'].strip().lower() if key[2] == 'sleep_stage' else float(row['value'])
                if not all(key) or not math.isfinite(ts):
                    raise ValueError('Missing identity or timestamp')
                if key[2] == 'sleep_stage':
                    if value not in STAGES:
                        raise ValueError('Unknown stage')
                elif not math.isfinite(value):
                    raise ValueError('Nonfinite reading')
            except (ValueError, TypeError, AttributeError):
                counts['invalid'] += 1
                continue
            if ts in groups[key]:
                if groups[key][ts] != value:
                    raise ValueError(f'{path}:{line}: Conflicting duplicate for {key} at {ts}')
                counts['duplicates'] += 1
                continue
            groups[key][ts] = value
            counts['valid'] += 1
    return {key: sorted(values.items()) for key, values in groups.items()}, counts


def benchmark(reference: dict, band: dict, tolerance: float = 5) -> list[dict]:
    results = []
    for key in sorted(reference.keys() | band.keys()):
        pairs, missing_ref, missing_band = align(reference.get(key, []), band.get(key, []), tolerance)
        stats = sleep_metrics(pairs) if key[2] == 'sleep_stage' else numeric_metrics(pairs)
        results.append({'participant': key[0], 'session': key[1], 'metric': key[2],
                        'unmatched_reference': missing_ref, 'unmatched_band': missing_band,
                        'statistics': stats})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path)
    parser.add_argument('band', type=Path)
    parser.add_argument('--tolerance', type=float, default=5, help='Maximum timestamp difference in seconds (default 5)')
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.tolerance) or args.tolerance < 0:
            raise ValueError('Tolerance must be finite and nonnegative')
        reference, ref_counts = load_csv(args.reference)
        band, band_counts = load_csv(args.band)
        report = {'version': 1, 'tolerance_seconds': args.tolerance,
                  'alignment': 'chronological_one_to_one',
                  'reference_input': ref_counts, 'band_input': band_counts,
                  'groups': benchmark(reference, band, args.tolerance),
                  'note': 'Descriptive agreement only. Repeated observations are not independent participants. No clinical certification.'}
        print(json.dumps(report, indent=2, allow_nan=False))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
