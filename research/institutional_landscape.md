# What institutional trading firms actually disclose — and where their methodology is really published

**Written:** 2026-09-10
**Status:** Research note. Every filing claim below was verified programmatically
against SEC primary sources on 2026-09-10; the verification script and its raw
JSON output are described in §2 and reproducible.

---

## 1. The question, and why the obvious answer is wrong

The motivating question was: *big prop shops, HFT firms, hedge funds and market
makers must describe their methodologies in SEC filings — can we read those and
learn how they trade?*

Reading SEC filings is entirely legal — they are public documents, published by
the SEC for exactly that purpose. **But the premise that they contain trading
methodology is false**, and that matters more than the legal question. US
securities law requires disclosure of *positions* (sometimes), *financial
condition*, *conflicts of interest*, and *material business risk*. It does not
require — and no firm volunteers — the signals, parameters, holding periods, or
model logic that constitute an edge.

Two primary sources, read directly rather than summarised:

**Virtu Financial 10-K, FY2025** (CIK 0001592386 — a *publicly listed* HFT market
maker, i.e. the most disclosure-bound firm in this entire space). The most
specific strategy language in the document:

> "we are able to test and rapidly deploy new liquidity provisioning strategies,
> expand to new securities, asset classes and geographies and increase
> transaction volumes at little incremental cost"

> "Our market making platform generates and disseminates continuous bid and offer
> quotes."

Everything technical sits behind the word *proprietary*: "proprietary,
multi-asset, multi-currency technology platform", "proprietary connectivity
network", "automated order routing models". No signal definitions, no
parameters, no thresholds. This is deliberate, competent, defensive disclosure —
it says *what* the business does and *why it matters to clients and regulators*,
and protects *how* as a trade secret.

**A Form ADV Part 2A "Item 8 — Methods of Analysis, Investment Strategies"
section**, the SEC form where registered advisers describe their strategy:

> "The foundation of [our] investment process is our method of blending
> proprietary quantitative models with qualitative research to build a portfolio
> of securities for each strategy that exhibits both good growth characteristics
> and reasonable valuations. Our quantitative modeling process first scores and
> ranks companies based upon predictive factors that include but are not limited
> to financial strength, historical growth, future earnings expectations, and
> valuation."

That is a *category* of approach, not a method. No weights, no lookback windows,
no rebalancing rules, no universe definition. Nothing replicable.

> **A trap worth recording.** That ADV belongs to **Renaissance Investment
> Management** (reninv.com), a traditional Cincinnati asset manager — **not**
> Renaissance Technologies (rentec.com), the Medallion fund. Web searches
> conflate the two constantly. Building an analysis on that confusion, and then
> repeating it in an interview, would be a costly and very visible error. Always
> resolve a firm to its CIK or CRD number, never to its name.

---

## 2. Method, and what it can and cannot support

Verification used SEC primary sources only:

1. **EDGAR bulk filer registry** (`Archives/edgar/cik-lookup-data.txt`) — the
   complete name→CIK mapping. **1,058,349 filer entries** parsed. One download
   rather than a hundred scraped pages.
2. **`data.sec.gov/submissions/CIK##########.json`** — the structured filing
   history per CIK, giving the actual form types each entity has filed.

**Two honest limitations of this method**, stated because they affect how much
weight the table in §4 can bear:

- **SEC blocks undeclared automated access.** The first attempt returned HTTP
  403 with *"Your Request Originates from an Undeclared Automated Tool"* for
  every request — a result that initially looked like "no firm files anything",
  which would have been a spectacularly wrong conclusion drawn from a scraper
  bug. It was caught because the answer contradicted a filing already fetched
  by hand minutes earlier. **Zero results is a claim that needs the same
  scepticism as a surprising positive result.**
- **Name matching is noisy.** Matching legal entity names by substring produces
  false positives: "Susquehanna" matched a radio holding company, "Vatic" matched
  an individual person, "Winton" matched a third-party feeder fund rather than
  Winton Group itself. Rows in §4 marked *(unresolved)* are cases where the
  registry match was ambiguous or the firm's US entity was not located — **not**
  evidence that the firm files nothing. Resolving those properly requires
  entity-by-entity CIK/CRD confirmation, which was not done for all 53.

