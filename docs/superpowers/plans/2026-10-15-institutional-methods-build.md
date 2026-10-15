# Institutional Methods, Plan 2 (Build and Run H11-H15) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Build the H11-H15 constructions exactly as pre-registered in `research/hypotheses.md` (commit 4b45399), run them on train and validation only, and report verdicts with trial counts and DSR.

**Architecture:** Pure weight-transform functions in two new modules (`src/round2.py`, `src/construction.py`) that take H1 target weights (already lagged) and return new target weights, so `run_backtest` stays untouched. One harness script loads prices only up to `SPLITS.validation_end`, runs baseline and every declared grid config, applies the pre-declared decision rules, and writes `research/round2_results.md`.

**Tech Stack:** pandas, numpy, scipy (linkage), scikit-learn `LedoitWolf` (installed: 1.7.0), pytest, ruff.

## Global Constraints

- Specs come verbatim from `research/hypotheses.md` "Round 2 pre-registration: H11-H15". Grids, primaries, decision rules and priors may not change. No configs may be added after seeing results.
- The 2021-2025 test window must never be loaded: price loading ends at `SPLITS.validation_end`; the harness asserts it.
- One-bar signal lag lives only in `src.features.make_tradable`. New functions use it (or an equivalent explicit `lag` offset) and never shift elsewhere.
- Long-only, gross exposure <= 1 (the engine raises otherwise). Baseline = H1 primary 126/skip21/k5/ME, 10 bps, as deployed.
- Costs: 10 bps headline; report 5/20 bps sweep for primaries only.
- All code passes `ruff check` and `pytest`. Results, including nulls, are appended to `research/daily_log.md` (CRLF, append-only).
- No change to live code paths (`scripts/run_live*.py`, `src/execution.py`, `src/sleeves.py`). No change to live sizing.

## Implementation decisions (made before any result, recorded here)

1. **Common evaluation start.** Variants need different warm-ups (e.g. 252-bar gate). To compare like with like, within each hypothesis the metrics window starts at the latest first-valid rebalance date across the baseline and every grid config. Baseline and variants are scored on the identical dates. The start dates are reported.
2. **H11 drift.** The band is applied against *drifted* current weights, simulated with the same drift and risk-free-cash formula as `run_backtest`, so b=0, phi=1 reproduces the baseline exactly (tested).
3. **H13 "state ON >= 3% of days"** is measured on daily SPY state (vol > theta and trailing return < 0, lagged one bar) within the evaluation window; the share of monthly rebalances acted on is also reported.
4. **H14 cap.** Per pre-registration, max 25% per asset, remainder to cash. For k=3 this caps gross at 75% for ERC/HRP versus 100% for equal weight; this is a stated structural handicap, reported not fixed.
5. **H12 exposure** e is the mean gross exposure of the VT10 portfolio over the window (ex post, acceptable for a diagnostic). Constant-exposure baseline return = e * r(H1 EW net) + (1-e) * rf.

## File map

- Create `src/round2.py`: `apply_no_trade_band` (H11), `apply_regime_scaling` (H13), `apply_absolute_gate` (H15), `common_start`.
- Create `src/construction.py`: `erc_weights`, `hrp_weights`, `apply_risk_construction` (H14).
- Create `tests/test_round2.py`, `tests/test_construction.py`.
- Create `scripts/run_round2.py`: harness for H11-H15 incl. H12 diagnostic; writes `research/round2_results.md`.
- Modify `research/daily_log.md`, `research/hypotheses.md` (append-only amendment for results/verdicts only).

---

### Task A: H11, H13, H15 transforms with tests

**Interfaces (produces):**
- `apply_no_trade_band(targets: DataFrame, prices: DataFrame, rf_daily: Series, band: float, phi: float) -> DataFrame`
- `apply_regime_scaling(weights: DataFrame, spy: Series, theta: float, scale: float, window: int, vol_window: int = 63, lag: int = 1) -> DataFrame`
- `apply_absolute_gate(weights: DataFrame, prices: DataFrame, rf_daily: Series, gate_window: int, lag: int = 1) -> DataFrame`
- `regime_state(spy, theta, window, vol_window=63, lag=1) -> Series` (1.0 ON, 0.0 OFF, NaN unknown)
- `common_start(frames: list[DataFrame]) -> Timestamp`

