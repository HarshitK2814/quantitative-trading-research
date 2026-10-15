# Measured slippage from the live ledger

**Generated:** 2026-10-15 from `portfolio/trades.csv` (read-only).
**Sign:** positive = worse for us. **Definition:** implementation shortfall vs the
reference price at order generation (includes drift until fill), not pure spread.

|                 |   n |   mean_bps |   median_bps |   p90_abs_bps |   std_bps |   share_over_10bps |
|:----------------|----:|-----------:|-------------:|--------------:|----------:|-------------------:|
| all             | 114 |      -1.7  |         0.51 |         52.1  |     33.27 |               0.09 |
| buy             |  59 |       0.45 |         0.79 |         49.63 |     32.26 |               0.1  |
| sell            |  55 |      -4.01 |         0    |         60.18 |     34.47 |               0.07 |
| notional <5k    |  83 |      -6.04 |         0.38 |         52.43 |     32.63 |               0.05 |
| notional 5k-20k |  30 |      10.2  |         0.61 |         51.67 |     33.18 |               0.2  |
| notional >20k   |   1 |       1.22 |         1.22 |          1.22 |    nan    |               0    |

- Fills analysed: **114**
- Mean -1.70 bps, median 0.51 bps,
  5%-winsorised mean -0.46 bps. Backtest headline assumption:
  **10 bps** per unit turnover.
- Caveats: paper fills are simulated and optimistic; ETF liquidity here is
  extreme; sample is a few weeks; heavy tails come mostly from reference-price
  staleness, not market impact. This is evidence about the cost assumption,
  not proof of it.
