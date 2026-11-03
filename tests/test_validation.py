import json
import math

import pytest

from miband6.validation import align, benchmark, load_csv, numeric_metrics, sleep_metrics, main


def test_numeric_agreement_and_sample_sd():
    result = numeric_metrics([(10, 12), (20, 18), (30, 34)])
    assert result['rmse'] == pytest.approx(math.sqrt(8))
    assert result['bias'] == pytest.approx(4 / 3)
    assert result['mape_pct'] == pytest.approx((20 + 10 + 100 * 4 / 30) / 3)
    assert result['loa95'][0] == pytest.approx(4 / 3 - 1.96 * math.sqrt(28 / 3))
    assert result['pearson_r'] > 0.9


def test_zero_reference_and_constant_series_are_explicit():
    result = numeric_metrics([(0, 1), (0, 2)])
    assert result['mape_pct'] is None and result['mape_n'] == 0
    assert result['pearson_r'] is None
    assert numeric_metrics([(1, 2)])['loa95'] is None
    assert numeric_metrics([])['rmse'] is None


def test_alignment_is_one_to_one_and_tolerance_bounded():
    pairs, missing_ref, missing_band = align([(0, 10), (1, 11), (10, 12)], [(0.5, 20)], 1)
    assert pairs == [(10, 20)]
    assert (missing_ref, missing_band) == (2, 0)
    assert align([(0, 10)], [(2, 20)], 1)[0] == []
    with pytest.raises(ValueError):
        align([], [], -1)


def test_csv_validation_duplicates_and_sessions(tmp_path):
    p = tmp_path / 'a.csv'
    p.write_text('participant,session,metric,timestamp,value\np1,s1,hr,0,60\np1,s1,hr,0,60\np1,s2,hr,0,61\np1,s2,hr,1,nan\np1,s2,hr,,62\n')
    groups, counts = load_csv(p)
    assert len(groups) == 2
    assert counts == {'rows': 5, 'valid': 2, 'invalid': 2, 'duplicates': 1}
    report = benchmark(groups, {('p1', 's1', 'hr'): [(0, 65)]}, tolerance=0)
    assert len(report) == 2
    assert report[0]['statistics']['bias'] == 5
    assert report[1]['statistics']['n'] == 0
    assert report[1]['unmatched_reference'] == 1
    p.write_text('participant,session,metric,timestamp,value\np1,s1,hr,0,60\np1,s1,hr,0,61\n')
    with pytest.raises(ValueError, match='Conflicting'):
        load_csv(p)


def test_sleep_confusion_and_kappa():
    result = sleep_metrics([('light', 'light'), ('deep', 'light'), ('rem', 'rem'), ('awake', 'awake')])
    assert result['accuracy'] == 0.75
    assert result['kappa'] == pytest.approx(2 / 3)
    assert result['confusion']['deep']['light'] == 1
    assert result['per_stage']['deep']['recall'] == 0
    assert result['per_stage']['deep']['precision'] is None
    assert sleep_metrics([('awake', 'awake')])['kappa'] is None


def test_cli_json_has_no_nan_and_tracks_exclusions(tmp_path, capsys):
    p = tmp_path / 'a.csv'
    p.write_text('participant,session,metric,timestamp,value\np1,s1,hr,1,60\np1,s1,hr,2,nan\n')
    assert main([str(p), str(p), '--tolerance', '0']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['reference_input']['invalid'] == 1
    assert output['groups'][0]['statistics']['pearson_r'] is None