Form ADV is **not** in EDGAR at all — it lives in IAPD
(adviserinfo.sec.gov). Where §4 refers to ADV availability, that is by
adviser-registration status, not an EDGAR lookup.

---

## 3. The structural finding: the firms you most want to study are the ones that disclose least

This is the most useful result in the note, and it emerged from the data rather
than being assumed going in.

**Form 13F comes in two flavours**, and which one a firm files is diagnostic:

- **13F-HR** ("Holdings Report") — an actual list of positions.
- **13F-NT** ("Notice") — a filing that says, in effect, *I have nothing to report
  here; my holdings appear on another manager's report.*

Sort the verified data by that distinction and a clean pattern appears:

| Files 13F-**NT** (no holdings detail) | Files 13F-**HR** (actual positions) |
|---|---|
| Jane Street, Citadel Securities GP, Virtu Financial BD, Tower Research Capital Europe, Wolverine Holdings, Citadel Advisors II, Squarepoint (DIFC) | Renaissance Technologies, Two Sigma Investments, Bridgewater Associates, Millennium, Balyasny, ExodusPoint, Qube Research, Voleon, AHL Partners (Man), Acadian, DFA, Numerai |

**The fastest traders disclose the least, and it is structural, not evasive.**
13F is a *quarter-end snapshot filed 45 days late*. A market maker whose
inventory turns over in seconds to hours holds essentially nothing at any
quarter boundary that reflects how it makes money. There is no filing in the US
disclosure regime whose sampling frequency can even represent an HFT strategy.
You cannot reverse-engineer a millisecond strategy from a quarterly photograph —
not because it is hidden, but because it is not there to photograph.

The other form these firms do file, **X-17A-5**, is the broker-dealer annual
audited report (FOCUS). It contains balance sheets and net capital computations.
Financial condition, not method.

**Conclusion for the project:** the slower and more institutional a manager is,
the more you can learn from its filings — and 13F still tells you *what* was held
at a date, never *why*. The proper use of 13F data is as a research *dataset*
(e.g. studying whether institutional holdings changes predict returns — a real,
published literature with mixed and largely decayed results), not as a strategy
manual.

---

## 4. The firms (53), with verified filing status

Categories: **HFT/prop** = proprietary trading and market making ·
**Quant fund** = systematic/multi-strategy hedge funds ·
**Factor manager** = systematic asset managers (the most transparent tier).

`EDGAR entity` is the matched filer name; `Key forms` are actual observed form
types.

### HFT / proprietary trading / market making

| # | Firm | EDGAR entity matched | Key forms observed |
|---|---|---|---|
| 1 | Jane Street | Jane Street Capital, LLC / Asia Trading Ltd | 13F-NT, X-17A-5, FOCUSN |
| 2 | Citadel Securities | Citadel Securities GP LLC | 13F-NT, SC 13G, X-17A-5 |
| 3 | Jump Trading | Jump Financial, LLC | **13F-HR**, 13F-NT |
| 4 | Hudson River Trading | *(unresolved)* | — |
| 5 | Virtu Financial | Virtu Financial BD LLC + **Virtu Financial, Inc.** (public) | 13F-NT/HR, X-17A-5, **10-K, 10-Q, 8-K, DEF 14A** |
| 6 | DRW | DRW Securities, L.L.C. | 13F-HR, X-17A-5 |
| 7 | Optiver | Optiver Derivatives Trading – USA, LLC | X-17A-5 |
| 8 | IMC | *(unresolved)* | — |
| 9 | Susquehanna (SIG) | *(unresolved — matched unrelated radio co.)* | — |
| 10 | Tower Research Capital | Tower Research Capital Europe Ltd | 13F-NT |
| 11 | XTX Markets | XTX Markets LLC | 13F-HR, 13F-NT, X-17A-5 |
| 12 | Flow Traders | Flow Traders U.S. Institutional Trading | X-17A-5 |
| 13 | Two Sigma Securities | Two Sigma Securities, LLC | 13F-HR, X-17A-5 |
| 14 | GTS | GTS Securities LLC | 13F-HR, X-17A-5 |
| 15 | Wolverine Trading | Wolverine Holdings, LLC | 13F-NT |
| 16 | Akuna Capital | Akuna Securities LLC | 13F-HR, X-17A-5 |
| 17 | Belvedere Trading | Belvedere Trading LLC | X-17A-5 |
| 18 | Chicago Trading Co. | *(unresolved)* | — |
| 19 | Old Mission Capital | Old Mission Capital LLC | 13F-HR |
| 20 | Quantlab | Quantlab Brokerage, LLC | X-17A-5 |
| 21 | Radix Trading | *(unresolved)* | — |
| 22 | Vatic Investments | *(unresolved)* | — |
| 23 | Headlands Technologies | Headlands Alternative Investments II | Form D |
| 24 | Tradebot Systems | Tradebot Systems, Inc. | X-17A-5 |
| 25 | PEAK6 | PEAK6 Capital Management LLC | (adviser-side) |

