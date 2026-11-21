import pandas as pd
from scripts.run_ensemble import append_snapshot
from scripts.build_dashboard import ensemble_section

ROW = dict(date="2026-11-23", ts_utc="t", equity=100000.0, spy_close=700.0, scale=1.0,
           killed=False, gross_target=0.73, n_targets=70, n_orders=58, n_failed=0)


def test_append_snapshot_header_once(tmp_path):
    p = tmp_path / "s.csv"
    append_snapshot(p, ROW)
    append_snapshot(p, dict(ROW, date="2026-11-24", equity=101000.0, spy_close=693.0))
    df = pd.read_csv(p)
    assert list(df.columns) == list(ROW) and len(df) == 2


def test_section_reports_excess_vs_spy():
    snap = pd.DataFrame([ROW, dict(ROW, date="2026-11-24", equity=101000.0, spy_close=693.0)])
    html = ensemble_section(snap)
    assert "+1.00%" in html and "-1.00%" in html and "+2.00" in html  # ens, SPY, excess pp


def test_section_empty():
    assert "not started" in ensemble_section(pd.DataFrame()).lower()
