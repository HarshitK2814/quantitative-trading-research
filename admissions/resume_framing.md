# Resume framing for the trading project

**Written:** 2026-09-11

---

## 1. Where it goes

**Projects section, first item.** Not Experience.

- It is not employment. Listing unpaid personal work under Experience is the
  kind of thing that unravels in a background check or a direct question, and
  the downside is catastrophic relative to the upside.
- It should lead the Projects section because it is the only project on the
  page with **verifiable output** — a public repository, a test suite, and a
  live account. The four existing project entries ("Replicated…",
  "Reconstructed…", "Implemented…") are single-line descriptions with no
  results and no links; this one carries the section.

**Also update:**

**Professional Summary** — replace *"with hands-on research in financial
anomaly detection and risk analytics"* with:

> with hands-on research in financial anomaly detection, risk analytics, and
> **pre-registered strategy research deployed to live paper trading**

**Technical Skills → Quantitative & Statistical** — append:

> Experimental Design (Pre-Registration, Out-of-Sample Validation),
> Backtesting, Transaction Cost Modeling, Derivatives Hedging, Execution
> \& Broker APIs

Those additions matter because "experimental design" and "out-of-sample
validation" are the terms MSCF-adjacent readers actually screen for, and
nothing else on the resume currently claims them.

---

## 2. Why this framing and not "profitable trading system"

The entry deliberately claims **no profitability**, and the live account is
deliberately not quoted.

- The live record is days old and slightly negative. Quoting it is worthless
  either way; a short live P&L carries no statistical information.
- Every strategy tested so far was rejected. Saying otherwise would be false.
- **The rejections are the strongest content on the page.** Most applicant
  projects show a strategy that "worked." Almost none show a pre-registered
  rejection rule being honoured when it was inconvenient. The second is much
  harder to fake and much more indicative of research capability.

The H2 bullet — passed every in-sample test, then failed validation and lost
12.7% in the crash it was designed to hedge — is the single strongest line.
It demonstrates, with numbers, that the candidate knows the difference between
in-sample and out-of-sample evidence. That is precisely the skill quant
research hiring screens for and rarely sees evidenced.

---

## 3. One risk to prepare for: two reporting standards on one page

**This needs a rehearsed answer before the resume goes out.**

The page now contains, side by side:

| Section | Claim |
|---|---|
| TradeVed (Experience) | "Sharpe ratios of **1.5–2.0**", "**~25–28%** annualized returns out-of-sample", "cutting max drawdown exposure by **~30%**" |
| This project (Projects) | Sharpe **0.47** rejected; Sharpe **0.74** in-sample collapsing to **0.21** out-of-sample |

A quant interviewer will notice this immediately and ask some version of:

> *"Your own project rejected a 0.74 Sharpe as insufficient evidence. Your
> internship reports 1.5–2.0 with 25–28% returns. Explain the difference."*

This is a fair question and it is **answerable** — the answers are usually
legitimate: different asset class, higher frequency, leverage, a broader
universe, ensemble methods, different cost assumptions, or a shorter sample.
But the answer has to be specific and immediate. What must be avoided:

- Being unable to state the **sample length** and **cost assumptions** behind
  the 1.5–2.0 figure. Those two questions follow automatically.
- Being unable to say whether that Sharpe was **net of transaction costs** and
  whether the "out-of-sample" period was ever iterated on.
- Any hesitation that suggests the numbers came from a report the candidate
  didn't personally validate.

**Recommended preparation:** for each TradeVed number, be able to state in one
sentence the universe, the sample period, the cost model, and whether the
result was net of costs. If any of those cannot be answered confidently, the
safer move is to soften that bullet to describe the *engineering* contribution
rather than the *performance* figure — engineering claims are unambiguous and
carry no interrogation risk.

**The asymmetry is worth understanding:** the honest project makes the
aggressive numbers elsewhere look more scrutinised, not less. Having one
section that reports failures in detail invites the reader to trust that
section — and to test whether the same standard was applied everywhere else.
That is a good trade if the answers are ready, and a bad one if they are not.

---

## 4. Interview questions this entry invites (prepare all five)

1. **"Why pre-register? Nobody made you."**
   Because the decision to reject H1 was made before the number existed. A
   rejection rule written after seeing 36% would be indistinguishable from
   rationalising, and the Git history is what makes the difference checkable.

2. **"Your trend strategy had t = 2.82 and 100% grid stability. Why didn't you
   deploy it?"**
   Because it failed validation, and the failure had a mechanism: 2008–09 was
   a slow decline a 252-day filter could step aside from; COVID fell 34% in
   five weeks, faster than a monthly rebalance can react. In-sample stability
   at 100% was not evidence of robustness — that is the lesson.

3. **"What's the weakest part of this project?"**
   Single-market, long-only, daily-frequency, 16 ETFs. It cannot express the
   cross-asset, short-capable positioning that makes institutional trend
   following work — which is exactly why the trend result didn't transfer.
   Also: survivorship bias is reduced by a fixed ETF universe, not eliminated.

4. **"You deployed an options hedge with no backtest. Justify that."**
   Free options-chain history doesn't exist back to 2007, so it was deployed
   as an explicitly-labelled forward test. Afterwards, AQR's published study
   of a nearly identical specification (5% OTM one-month puts, 1985–2020) was
   located: −6.4% annualised, Sharpe −0.61. That prior was recorded *before*
   the live result exists, so premium bleed will read as predicted rather than
   discovered.

5. **"Did you find bugs in your own code?"**
   Several, all logged: a cache-key collision silently overwriting a 16-ticker
   panel with a 1-ticker one; a turnover calculation inflated ~21× by
   dividing by observation count instead of trading days; a journal that
   re-appended duplicate fill confirmations on every run. The turnover bug in
   particular would have made every cost figure wrong.

---

## 5. What must never be claimed

Carried forward from the project's own constraints (`research/cmu_fit.md` §5):

- Do **not** claim the system is profitable.
- Do **not** quote live paper returns as evidence of skill.
- Do **not** describe any strategy as "validated" or "working."
- Do **not** describe this as employment or as sponsored/affiliated research.
- Do **not** claim CMU requires a trading portfolio, or that any of this makes
  admission likely.