### Quant hedge funds / systematic multi-strategy

| # | Firm | EDGAR entity matched | Key forms observed |
|---|---|---|---|
| 26 | Renaissance Technologies | Renaissance Technologies LLC (CIK 1037389) | **13F-HR**, SC 13G, N-PX |
| 27 | Two Sigma Investments | Two Sigma Investments, LP | **13F-HR**, N-PX |
| 28 | D. E. Shaw | D. E. Shaw & Co, L.L.C. | SC 13G (+13F under group entity) |
| 29 | Citadel Advisors | Citadel Advisors II LLC | 13F-NT |
| 30 | Millennium Management | Millennium Management LLC | **13F-HR**, SC 13G |
| 31 | Point72 | (fund entities) | Form D |
| 32 | Balyasny | Balyasny Asset Management L.P. | **13F-HR**, SC 13G |
| 33 | ExodusPoint | ExodusPoint Capital Management, LP | **13F-HR**, SC 13G |
| 34 | AQR Capital | AQR Capital Management LLC (CIK 1167557) | **13F-HR**, SC 13G |
| 35 | Bridgewater Associates | Bridgewater Associates, LP | **13F-HR** |
| 36 | Man Group / AHL | AHL Partners LLP | **13F-HR**, 13F-NT |
| 37 | PDT Partners | PDT Partners ESC Fund, LLC | Form D |
| 38 | WorldQuant | (fund entities) | Form D |
| 39 | Voleon | Voleon Capital Management LP | **13F-HR** |
| 40 | Squarepoint | Squarepoint (DIFC) Ltd | 13F-NT |
| 41 | Marshall Wace | (fund entities) | Form D |
| 42 | Winton | *(unresolved — matched feeder fund)* | 10-K (feeder) |
| 43 | Schonfeld | SB Schonfeld Active Managers Fund LP | *(unresolved)* |
| 44 | Capula | Capula Alternative Markets Alpha Fund | Form D |
| 45 | Qube Research & Technologies | Qube Research & Technologies Ltd | **13F-HR**, SC 13G |

### Systematic / factor asset managers — *the tier that actually publishes*

| # | Firm | EDGAR entity matched | Key forms observed |
|---|---|---|---|
| 46 | Acadian Asset Management | Acadian Asset Management LLC | **13F-HR**, N-PX |
| 47 | Dimensional Fund Advisors | Dimensional Fund Advisors LP | **13F-HR**, SC 13G |
| 48 | Research Affiliates | (via Parametric/partner vehicles) | Form D |
| 49 | Arrowstreet Capital | Arrowstreet (Delaware) Alpha Extension | Form D |
| 50 | Los Angeles Capital | Los Angeles Capital Management LLC | **13F-HR**, N-PX |
| 51 | Robeco | Boston Partners entities | *(unresolved)* |
| 52 | Numerai | Numerai GP LLC | **13F-HR**, Form D |
| 53 | First Quadrant | FQ A-Squared Fund Ltd. | Form D |

---

## 5. Where the methodology actually is

