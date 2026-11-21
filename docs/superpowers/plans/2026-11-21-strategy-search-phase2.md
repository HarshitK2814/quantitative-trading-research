# Strategy Search — Phase 2 Plan (reporting)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** Make the live ensemble's record visible: a daily ensemble snapshot, plus a dashboard section comparing it with SPY.

**Scope decisions (2026-11-21):**
- **30-min intraday:** dropped. Sessions end by 12:00 ET, so the documented intraday effect (last half-hour) can't be traded.
- **Options proxy (`^PUT`) and VIX/VIX3M filter:** tested, both rejected. Each improved one of train/valid but not both; see `research/strategy_search.md`.
- **Weekly email:** `scripts/weekly_report.py` already exists. Scheduling it plus a Gmail draft is a follow-up that needs the user's OK (it's a cloud routine).

## Global Constraints
- Paper only. Never pass `--execute` in tests or verification.
- Journals are append-only CSVs under `portfolio/`. Never rewrite past rows.
- Dashboard figures come only from committed files (see the `build_dashboard.py` docstring).
- Tests: `PYTHONPATH=. python -m pytest tests -q`.

### Task 1: Ensemble snapshot + dashboard section + wiring

**Files:** Modify `scripts/run_ensemble.py`, `scripts/build_dashboard.py`, `scripts/run_session_local.ps1`. Create `tests/search/test_snapshot.py`.

**Interfaces — Produces:**
- `append_snapshot(path: Path, row: dict) -> None` in `scripts/run_ensemble.py`. Writes a header on first write; columns `date, ts_utc, equity, spy_close, scale, killed, gross_target, n_targets, n_orders, n_failed`.
- `ensemble_section(snap: pd.DataFrame) -> str` in `scripts/build_dashboard.py`. Returns an HTML block.

- [ ] **Step 1: Failing tests** in `tests/search/test_snapshot.py`:

```python
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
```

- [ ] **Step 2:** Run it and confirm it fails.
- [ ] **Step 3: Implement**
  - In `run_ensemble.py main()`: with `--execute` only, after orders, call `append_snapshot(Path("portfolio/ensemble_snapshot.csv"), {...})`. Take `spy_close` from the panel's last SPY close. `killed = state.get("killed", False)`.
  - In `build_dashboard.py`: add `ensemble_section(snap)`, which renders:
    - A heading "Live ensemble (from 2026-11-23)".
    - Ensemble return since first row, SPY return since first row, and the excess in percentage points (format `+1.00%` and `+2.00 pp`).
    - Current drawdown from peak, kill-switch state, the latest gross target and the number of positions.
    - A sparkline of equity using the existing `_sparkline`.
    - Empty frame → `<p class="muted">Ensemble not started yet.</p>`.
  - Load `portfolio/ensemble_snapshot.csv` in `build()` if it exists, keeping the last row per date, and insert the section near the top of the page.
  - In `scripts/run_session_local.ps1`, inside the `$h -eq 9` block after the ensemble run, add `cmd /c "`"$py`" scripts/build_dashboard.py >> $log 2>&1"`. Add `portfolio/ensemble_snapshot.csv docs/index.html` to its `git add` line.
- [ ] **Step 4:** Run the tests and confirm they pass, then run `PYTHONPATH=. python scripts/build_dashboard.py` and confirm it writes `docs/index.html` without error.
- [ ] **Step 5:** Commit.
