# CMU MSCF — What the program actually says, and how this project relates

**Compiled:** 2026-09-05
**Target:** MS in Computational Finance (MSCF), Carnegie Mellon — Fall 2027 intake
**All sources accessed:** 2026-09-05

---

## How to read this document

Claims are separated into three categories and never blended. This separation
exists because the difference between "CMU said this" and "I inferred this" is
exactly the kind of distinction a research programme is supposed to enforce.

| Tag | Meaning |
|---|---|
| **[A]** | Explicitly stated by CMU on an official `cmu.edu` page, quoted verbatim. |
| **[B]** | Publicly observable fact about the program or its students, from an official page, that CMU does not frame as an admissions requirement. |
| **[C]** | My own inference or recommendation. Not endorsed by CMU. Could be wrong. |

**Nothing in this repository claims that this project causes, guarantees, or
materially improves admission to MSCF.** That claim would be unfalsifiable and
false. See §5.

---

## 1. [A] What CMU explicitly says it looks for

Source: [MSCF Program FAQ](https://www.cmu.edu/mscf/admissions/faq) — accessed 2026-09-05.

Under **"What are you looking for in a candidate for the MSCF program?"**:

> "proof of success academically in a depth of mathematics coursework"

> "demonstrated understanding of the field of quantitative finance and clear
> goals therein"

> "candidates who can express their ideas clearly both verbally and in writing"

> "have the motivation to be successful in the rigors of the MSCF program"

> "able to work well in diverse teams"

> "The admissions process is very holistic in nature"

> "any one area of weakness may be balanced by another area of strength"

### 1.1 [A] The paper-trading recommendation

Under **"How can I enhance my profile?"**, CMU lists (verbatim):

> "Open a paper trading account and start developing and practicing your own
> trading strategies"

Alongside, in the same list:

> "Study. In particular, strong performance in your quantitative and
> computational coursework"
> "Fill in any gaps in your academic background by taking any pre-requisite courses"
> "Be sure to take any courses for a grade at an accredited college or university"
> "Find an internship in the financial services industry"
> "Follow the markets and read the news"
> "Start building your professional network"
> "Practice your written and verbal communication skills"

**Read this list carefully.** Paper trading is *one of eight* suggestions, and
it is not the first. The list is headed by coursework performance. This matters
for how much weight this project should be given in an application narrative —
see §5.

Note also the exact verb phrasing: *"developing and practicing your own trading
strategies."* CMU is recommending the **activity of strategy development**, with
the paper account as the venue. It is not recommending a trading track record.

### 1.2 [A] Hard requirements

| Requirement | Verbatim |
|---|---|
| Testing | "A GRE or GMAT score is required for all candidates" · "You must have taken the test within five years of submitting your application" |
| Mathematics | "most have taken engineering-level math courses beyond calculus including Linear Algebra" · "A calculus-based probability course is also required" |
| Programming | "one full-semester course in an object-oriented programming language" · "Additional programming coursework is highly recommended" |
| Work experience | "Relevant professional experience is preferred but is not required" |

**[C] Implication for me:** the calculus-based probability course and the
OOP course are *prerequisites*, and this project does not substitute for
either. If either is missing from my transcript, closing that gap outranks
every hour spent on this repository. That is a scheduling conclusion, and it is
recorded here so it is not quietly forgotten.

---

## 2. [B] Who actually gets in

Source: [MSCF Class Profile](https://www.cmu.edu/mscf/admissions/class-profile.html)
— accessed 2026-09-05. Figures describe the **Fall 2025 entering class**.

| Metric | Value |
|---|---|
| Applicants | 1,051 |
| Class size | 108 |
| Average GPA | 3.86 |
| Average GRE Quantitative | 169 |
| Average GRE Verbal | 161 |
| International | 78% |
| No full-time work experience | 77% |
| Location split | Pittsburgh 56 · New York City 52 |

Undergraduate major breakdown:

| Major | Share |
|---|---|
| Mathematics / Statistics | 52% |
| Business / Finance | 20% |
| Information Systems / Computer Science | 18% |
| Engineering | 5% |
| Economics | 4% |
| Other | 1% |

### [C] What I take from this — including the uncomfortable part

- **Roughly a 10% admit rate** (108 of 1,051), assuming all admits enrolled.
  Actual admit rate is higher than yield-adjusted 10.3%, since not every admit
  enrols; the true figure is not published. **I should not quote "10% admit
  rate" as fact** — it is a lower bound on selectivity computed from two
  published numbers, and should be described that way if described at all.
- **77% enter with no full-time work experience.** Applying as an undergraduate
  is the norm here, not a disadvantage. This is genuinely encouraging.
- **GRE Quant 169 average.** This is the single most consequential number on
  the page. A 169Q average in a pool of 1,051 means the quantitative bar is set
  by test performance and transcript, and **no portfolio project compensates
  for a weak quant score.** Time allocation should reflect that.
- **52% come from Mathematics/Statistics backgrounds.** The modal admit is
  mathematically strong. The differentiating question for me is therefore not
  "can I code" but "can I demonstrate quantitative *judgment*" — which is what
  a project with pre-registered hypotheses and honest failure analysis can
  show, and a project with a nice equity curve cannot.

---

## 3. [B] What the curriculum implies about valued skills

Source: [MSCF Curriculum](https://www.cmu.edu/mscf/academics/curriculum) —
accessed 2026-09-05. Selected course titles, verbatim:

**Year one:** 46901 Fundamentals of Programming and CS · 46902 Data Structures
and Algorithms · 46921/46923 Financial Data Science I & II · 46926/46927
Machine Learning I & II · 46929 Financial Time Series Analysis · 46932
Simulation Methods for Option Pricing · 46944/46945 Stochastic Calculus for
Finance I & II · 46956 Fixed Income · 46964 Algorithm Design and Applications
for Computational Finance · 46972 MSCF Investments · 46973 MSCF Options ·
46974 Financial Products and Markets · 46906/46907 MSCF Business Communication
I & II · 46971 Presentations for Financial Computation

**Year two:** 46954 Risk Management · 46976 Financial Optimization · 46979
Asset Management · 46982 Market Microstructure and Algorithmic Trading ·
46937 MSCF Deep Learning · 46983 MSCF Machine Learning Capstone Project ·
46915 Advanced Derivative Models · 46924 Natural Language Processing ·
46975 Macroeconomics for Computational Finance

Pre-program: MSCF Math Prep · MSCF Probability Prep · MSCF Programming Prep ·
MSCF Markets Prep. An internship (46999) is required.

### [C] Direct mappings from this project to named courses

These are **topic overlaps**, not equivalences. A 12-week self-directed project
is not a semester of graduate coursework, and this document will not pretend
otherwise.

| Project component | Related course |
|---|---|
| Return/volatility modelling, autocorrelation, stationarity checks | 46929 Financial Time Series Analysis |
| Backtesting pipeline, feature engineering, train/validation/test discipline | 46921/46923 Financial Data Science I & II |
| Optional gradient-boosted ranker vs. baseline | 46926/46927 Machine Learning I & II |
| Volatility targeting, drawdown limits, exposure monitoring | 46954 Risk Management |
| Risk parity, weight constraints, optimisation under limits | 46976 Financial Optimization |
| Transaction costs, slippage, order execution via broker API | 46982 Market Microstructure and Algorithmic Trading |
| Portfolio construction, benchmark-relative evaluation | 46979 Asset Management · 46972 MSCF Investments |
| Written report and one-page summary | 46906/46907 Business Communication |

**Two notable non-mappings**, stated so the gap is explicit rather than hidden:
this project contains **no stochastic calculus** (46944/46945) and **no
derivatives pricing or simulation** (46932, 46973, 46915). Those are core to
MSCF and are demonstrated through coursework and the GRE, not here. Anyone
reading this project as evidence of derivatives knowledge would be reading it
wrong.

---

## 4. [C] What this project is designed to demonstrate

Mapped against CMU's own stated criteria from §1:

| CMU criterion [A] | How this project speaks to it | Honest strength |
|---|---|---|
| "depth of mathematics coursework" | Applied statistics: hypothesis testing, bootstrap CIs, multiple-testing awareness, time-series regression | **Weak.** Transcript evidence dominates. This is applied, not deep, mathematics. |
| "demonstrated understanding of the field of quantitative finance" | Costs, slippage, turnover, capacity, factor exposure, benchmark selection, why Sharpe misleads | **Strong.** This is the criterion the project genuinely serves. |
| "clear goals therein" | A stated research question, a pre-declared selection rubric, documented decisions | **Strong.** |
| "express their ideas clearly both verbally and in writing" | Technical report, README, one-page summary, interview question bank | **Strong**, and directly testable by a reader. |
| "motivation to be successful in the rigors" | 12 weeks of dated commits and a research log showing sustained independent work | **Moderate.** Evidence of persistence, which is real but indirect. |
| "able to work well in diverse teams" | — | **Not demonstrated.** This is solo work. Teamwork evidence must come from elsewhere in the application. |
| "Open a paper trading account and start developing and practicing your own trading strategies" | Alpaca paper account with logged trades, plus the research surrounding it | **Directly responsive.** |

**The honest summary:** this project addresses roughly three of CMU's six stated
criteria well, one partially, and one not at all. It is a supporting exhibit,
not a centrepiece.

---

## 5. [C] What must never be claimed

The following statements are **prohibited** in this repository, in the resume,
in the LinkedIn post, and in any application essay:

- ❌ "CMU requires a trading portfolio." — False. It is one of eight profile
  suggestions in an FAQ.
- ❌ "This project will get me into MSCF." — Unfalsifiable and false.
- ❌ "This satisfies CMU's requirements." — The requirements are coursework,
  a GRE/GMAT score, and prerequisites. This satisfies none of them.
- ❌ "I am a profitable trader." — Simulated results over weeks establish
  nothing about skill.
- ❌ Any admissions-outcome causal claim whatsoever.

The **only** defensible framing, to be used verbatim where a framing is needed:

> "This project develops and practices systematic trading strategies in a paper
> account — an activity CMU's own admissions FAQ recommends prospective
> applicants undertake — and documents the surrounding quantitative research:
> hypothesis formation, backtesting under realistic transaction costs,
> out-of-sample validation, risk management, and live paper execution."

Every clause there is either verifiable from the repository or quoted from the
FAQ.

---

## 6. [C] The strategic point, stated plainly

CMU recommends a paper trading account as a way to *develop and practice
strategies*. It does not ask for returns, and returns over a 10-week window
would not be informative if it did.

So the account is the **venue**, not the achievement. The achievement is the
intellectual work around it — and that work is what distinguishes this from the
large number of applications that will also mention a trading account.

A reader who opens this repository should encounter, in order: a research
question, a pre-registered hypothesis, a method, a result, and an honest
account of what failed. If they instead encounter an equity curve going up and
to the right, the project has failed at its actual purpose regardless of the
number on the chart.

---

## Sources

All accessed 2026-09-05.

- [MSCF Program FAQ](https://www.cmu.edu/mscf/admissions/faq)
- [MSCF Class Profile](https://www.cmu.edu/mscf/admissions/class-profile.html)
- [MSCF Curriculum](https://www.cmu.edu/mscf/academics/curriculum)
- [MSCF Admissions](https://www.cmu.edu/mscf/admissions/index.html)
- [MSCF Apply](https://www.cmu.edu/mscf/admissions/apply.html)

**Re-verification note:** program pages change between admissions cycles. Every
quotation above must be re-checked against the live pages before any of it is
used in an application submitted in the Fall 2027 cycle.
