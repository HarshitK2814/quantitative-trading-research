# Deflated Sharpe over the trial ledger (train 2007-2016, 10 bps)

Method: Bailey & Lopez de Prado (2014). Sharpes annualised for display; the
test statistic uses per-period values. `Luck-only max` is the annualised Sharpe
the best of N skill-less trials is expected to reach given the observed
dispersion of trial Sharpes. DSR is the probability the candidate's true Sharpe
exceeds it (0.95+ would be strong; ~0.5 is indistinguishable from selection).

| Candidate | Sharpe | Trials N | Luck-only max | DSR |
|---|---|---|---|---|
| H1 primary 126/k5/skip21 vs H1 grid | 0.472 | 50 | 0.224 | 0.783 |
| best H4 train config (IV63 lb=252 k=8) vs H1+H4 ledger | 0.605 | 175 | 0.263 | 0.858 |

Caveats: ledger counts only the H1 and H4 grids re-computed here; H2/H3/H6/H7
trials are logged separately in `research/overfitting.md`, so true N is larger
and DSR values here are upper bounds. Train window only.
