# Round 2 results (train + validation only; test untouched)

## H11 no-trade band (15 configs)
Common evaluation start: 2007-08-31

train: baseline vs primary (b=0.04, phi=1.0)
```
          sharpe    ret    vol    mdd   turn
baseline   0.488  0.077  0.175 -0.398  6.786
primary    0.483  0.076  0.175 -0.404  6.498
```
Sharpe>=base False; turnover<=75% False (96%); grid share >= base 50% (need 60%): False

validation: baseline vs primary (b=0.04, phi=1.0)
```
          sharpe    ret   vol    mdd   turn
baseline   0.859  0.156  0.17 -0.246  6.798
primary    0.852  0.155  0.17 -0.246  6.608
```
Sharpe>=base False; turnover<=75% False (97%); grid share >= base 0% (need 60%): False

## H13 regime scaling (12 configs)
Common evaluation start: 2007-08-31

train: baseline vs primary (theta=.20, s=.5, W=252)
```
          sharpe    ret    vol    mdd   turn
baseline   0.488  0.077  0.175 -0.398  6.786
primary    0.560  0.080  0.150 -0.249  6.604
```
State ON 15.5% of days (need >=3%); primary meets both True; grid meeting both 100% (need 60%)

validation: baseline vs primary (theta=.20, s=.5, W=252)
```
          sharpe    ret    vol    mdd   turn
baseline   0.859  0.156  0.170 -0.246  6.798
primary    0.750  0.131  0.164 -0.246  6.968
```
State ON 6.5% of days (need >=3%); primary meets both False; grid meeting both 0% (need 60%)

## H15 absolute-momentum gate (9 configs)
Common evaluation start: 2008-01-31

train: baseline vs primary (G=252, k=5)
```
          sharpe    ret    vol    mdd   turn
baseline   0.471  0.072  0.175 -0.398  6.802
primary    0.600  0.079  0.138 -0.189  6.101
```
Primary meets alternative True; grid configs meeting it 6/9 (need >=5)

validation: baseline vs primary (G=252, k=5)
```
          sharpe    ret   vol    mdd   turn
baseline   0.859  0.156  0.17 -0.246  6.798
primary    0.801  0.137  0.16 -0.246  6.068
```
Primary meets alternative False; grid configs meeting it 0/9 (need >=5)

## H14 ERC / HRP (27 evaluations)
Common evaluation start: 2008-02-29 (25% cap: k=3 gross is 75%)

train
erc: beats EW in 8/9 selections (need >=6); mean turnover ratio 0.97 (need <=1.25)
hrp: beats EW in 7/9 selections (need >=6); mean turnover ratio 1.04 (need <=1.25)

validation
erc: beats EW in 2/9 selections (need >=6); mean turnover ratio 1.01 (need <=1.25)
hrp: beats EW in 5/9 selections (need >=6); mean turnover ratio 1.09 (need <=1.25)
Primary (k=5, L=126):
```
     sharpe    ret    vol    mdd   turn
EW    0.859  0.156  0.170 -0.246  6.798
ERC   0.857  0.136  0.145 -0.203  7.453
HRP   0.874  0.125  0.129 -0.174  8.008
```

## H12 diagnostic: cash drag vs timing (25 configs x 2 periods)
train: configs with positive shortfall 22/25; median cash-drag share 1.51; median timing value +0.064
validation: configs with positive shortfall 25/25; median cash-drag share 0.48; median timing value -0.129

## Cost sweep, primaries (validation)
```
        base    H11    H13    H15  H14-ERC
5bps   0.879  0.872  0.771  0.820    0.883
10bps  0.859  0.852  0.750  0.801    0.857
20bps  0.819  0.813  0.707  0.763    0.806
```

## Verdicts (pre-registered rules, applied literally)
- H11: NOT SUPPORTED
- H13: NOT SUPPORTED
- H15: NOT SUPPORTED
- H14: NOT SUPPORTED
- H12: REJECTED (timing, not exposure level)

Trials this round: 113 (cumulative ledger >= 438).
NO CANDIDATE FROZEN; test window untouched.
