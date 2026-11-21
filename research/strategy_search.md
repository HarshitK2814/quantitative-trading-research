# Strategy search (exploratory track)

Run 2026-11-21. **566 trials.** Not pre-registered; every trial is in `research/search_ledger.csv`.

SPY Sharpe: train 0.55, valid 0.85, holdout 0.64.

## By family

| family        |   trials |   best_valid |   passed |
|:--------------|---------:|-------------:|---------:|
| low_vol       |       16 |    0.911472  |        0 |
| pairs         |       36 |    0.249833  |        0 |
| regime        |       20 |    1.14186   |        0 |
| reversal      |       32 |    0.0394129 |        0 |
| rsi2          |       96 |    1.35008   |        0 |
| sma_trend     |      110 |    1.12837   |        0 |
| tsmom         |      100 |    1.26805   |        0 |
| turn_of_month |       20 |    0.751635  |        0 |
| xs_mom        |      136 |    1.14425   |        0 |

## Top 20 by validation Sharpe

| name                                                                |   train_sharpe |   valid_sharpe |   valid_max_dd |      dsr | robust   | survivor   |
|:--------------------------------------------------------------------|---------------:|---------------:|---------------:|---------:|:---------|:-----------|
| rsi2:entry=20,exit_=70,sma=200,universe=s2                          |       0.534596 |        1.35008 |     -0.0424997 | 0.369109 | False    | False      |
| rsi2:entry=10,exit_=50,sma=100,universe=s2                          |       0.554041 |        1.32739 |     -0.0182684 | 0.343769 | False    | False      |
| rsi2:entry=15,exit_=70,sma=200,universe=s2                          |       0.579439 |        1.29666 |     -0.0403738 | 0.327075 | False    | False      |
| rsi2:entry=15,exit_=70,sma=100,universe=s2                          |       0.588136 |        1.29519 |     -0.032331  | 0.323486 | False    | False      |
| rsi2:entry=20,exit_=70,sma=100,universe=s2                          |       0.63171  |        1.28945 |     -0.0367207 | 0.322318 | False    | False      |
| tsmom:long_short=False,lookback=189,universe=s1,vol_target=False    |       0.517274 |        1.26805 |     -0.100257  | 0.313545 | False    | False      |
| rsi2:entry=5,exit_=70,sma=200,universe=s2                           |       0.51738  |        1.25185 |     -0.02095   | 0.278251 | False    | False      |
| rsi2:entry=5,exit_=50,sma=200,universe=s2                           |       0.637815 |        1.23754 |     -0.0156865 | 0.254116 | False    | False      |
| tsmom:long_short=False,lookback=189,universe=s1,vol_target=True     |       0.598702 |        1.22134 |     -0.0930919 | 0.281728 | False    | False      |
| tsmom:long_short=False,lookback=21,universe=crypto,vol_target=False |       0.982834 |        1.2152  |     -0.422262  | 0.271556 | False    | False      |
| rsi2:entry=10,exit_=70,sma=100,universe=s2                          |       0.443811 |        1.19982 |     -0.0263251 | 0.258283 | False    | False      |
| rsi2:entry=10,exit_=70,sma=200,universe=s2                          |       0.442871 |        1.18196 |     -0.0274935 | 0.250259 | False    | False      |
| tsmom:long_short=False,lookback=21,universe=crypto,vol_target=True  |       1.16338  |        1.17669 |     -0.117154  | 0.242187 | False    | False      |
| rsi2:entry=10,exit_=50,sma=200,universe=s2                          |       0.602757 |        1.17243 |     -0.0284403 | 0.236933 | False    | False      |
| xs_mom:long_short=False,lookback=63,skip=0,top=2,universe=sectors   |       0.429673 |        1.14425 |     -0.176387  | 0.232032 | False    | False      |
| tsmom:long_short=False,lookback=252,universe=crypto,vol_target=True |       0.895102 |        1.14424 |     -0.130404  | 0.225462 | False    | False      |
| regime:risk_off=cash,sma=150                                        |       0.58478  |        1.14186 |     -0.15434   | 0.231329 | False    | False      |
| sma_trend:fast=10,slow=200,universe=s1                              |       0.698773 |        1.12837 |     -0.109582  | 0.22319  | False    | False      |
| sma_trend:fast=50,slow=200,universe=s1                              |       0.703522 |        1.12638 |     -0.0986016 | 0.222305 | False    | False      |
| regime:risk_off=cash,sma=200                                        |       0.680414 |        1.1259  |     -0.177697  | 0.221693 | False    | False      |

## Survivors (0)


Retired live sleeves: ['S1', 'S2', 'H1'].

Limits: survivorship reduced (point-in-time membership, -30% delisting) but not removed; delisted names missing from yfinance are absent. DSR uses all trials.

## What was deployed instead (controller decision, 2026-11-21)

**No grid trial survived** the deflated-Sharpe bar (best DSR 0.37 across 566 trials). Read literally, none of the 566 can be told apart from luck on 4 years of validation data.

So nothing was picked from the grid. The deployed ensemble uses only rules fixed in advance:
- **S1, S2:** pre-registered on 2026-11-10. Each counts as one trial (PSR 0.99 on validation).
- **TSMOM 12m:** literature default (Moskowitz-Ooi-Pedersen 2012), long-only, vol-scaled, ETF universe.
- **LowVol:** 252-day volatility, top 50 S&P 500 names by point-in-time liquidity.

Mix: inverse-vol (63d, lagged), then scaled to a **10% vol target**, gross exposure ≤ 100%, position cap 10%.

| | Train Sharpe | Valid Sharpe | Holdout Sharpe | Holdout return | Holdout max DD |
|---|---|---|---|---|---|
| Ensemble (10% vol, deployed: std floor 0.003) | 0.79 | 0.95 | 0.78 | +13.2% | -9.5% |
| Ensemble (10% vol, before floor fix) | 0.84 | 1.10 | 0.72 | +12.5% | -9.8% |
| SPY | 0.55 | 0.85 | 0.64 | +20.0% | -18.8% |
| H1 (retired) | 0.61 | 0.67 | 0.29 | +7.4% | -26.7% |

**Disclosure:** vol targets 0.08, 0.12 and 0.15 were also viewed on the holdout (Sharpe 0.82, 0.64, 0.62). 0.10 was kept as the round default, not the best. The holdout has therefore been touched more than once, and these numbers are optimistic. The live paper record from 2026-11-23 is the real test.


## Phase 2 overlays tested (2026-11-21, rules fixed before running)
Rule: an overlay is adopted only if it improves BOTH train and validation Sharpe. The holdout is not used to decide, because it has already been viewed.

| | Train | Valid | Holdout | Verdict |
|---|---|---|---|---|
| Live ensemble | 0.79 | 0.95 | 0.78 | baseline |
| + VIX/VIX3M > 1 → half size | 0.82 | 0.88 | 0.96 | **Rejected** (valid worse) |
| + Cboe PutWrite (^PUT) sleeve, inverse-vol | 0.64 | 1.17 | 0.67 | **Rejected** (train worse) |

The VIX filter's holdout gain is noted, but it is not acted on, since acting on it would be selecting on the holdout. Intraday (30-min) was dropped: the session schedule ends by 12:00 ET.