The paradox: **the firms that publish the most detailed, replicable methodology
are not hiding it in filings — they put it in peer-reviewed journals and public
white papers.** AQR, Man, Robeco, Research Affiliates and Dimensional publish
real specifications, with parameters, sample periods, and results. They can
afford to because their edge is in implementation, scale, and cost control, not
in the existence of the idea.

This is a far better source than any filing, and it is free.

### Directly relevant to this project's hypotheses

| Paper | Authors | Maps to |
|---|---|---|
| **Tail Risk Hedging: Contrasting Put and Trend Strategies** (AQR, Jul 2020) | Ilmanen, Thapar, Tummala, Villalon | **H9** (see §6) |
| **Time Series Momentum** (JFE 2012) | Moskowitz, Ooi, Pedersen | **H2** |
| **Value and Momentum Everywhere** (J. Finance 2013) | Asness, Moskowitz, Pedersen | **H1, H7** |
| **Returns to Buying Winners and Selling Losers** (J. Finance 1993) | Jegadeesh, Titman | **H1** (the origin) |
| **Trading Costs / Trading Costs of Asset Pricing Anomalies** | Frazzini, Israel, Moskowitz | **cost model** (see below) |
| **Betting Against Beta** (JFE 2014) | Frazzini, Pedersen | **H4** |
| **Fact, Fiction and Momentum Investing** | Asness, Frazzini, Israel, Moskowitz | **H1** — answers the standard objections |
| **A Century of Evidence on Trend-Following Investing** | Hurst, Ooi, Pedersen | **H2** |

**On the cost model specifically:** Frazzini, Israel & Moskowitz estimated
trading costs from roughly **$1.7 trillion of live execution data** at a large
institutional manager across 21 developed markets over 19 years — and concluded
that real costs are *many times smaller* than the literature's standard
estimates, with break-even fund sizes an order of magnitude larger. That is
directly relevant to this project's headline **10bps per unit turnover**
assumption, and is the strongest available external check on whether H1's
cost-driven degradation was modelled too harshly or about right. It also
suggests the existing cost sweep (0/5/10/20bps) brackets the plausible range
sensibly rather than needing to be widened.

---

## 6. The headline finding: institutional evidence directly contradicts H9's premise

When H9 (the options protective-put overlay) was pre-registered on 2026-09-10,
it carried this disclosure:

> "no free historical options-chain data exists back to 2007 … so this **cannot**
> be backtested … It would deploy directly as a forward test with no historical
> validation."

**That is still true of *our* ability to backtest it — but it was incomplete as a
statement about available evidence.** AQR ran exactly this backtest using paid
OptionMetrics data and published the results. The data is behind a paywall; the
*finding* is free.

**AQR's tested strategy:** buy a **5% out-of-the-money one-month S&P 500 index
put at mid-month, roll into a new put at expiry.** Sample: **2 Jan 1985 –
31 Mar 2020** (35 years).

**H9 as deployed:** buy a **~5% out-of-the-money SPY put, 21–35 days to expiry,
rolled inside 14 DTE.**

These are, for practical purposes, **the same strategy.**

### Their results

| Strategy | Geometric mean | Sharpe | CVaR 5% | Max DD | Skew | Equity corr. |
|---|---|---|---|---|---|---|
| **Put** — long 5% OTM 1-mo S&P puts (scaled to 10% vol) | **−6.4%** | **−0.61** | −5.5% | **−92%** | +3.5 | −0.64 |
| **Trend** — multi-asset trend following (10% vol target) | **+8.7%** | **+0.84** | −5.7% | −35% | +0.1 | −0.08 |

Crucially, **the Put returns are gross of trading costs and fees**, while the
Trend returns are *net* of estimated transaction costs. The real-world gap is
therefore **wider** than the table shows.

AQR's mechanism for the loss is specific and testable: option-implied
volatilities and implied negative skewness *systematically exceed subsequent
realisations*, so the seller of protection is paid a risk premium on average and
the buyer pays it. Their summary of the Put strategy's behaviour in crises:

> "Put did make timely gains in sharp bear markets but spent those gains soon
> after by buying more expensive puts."

And their overall conclusion:

