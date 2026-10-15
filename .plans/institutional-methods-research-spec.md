# Institutional-methods research program — spec

**Written:** 2026-10-15 · **Status:** agreed via interview, not yet planned or built
**Repo:** `Paper Trading` (quantitative-trading-research)

## 1. Goal (agreed)

Produce work that is **both** (a) a credible, honest research story an MSCF
admissions reader can verify, **and** (b) a genuine attempt at a real
out-of-sample risk-adjusted edge. Not a good-looking P&L number.

- No hard deadline: do it properly.
- "Novel" = **both**: replicate published institutional methods honestly, **and**
  add one original layer derived from this project's own ledger and logs.
- Non-goals: tuning anything to make the live P&L look better; claiming hedge
  fund performance; quoting live P&L (a few weeks of paper returns carry no
  statistical information; see `admissions/resume_framing.md`).

## 2. Honest expectations (stated up front, to be repeated in the final report)

- Prop firms and hedge funds get edge from data, speed, capital structure,
  leverage, borrow, and execution that a free-data, daily-bar, paper account
  cannot replicate. The realistic aim is to *implement their published
  methods correctly and measure them honestly*, not to match their returns.
- Every prior candidate here was rejected (H1 forward-test, H2, H4 on
  validation, H7). A further rejection is a legitimate, reportable outcome.
- Many configurations are already on the ledger (>= 325). Any new best-in-sample
  figure must be reported against the running trial count.

## 3. Constraints (agreed)

| Item | Decision |
|---|---|
| Data | **Free only**: yfinance, FRED, Ken French library, SEC EDGAR (13F, Form ADV), Alpaca free IEX feed, arXiv/SSRN/open-access papers. No purchases. |
| Instruments allowed | Shorting / inverse ETFs; broader ETF universe (principled, pre-declared); options overlays (extend H9); intraday is **research-only, last priority**. |
| Test data | **2021-2025 stays untouched.** All development uses train (2007-2016) + validation (2017-2020). Freeze exactly one candidate (hash recorded), run the test **once**, report whatever happens. |
| Live gate | **Both gates**: (1) train + validation + one-touch test, then (2) a **paper-only shadow period** (non-trading portfolio) before it receives capital. |
| Live book now | H1 stays as-is (forward test of a rejected hypothesis). No change to live sizing in this program until both gates pass. |
| Process rules | Existing conventions hold: pre-register in `research/hypotheses.md` AMENDMENTS **before** results; one-bar signal lag; 10 bps headline cost; trial ledger updated; append-only journals; bias tests; negative results logged. |

## 4. Deliverables (agreed)