**Tests (`tests/test_round2.py`):**
- band b=0, phi=1 gives backtest returns identical (`allclose`) to the unbanded baseline.
- band b=0.04 lowers total turnover on a synthetic noisy panel; weights stay in [0,1], sum <= 1.
- band rows only on baseline rebalance dates (NaN elsewhere).
- shift-invariance for all three: perturb prices strictly after cutoff t, outputs up to and including t are bit-identical.
- regime scaling: ON rows are exactly `scale` times baseline, OFF rows equal baseline; unknown state (NaN) leaves the row at baseline *and counts as OFF*.
- gate: an asset whose trailing return is below risk-free gets weight 0 and the weight is not reallocated (cash); an asset above keeps its weight; insufficient history gives a NaN row.
- `common_start` returns the latest first non-NaN row date.

- [ ] Write tests, run (fail), implement, run (pass), `ruff check`, commit `feat: H11/H13/H15 weight transforms with bias tests`.

### Task B: H14 ERC and HRP with tests

**Interfaces (produces):**
- `erc_weights(cov: np.ndarray, iters: int = 500, tol: float = 1e-12) -> np.ndarray` (sums to 1, long-only, cyclical coordinate descent)
- `hrp_weights(cov: np.ndarray) -> np.ndarray` (Lopez de Prado 2016: correlation distance sqrt((1-rho)/2), single linkage, quasi-diagonalisation, recursive bisection with inverse-variance cluster weights; sums to 1)
- `apply_risk_construction(weights, prices, method: Literal["erc","hrp"], cov_window=252, max_weight=0.25, lag=1) -> DataFrame` — keeps H1 selection, sizes by method using Ledoit-Wolf shrunk covariance of the trailing `cov_window` daily returns ending `lag` bars before the rebalance date; clips at `max_weight`, remainder to cash; rows with insufficient or NaN history stay at the input weights' NaN-ness (row NaN).

**Tests (`tests/test_construction.py`):**
- ERC on diagonal cov gives weights proportional to 1/sigma; risk contributions equal (tolerance 1e-6) on a random PSD cov.
- HRP sums to 1, non-negative; two uncorrelated assets give inverse-variance weights.
- `apply_risk_construction`: max weight respected, sum <= 1, selection unchanged (zero stays zero), shift-invariance of outputs at and before the cutoff under future price perturbation.

- [ ] Write tests, run (fail), implement, run (pass), `ruff check`, commit `feat: H14 ERC/HRP construction with Ledoit-Wolf and bias tests`.

### Task C: Harness, train and validation runs, verdicts

**Files:** Create `scripts/run_round2.py`.

Behaviour:
- Loads prices/rf with end date `SPLITS.validation_end`; `assert px.index.max() <= pd.Timestamp(SPLITS.validation_end)`.
- For each window (train, validation) and each hypothesis, builds baseline + the declared grid exactly (H11 15, H13 12, H14 27, H15 9; H12 25 configs x 2 periods) using the shared `common_start`.
- Prints and writes tables: net Sharpe, ann return, vol, max drawdown, ann turnover for primaries vs baseline; grid pass-rates; H13 state shares; H12 cash-drag share and timing value medians; 5/20 bps sweep for primaries.
- Applies each decision rule from the pre-registration literally and prints SUPPORTED / NOT SUPPORTED / UNINFORMATIVE per hypothesis, plus the trial counts (H11 15, H12 50, H13 12, H14 27, H15 9; cumulative >= 438).
- Applies the freeze rule: if >=1 of H11/H13/H14/H15 is Supported, prints the one with the largest validation net-Sharpe improvement over baseline at its primary config; otherwise prints "NO CANDIDATE FROZEN; test window untouched".

- [ ] Run once on train+validation, save output to `research/round2_results.md` (script writes it), append a dated entry to `research/daily_log.md`, run full `pytest` + `ruff`, commit and push.

### Task D: DSR and honest verdict (conditional)

- [ ] For any Supported hypothesis, compute the validation DSR of the frozen primary against the declared cumulative ledger (>= 438 trials; Sharpe variance from the logged grid Sharpes) using `src.overfitting`. Report whether >= 0.95. Record result in `research/round2_results.md` and the daily log.

### Task E: Freeze and one-touch test (ONLY if Task C froze a candidate)

- [ ] Record frozen config and `git hash-object` of the code, commit "freeze candidate" *before* running anything on test. Run test once, log as-is. If no candidate was frozen: skip and state that the test window is untouched.
- [ ] Shadow portfolio (paper-only, non-trading) only if the test is also passed; not started otherwise.
- [ ] Intraday cost-realism study remains deferred (research-only, last priority).