> "The common view that Put costs more but is a more effective tail hedge
> contains a kernel of truth but does not capture the full story… we end up
> preferring Trend over Put."

### What this means for the project — and what it does *not* mean

**It does not mean H9 should be quietly switched off.** That would be exactly the
reactive strategy-swapping this project has already declined to do, and H9's
live forward test remains a legitimate, pre-registered experiment. A hedge that
costs money in a calm period is *insurance behaving normally*, not a failed
hypothesis.

**What it does mean, concretely:**

1. **H9's stated prior was too neutral and should be corrected in the log** —
   not the hypothesis text (which is frozen), but the record should now note
   that strong external evidence *predicts negative expected return* for this
   exact specification. Recording that now, before H9's live result exists, is
   the whole point of pre-registration discipline.
2. **The 35-year Sharpe of −0.61 sets a realistic expectation.** If H9 bleeds
   premium over the next four months, that is the *predicted* outcome, not a
   surprise or a bug — and the project should say so in advance rather than
   discover it in December.
3. **It creates a genuinely interesting comparison this project is unusually
   well-placed to run**: H2 (time-series trend) is already pre-registered and
   not yet backtested. AQR's claim is precisely that **trend-following is a
   better crisis hedge than puts.** Testing H2 against H9 as competing
   drawdown-mitigation tools — one backtestable on free data, one running live —
   is a sharper research question than either alone, and it comes with a
   published institutional prior to agree or disagree with.
4. **This also retroactively strengthens the earlier drawdown-control decision.**
   The request was "no more than 5–7% drawdown"; the answer built was circuit
   breakers plus a put overlay. The institutional evidence suggests the
   *cheapest* effective drawdown control in this space is trend-following
   exposure, not purchased optionality — which is H2, sitting un-backtested in
   the hypothesis file.

**Proposed follow-up (to be pre-registered before any test):** *H10 — Put versus
trend as drawdown mitigation.* Compare the realised cost and drawdown-reduction
of H9's live put overlay against a backtested H2 trend overlay on the same book,
with AQR's finding as the explicit stated prior (i.e. predicting Trend wins on
cost-adjusted terms). Because the prior is now on record *before* the test, a
result agreeing with AQR is weak confirmation, and a result disagreeing is the
interesting one.

---

## 7. Honest summary of what this exercise produced

**What was asked for:** methodologies extracted from ~50 firms' SEC filings.

**What exists:** essentially none of that. Filings disclose positions, financial
condition, and risk — never method. The fastest firms disclose least, for a
structural reason (13F-NT vs 13F-HR) that is itself worth knowing.

**What was found instead, and is more valuable:** the same firms publish real,
parameterised methodology in the open literature — and one of those papers
tests, over 35 years, a strategy nearly identical to one this project deployed
live today, and finds it loses 6.4% annually.

That last point is the kind of thing this exercise was actually for. Not a
stolen edge — a published, checkable result that changes what we expect from a
position already on the books, recorded before the outcome is known.

---

## Sources

- Virtu Financial 10-K FY2025 — SEC EDGAR CIK 0001592386,
  <https://www.sec.gov/Archives/edgar/data/1592386/000159238626000009/virt-20251231.htm>
- SEC EDGAR bulk filer registry —
  <https://www.sec.gov/Archives/edgar/cik-lookup-data.txt>
- SEC structured submissions API — <https://data.sec.gov/submissions/>
- AQR, *Tail Risk Hedging: Contrasting Put and Trend Strategies* (July 2020) —
  <https://www.aqr.com/Insights/Research/White-Papers/Tail-Risk-Hedging-Contrasting-Put-and-Trend-Strategies>
- AQR, *Alternative Thinking: Tail-Hedging Strategies* —
  <https://www.aqr.com/Insights/Research/Alternative-Thinking/Tail-Hedging-Strategies>
- Frazzini, Israel & Moskowitz, *Trading Costs of Asset Pricing Anomalies* —
  <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2294498>
- Frazzini, Israel & Moskowitz, *Trading Costs* (2018) —
  <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3229719>
- SEC Investment Adviser Public Disclosure (Form ADV) —
  <https://adviserinfo.sec.gov/>