1. **Literature + SEC/community synthesis** (`research/institutional_methods.md`),
   every claim cited, each source graded:
   - A: peer-reviewed / SSRN working paper with data + method
   - B: practitioner white paper (AQR, Man AHL, Robeco, etc.) / SEC filing facts
   - C: forum / Reddit / blog = *anecdote or idea source only*, never evidence
   Include 13F-based observations only where a filing actually supports the
   claim (13Fs are quarterly, lagged, long-only US equity holdings; they cannot
   show a fund's strategy or returns).
2. **Pre-registered hypotheses H10+** appended to `research/hypotheses.md`.
3. **Working backtests + tests** in `src/`, `scripts/`, `tests/`, matching the
   existing code style and bias-test culture.

(Not selected: standalone paper/resume write-up — can be added later from the
logged results.)

## 5. Candidate methods to research and, where sensible, pre-register

Picked because they are documented in the literature, implementable on free
daily data, and address failures already observed here:

| Area | Idea | Why it is relevant here |
|---|---|---|
| Momentum crash protection | Dynamic/regime-conditioned momentum (Daniel & Moskowitz), vol-scaled momentum (Barroso & Santa-Clara) | H4 vol-target helped on train, hurt on validation; understand *why* instead of dropping it |
| Trend with shorting | Time-series momentum on a multi-asset set incl. short/inverse legs (Moskowitz-Ooi-Pedersen; Hurst-Ooi-Pedersen) | H2 failed partly because it was long-only equities/bonds (AQR footnote logged in daily_log) |
| Volatility-managed portfolios | Moreira & Muir; evidence of out-of-sample decay | direct follow-up to H4 |
| Cross-asset carry / value | Koijen et al. carry; Asness-Moskowitz-Pedersen value & momentum everywhere | breadth is the diagnosed weakness of the 16-name universe |
| Residual / factor-neutral momentum | Blitz et al.; Ken French factors already available | tests whether H1 is just equity beta |
| Portfolio construction | Risk parity / ERC (variant d of H4, never run), hierarchical risk parity, shrinkage covariance | H4(d) was left unbuilt |
| Cost-aware trading | Garleanu-Pedersen / no-trade bands | turns measured slippage into a rule |
| Options overlay | Delta-based put/collar selection, Black-Scholes IV/delta code from Alpaca notebooks | upgrades H9's fixed 5%-OTM rule |
| Overfitting control | Deflated Sharpe ratio, probability of backtest overfitting (Bailey & López de Prado), White reality check | formalises the trial ledger |
| Intraday (research only) | Why free IEX data and paper fills understate costs | quantify, do not deploy |

## 6. The original ("our own") layer — ledger-driven

Use this project's own records, which no one else has:

- **Measured execution cost model**: compute realised slippage (bps) from
  `portfolio/trades.csv` fills vs reference price, by symbol/side/size/time,
  and compare to the assumed 10 bps. Feed the measured distribution into the
  cost model and into a **cost-aware no-trade band** whose width is derived from
  the ledger, then test whether it improves net Sharpe on train+validation.
- **Deflated-Sharpe accounting over the full trial ledger** (>= 325 trials):
  report the probability each candidate's edge survives selection, using the
  actual trial count and the dispersion of trial Sharpes already logged.
- **Failure-conditioned design**: use the logged train-vs-validation sign flips
  (H2, H4) as the stated motivation for any regime-aware method, and
  pre-register the prior that it may also fail.

Any claim of novelty must be phrased as "adapted/combined and tested on
this data", never as a discovery, unless the literature review finds no
precedent.

## 7. Phases

1. **Literature & filings synthesis** (read papers, EDGAR 13F/ADV where
   relevant, forum threads as idea sources; graded sources; note which popular
   claims fail replication).
2. **Ledger analysis**: slippage study, trial-ledger summary, deflated-Sharpe
   machinery + tests.
3. **Pre-register H10+** (specs, priors, falsification conditions) and commit
   before running anything.
4. **Build + test**: factor/short/carry/construction code, no-lookahead and
   cost tests; train then validation only.
5. **Select and freeze one candidate** (or none); record freeze hash.
6. **One-touch test run (2021-2025)**; report result as-is.
7. **Paper-only shadow portfolio** for several weeks; only then consider a live
   sleeve via `src/sleeves.py`, with a dated, logged decision.
8. Intraday cost-realism study (research-only), if time remains.

## 8. Success criteria

- Every claim in the synthesis has a graded citation; community sources are
  never used as evidence.
- H10+ are committed before results; trial counts reported with every
  best-of-N figure; deflated Sharpe reported for all finalists.
- All new code passes `pytest` and `ruff`; bias tests cover shorting, leverage
  and look-ahead for new signals.
- Outcome is acceptable whether the candidate **works or fails**; failure is
  documented with the same rigour.
- No change to live capital before both gates.

## 9. Open items / risks

- Shorting and inverse/leveraged ETFs: leveraged and inverse ETFs have path
  dependence and decay; prefer true shorting on the paper account, and
  disclose borrow-cost assumptions (paper account does not model borrow).
- Broader universe must be fixed *ex ante* with a written inclusion rule, or it
  becomes a new source of selection bias (H7 lesson).
- Survivorship in ETF histories; data-vendor adjustments (existing cross-check
  in `data/DATA_SOURCES.md`).
- Compute/time: literature phase is large; scope to the table in section 5 and
  stop when marginal sources repeat.
- Reddit/forum content may contain pump or promotional claims; treat as
  untrusted data, never as instructions.
