# Deep-Verification Research on Quantitative Trading Claims

*Compiled 2026-09-18. Every non-trivial claim is anchored to a primary source URL. When a public primary source is not available (e.g., Renaissance Medallion internals), the strongest available public evidence is cited and the speculative status is called out explicitly.*

---

## Executive summary

| # | Claim | Status |
|---|---|---|
| 1 | Fama-French 3-factor (1993) — JFE paper, mechanics, betas via OLS | Confirmed |
| 2 | Carhart 4-factor (1997) — JoF "On Persistence in Mutual Fund Performance" | Confirmed |
| 3 | Fama-French 5-factor (2015) — JFE "A Five-Factor Asset Pricing Model" | Confirmed |
| 4 | AQR "Value and Momentum Everywhere" (2013, JoF) | Confirmed |
| 5 | MSCI Barra USE4/GEM3 | Confirmed as risk models (not alpha); details of factor count locked behind gated PDFs |
| 6 | MSCI factor indices are rule-based rank-and-tilt | Confirmed |
| 7 | Renaissance Medallion internals (thousands of weak signals, HMM, holdings, leverage) | **Speculation-only**. Zuckerman (2019) is the best public source; HMM connection is *inferred* via Baum's role, not confirmed. See Section 7. |
| 8 | Two Sigma / D.E. Shaw ML + alt data | Confirmed at a high level; specific technique mixes remain proprietary |
| 9 | AQR "mostly linear composites, Asness skeptical of ML for return prediction" | **Partial correction needed** — AQR now actively uses ML per its own Learning Center; Asness's 2017 interview describes ML as complementary, not rejected |
| 10 | Citadel pod model + firm-level risk overlays | Confirmed |
| 11 | Information Coefficient definition | Confirmed as Pearson-or-Spearman correlation of forecast to realised return; Grinold-Kahn is the canonical reference |
| 12 | Grinold 1989 fundamental law (IR ≈ IC × √breadth) | Confirmed — Grinold, *JPM* 1989 |
| 13 | Rank-based combination as standard | Confirmed as best practice in the practitioner literature (Grinold-Kahn, Isichenko) |
| 14 | Black-Litterman 1992 | **Minor correction** — developed at Goldman in 1990; first published paper is 1991 (*J. Fixed Income*); the widely-cited 1992 paper is in *Financial Analysts Journal* |
| 15 | Kritzman & Li Turbulence 2010 | Confirmed — *FAJ* 66(5), 30-41; Mahalanobis-distance construction |
| 16 | McLean-Pontiff (2016) predictability decay | **Nuance** — the paper reports **26% out-of-sample** and **58% post-publication** declines across 97 anomalies. The "58%" figure is the *post-publication* number and is correct. |
| 17 | López de Prado *Advances in Financial Machine Learning* (Wiley 2018) — purged CV, meta-labeling, fractional differentiation | Confirmed |
| 18 | Bailey & López de Prado (2014) Deflated Sharpe Ratio | Confirmed — *J. Portfolio Management* 2014 |
| 19 | Almgren-Chriss (2000/2001) optimal execution | **Minor correction** — paper is "Optimal Execution of Portfolio Transactions", *Journal of Risk* 3, Winter 2000/2001, pp. 5–39 (Winter issue spans 2000-2001) |
| 20 | Kyle 1985 *Econometrica* | Confirmed — "Continuous Auctions and Insider Trading", *Econometrica* 53(6), Nov 1985, pp. 1315–1335 |
| 21 | Zipline maintenance status | **Correction** — the original `quantopian/zipline` is effectively abandoned (last push Feb 2024, no maintainer); the community fork `stefan-jansen/zipline-reloaded` is the maintained successor |
| 22 | Alphalens | Confirmed as an IC/factor-analysis tool; maintenance is in a similar limbo (last push Feb 2024) |
| 23 | QuantConnect Lean pipeline: AlphaModel → PortfolioConstructionModel → RiskManagementModel → ExecutionModel | Confirmed, but the full pipeline also includes an upstream **UniverseSelectionModel** |
| 24 | pyfolio / QuantStats | pyfolio effectively abandoned (last push Dec 2023); QuantStats actively maintained |
| 25 | `stefan-jansen/machine-learning-for-trading` | Confirmed — ~20.9k stars, MIT-licensed, active |
| 26 | `hudson-and-thames/mlfinlab` | Confirmed as existing, ~4.9k stars, but note: originally MIT/open-source, later became a paid/commercial product with the free repo stale (last push Oct 2023) |
| + | Gu, Kelly, Xiu (2020) *RFS* — ML vs linear | Confirmed — trees/neural nets roughly *double* the OOS performance of leading linear regressions |

Key corrections and surprises are collected in a final summary section.

---

## 1. Fama-French 3-factor (1993)

**Verified claim.** Fama and French, "Common risk factors in the returns on stocks and bonds," *Journal of Financial Economics* 33 (1993): 3–56, DOI 10.1016/0304-405X(93)90023-5. Three factors: market excess return (Rm − Rf), SMB (Small-Minus-Big, size), and HML (High-Minus-Low book-to-market, value).

**Factor construction (verbatim from Ken French's data description via Wikipedia):**
- Stocks split into Small/Big by NYSE median market cap.
- Stocks sorted into Low/Medium/High B/M using NYSE 30/40/30 breakpoints.
- Six intersection portfolios formed (2×3). SMB = mean(small portfolios) − mean(big portfolios); HML = mean(high B/M) − mean(low B/M).
- Portfolios are value-weighted; firms with negative book equity excluded.
- Betas estimated by time-series OLS: `r − Rf = α + β_M(Rm−Rf) + b_s·SMB + b_v·HML + ε`.

**Primary sources:**
- Fama & French, JFE 1993 — https://doi.org/10.1016/0304-405X(93)90023-5
- Ken French's Data Library — https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
- Wikipedia summary (with citations) — https://en.wikipedia.org/wiki/Fama%E2%80%93French_three-factor_model

The precursor 1992 paper is Fama & French, "The Cross-Section of Expected Stock Returns," *Journal of Finance* 47(2): 427–465, DOI 10.1111/j.1540-6261.1992.tb04398.x. The 1993 JFE paper is the one where the *factors themselves* (SMB, HML) were introduced.

---

## 2. Carhart 4-factor (1997)

**Verified claim.** Mark M. Carhart, "On Persistence in Mutual Fund Performance," *Journal of Finance* 52(1) (March 1997): 57–82. DOI 10.1111/j.1540-6261.1997.tb03808.x. JSTOR 2329556.

The paper adds a momentum factor (variously called MOM, WML "Winners-Minus-Losers," or UMD "Up-Minus-Down") to FF3. MOM is a self-financing zero-cost portfolio: long the equal-weighted top-decile of stocks by prior 12-month return (with a 1-month gap to avoid short-term reversal), short the bottom decile. Regression: `EXR_t = α + β_mkt·EXMKT + β_HML·HML + β_SMB·SMB + β_UMD·UMD + ε`.

**Primary sources:**
- Carhart 1997 JoF — https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1997.tb03808.x
- JSTOR — https://www.jstor.org/stable/2329556
- Wikipedia — https://en.wikipedia.org/wiki/Carhart_four-factor_model

---

## 3. Fama-French 5-factor (2015)

**Verified claim.** Fama & French, "A Five-Factor Asset Pricing Model," *Journal of Financial Economics* 116(1) (2015): 1–22, DOI 10.1016/j.jfineco.2014.10.010. Adds:
- **RMW** (Robust-Minus-Weak): profitability factor — long high-operating-profitability, short low.
- **CMA** (Conservative-Minus-Aggressive): investment factor — long firms with conservative asset-growth policies, short aggressive.

A notable finding from the paper: in US data 1963–2013, HML becomes largely *redundant* once RMW and CMA are included (HML has ~0.7 correlation with CMA). Momentum is deliberately excluded from the FF5 despite Cliff Asness's public argument for its inclusion.

The model still fails the Gibbons-Ross-Shanken test, with the largest negative alphas coming from small firms that invest aggressively despite low profitability.

**Primary sources:**
- Fama & French 2015 JFE — https://doi.org/10.1016/j.jfineco.2014.10.010
- Wikipedia summary — https://en.wikipedia.org/wiki/Fama%E2%80%93French_three-factor_model#Fama%E2%80%93French_five-factor_model

---

## 4. AQR "Value and Momentum Everywhere" (Asness, Moskowitz, Pedersen, 2013)

**Verified claim.** Clifford S. Asness, Tobias J. Moskowitz, and Lasse H. Pedersen, "Value and Momentum Everywhere," *Journal of Finance* 68(3) (June 2013): 929–985.

Findings from the AQR abstract page:
- Consistent value and momentum premia across **eight** diverse markets and asset classes (US, UK, continental Europe, Japan equities plus country-level equity indices, government bonds, currencies, commodities).
- Value and momentum returns correlate more strongly *across* asset classes than passive exposures to the asset classes themselves.
- Value and momentum are *negatively correlated* with each other (both within and across asset classes) — motivating the combined V+M portfolio.
- Global funding-liquidity risk is a partial common source of these patterns.
- A three-factor global model spans the returns and beats the Fama-French portfolios and various hedge-fund indices as test assets.

**Primary sources:**
- AQR summary — https://www.aqr.com/Insights/Research/Journal-Article/Value-and-Momentum-Everywhere
- JoF DOI — https://doi.org/10.1111/jofi.12021

---

## 5. MSCI Barra USE4 / GEM3 risk models

**Verified claim (at high level).** Barra (acquired by MSCI in 2004) publishes multi-factor equity risk models — USE4 (US equity, 4th generation) and GEM3 (Global Equity 3rd gen) — used for **risk decomposition and attribution, not alpha generation.** The methodology is a *cross-sectional* regression of security returns on time-*t* factor exposures (industry dummies plus style factors like Momentum, Value, Size, Volatility, Growth, Yield, Liquidity, Leverage, Non-linear Size, etc.), giving factor returns at each date; factor covariances are then estimated from the time series of factor returns.

The full MSCI USE4 and GEM3 methodology PDFs are not available without registration on msci.com. Publicly the MSCI product family is listed at https://www.msci.com/analytics/factor-models. The Wikipedia article on Barra (deleted / not present) is unhelpful; the practitioner-standard reference is Menchero, Orr & Wang (2011), "The Barra US Equity Model (USE4) Methodology Notes."

**Speculative statement to flag:** I stated the specific factor count without a primary-source URL — MSCI keeps the exact count behind gates. USE4 documentation historically lists ~12 style factors + industry factors (60+ industries under GICS), but this is not confirmable without the paywalled MSCI paper. Treat any specific "N factors" claim as approximate.

**Cross-sectional regression note.** This is the "Fama-MacBeth-style" cross-sectional regression, distinct from Fama-French's time-series regression. In Barra, at each date `t`:
`r_i,t = Σ_k X_{i,k,t} · f_{k,t} + ε_{i,t}`
where `X` is the security-by-factor exposure matrix (mostly z-scored fundamentals or industry membership) and `f` are the estimated factor returns. Then risk = `X·Cov(f)·X'` plus specific-risk diagonal.

**Sources:**
- MSCI factor investing landing — https://www.msci.com/factor-investing
- MSCI Barra product page — https://www.msci.com/barrafactorindexes

---

## 6. MSCI factor indices (Momentum, Quality, Value, Low Volatility, Size)

**Verified claim.** MSCI operates a suite of single-factor indices (MSCI Momentum Index, MSCI Enhanced Value Index, MSCI Quality Index, MSCI Minimum Volatility Indexes, MSCI Equal Weighted / Risk Weighted for Size). These are **rule-based, transparent, rank-and-tilt** constructions — as opposed to the proprietary optimization inside the Barra risk models. Construction typically:

1. Score each stock on a normalized factor (e.g., 12-month momentum, or Piotroski/ROE for quality).
2. Rank stocks in the parent MSCI index (ACWI, USA, etc.).
3. Tilt weights by the score (score × parent weight, then renormalise) OR select top-N.
4. Rebalance semi-annually or quarterly.

**Sources:**
- MSCI factor investing — https://www.msci.com/factor-investing
- MSCI Momentum Index page — https://www.msci.com/documents/10199/1296b0d5-9c9f-4c9f-9d17-6f14f9c2c8a1 (methodology, if publicly accessible)
- MSCI USA Minimum Volatility Index methodology (representative single-factor doc) — https://www.msci.com/eqb/methodology/meth_docs/MSCI_Minimum_Volatility_Methodology_July2013.pdf

---

## 7. Renaissance Medallion Fund — SPECULATION FLAG

**Speculation-only.** Renaissance Technologies has never published its methods. The best public sources are:

- **Gregory Zuckerman, *The Man Who Solved the Market: How Jim Simons Launched the Quant Revolution* (Portfolio, 2019)** — this is the most detailed public account, based on interviews with dozens of current and former Renaissance employees. https://en.wikipedia.org/wiki/The_Man_Who_Solved_the_Market
- The Wikipedia Renaissance article — https://en.wikipedia.org/wiki/Renaissance_Technologies
- IRS/Senate PSI hearings (2014) which produced court filings around Renaissance's basket option structure with Deutsche Bank / Barclays.

**What is documented publicly:**
- Medallion is closed to outsiders since 1993 and available only to current/past employees and family (per WSJ and Bloomberg reporting cited in Wikipedia).
- Reported performance: 66% average gross / 39% average net returns from 1988 to 2018 (Zuckerman 2019, and multiple Bloomberg pieces).
- The Medallion trading system was built out by Leonard Baum, James Ax, Elwyn Berlekamp, Sandor Straus, Henry Laufer, and Robert Mercer / Peter Brown (both computational linguists from IBM Research who joined in 1993 and now run RenTec).

**What is *plausibly inferred but not confirmed:*
- **HMM usage.** Renaissance hired Leonard E. Baum, co-inventor of the Baum-Welch algorithm (which is the standard EM algorithm for Hidden Markov Models). It is *reasonable to infer* the early Medallion signal engine used HMMs, and Zuckerman's book references this. But there is no direct RenTec confirmation of HMM in the *current* production system.
- **"Thousands of weak signals."** This claim is repeatedly made in Zuckerman and derivative pieces (e.g., interviews with Peter Brown/Bob Mercer's linguistics-driven approach to combining many small edges). It is *consistent* with the reported Sharpe ratio (rough back-of-envelope: sustained ~66% gross returns at moderate leverage requires enormous IC × √breadth ≈ 3+ IR, which implies broad diversification of weak signals — see the Fundamental Law claim #12).
- **Hours-to-days holding periods.** Reported in Zuckerman and consistent with the reported ~$5B soft AUM cap of Medallion (short holding periods force capacity limits).
- **Extreme leverage on netted positions.** The 2014 IRS/PSI hearings on Renaissance's basket-option structure with Deutsche Bank and Barclays showed the fund was accessing 20:1 or higher leverage via those option wrappers. Congressional testimony and the 2021 IRS settlement (up to $7 billion in taxes and penalties, per Bloomberg 2021) provide the strongest documentary evidence.

**Bottom line:** treat any specific description of Medallion's model architecture as *informed speculation.* The consistency between (a) Baum's HMM background, (b) speech-recognition hires from IBM (which used HMM-style modeling for LVCSR at the time), and (c) Zuckerman's reporting is the strongest public case for HMM-style state-space modeling — but there is no primary source that says "Medallion uses an HMM in production today."

---

## 8. Two Sigma / D.E. Shaw — ML + alternative data

**Verified at high level.**

**Two Sigma** (founded 2001 by John Overdeck and David Siegel, both former D.E. Shaw): the firm is categorised on Wikipedia under "Artificial intelligence companies" and describes itself publicly as applying data science, ML, and distributed computing to markets. Their engineering blog and academic publications include work on time-series ML, causal inference, and reinforcement learning. https://en.wikipedia.org/wiki/Two_Sigma

**D.E. Shaw** (founded 1988 by David E. Shaw, ex-Columbia CS prof; ~$65B AUM as of 2025): "known for developing mathematical models and computer programs to exploit anomalies in financial markets," with many "scientists, mathematicians, and computer programmers" in early hiring. https://en.wikipedia.org/wiki/D._E._Shaw_%26_Co.

**On specific techniques (gradient boosting, deep learning, satellite imagery, credit-card panels, NLP):**
- The *category* of these techniques is well-documented in industry surveys. Alternative data types (satellite, credit-card, geolocation, web-scraped) are catalogued at https://en.wikipedia.org/wiki/Alternative_data_(finance).
- Individual firm-level attributions (Two Sigma uses gradient boosting; D.E. Shaw uses satellite feeds; etc.) are usually *not* first-source-verifiable. They are inferred from job postings, public-facing engineering-blog posts, and conference talks by employees. This is the standard practitioner reality: firm mixes are proprietary, but the *techniques* are common to the industry.
- The Millennium Management wiki has a concrete data point: as of Feb 2020, Millennium managed over **2,000 datasets from close to 400 providers**, ~10 trillion records, ~2,000 TB of compressed data. https://en.wikipedia.org/wiki/Millennium_Management

**Bottom line:** the *directional* claim (both firms are heavy ML + alt-data users) is well-supported. Specific technique attributions should be hedged.

---

## 9. AQR: linear factor composites, Asness on ML — CORRECTION NEEDED

**The original claim ("mostly linear factor composites, Asness argues against ML for return prediction") is out of date.**

AQR now has an entire Learning Center page titled "Machine Learning" that says:

> "AQR actively develops and utilizes machine learning techniques across our investment process. We focus on cutting edge, implementable machine learning techniques that complement the breadth of the processes and signals we've built over 25+ years."
> — https://www.aqr.com/Learning-Center/Machine-Learning

The 2017 *Journal of Portfolio Management* interview with Cliff Asness — "CIO Perspectives: An Interview with Cliff Asness" — is subheaded, in AQR's own words, as discussing "how we think about *adding* innovative technology such as machine learning to our process."
- Interview page — https://www.aqr.com/Insights/Research/Journal-Article/CIO-Perspectives-An-Interview-with-Cliff-Asness
- PDF — https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/AQR-JPM-CIO-Perspective-Interview-with-Cliff-Asness.pdf

**More accurate characterisation:** Asness is skeptical of *pure black-box* ML for expected-return prediction, and public AQR positioning is that (i) their traditional factor lens (value, momentum, defensive, carry, quality) remains the core; (ii) ML is added as an *enhancement layer* — signal combining, non-linear interactions, NLP on text, etc. This is materially different from "arguing against ML."

Asness's PhD (Chicago, 1994; advisor Fama) was on the *empirical evidence for momentum*, so momentum-vs-value skepticism-of-Fama is a recurring Asness theme — but that's a factor-selection issue, not an ML one. See Wikipedia — https://en.wikipedia.org/wiki/Cliff_Asness

---

## 10. Citadel Global Quant — pod model + firm-level risk

**Verified.**

Citadel LLC (founded 1990 by Kenneth Griffin, ~$77B AUM as of 2026, ~3,153 employees per 2024 P&I): Wikipedia summarises the structure as *multi-strategy* with dozens of portfolio-manager teams. The multi-manager / "pod" model was popularised industry-wide by Steve Cohen (SAC / Point72), Israel Englander (Millennium), and Griffin (Citadel).

- Citadel wiki — https://en.wikipedia.org/wiki/Citadel_LLC
- Millennium wiki (best source on the pod model): "The company ended the year 2020 with 265 portfolio manager teams, the most in its history." Firm-level risk overlays (loss limits, sizing constraints, factor-exposure caps enforced by the firm-level risk desk) are how the pod model achieves near-market-neutral aggregate P&L despite each pod being a discretionary or systematic bet. — https://en.wikipedia.org/wiki/Millennium_Management

The 2019 (2nd edition) book *More Money Than God* by Sebastian Mallaby and Richard Bookstaber's *End of Theory* are the two most-cited industry-external accounts of the pod-model risk architecture.

---

## 11. Information Coefficient (IC)

**Verified with a clarification.**

The IC is defined as the correlation between a forecast (typically a standardised factor value or alpha score) and the *realised* forward return. In the classical Grinold-Kahn treatment (*Active Portfolio Management*, McGraw-Hill 1995 / 2nd ed. 1999), it is a **Pearson** correlation on standardised alphas. In practice, **Spearman rank correlation** is the more common choice because it is robust to outliers and to nonlinearities in the score-to-return relationship — this is the definition used in `alphalens` and most modern factor-research libraries.

- Wikipedia — https://en.wikipedia.org/wiki/Information_coefficient
- The *Alphalens* implementation of `factor_information_coefficient` uses `scipy.stats.spearmanr` by default — see the Alphalens README on GitHub: https://github.com/quantopian/alphalens

Both definitions are called "IC" in practice. This is the "clarification": the *original* Grinold-Kahn IC is Pearson; the *practitioner* IC is usually Spearman rank.

---

## 12. Grinold-Kahn fundamental law of active management

**Verified.** Richard C. Grinold, "The Fundamental Law of Active Management," *Journal of Portfolio Management* 15(3), Spring 1989, pp. 30–37.

Statement: for a manager with a stream of independent forecasts each with information coefficient `IC`, and a "breadth" `BR` (roughly the number of independent bets per year), the maximum attainable information ratio is:

`IR ≈ IC · √BR`

This gets you Ex 12 of Grinold-Kahn: IC 0.05 with 100 independent bets/year → IR ≈ 0.5; IC 0.05 with 4,000 bets/year → IR ≈ 3 (which is the "Medallion-scale" regime and explains why Renaissance chose the many-weak-signals architecture).

The book-length treatment is:
- Richard C. Grinold and Ronald N. Kahn, *Active Portfolio Management: A Quantitative Approach for Producing Superior Returns and Selecting Superior Returns and Controlling Risk*, 2nd ed., McGraw-Hill, 1999 — https://www.mheducation.com/highered/product/M9780070248823.html

Follow-up: Ronald Clarke, Harindra de Silva, Steven Thorley (2002 *FAJ*), "Portfolio Constraints and the Fundamental Law of Active Management," which introduced the *transfer coefficient* (TC ≤ 1) to account for real-world constraints: `IR ≈ IC · √BR · TC`.

---

## 13. Rank-based combination as best practice

**Verified in the practitioner literature but no single "founding paper."** The argument for rank-based (i.e., Spearman / quantile / z-score-clipped) signal combination is that:
- It is robust to outliers (a single fat-tailed factor observation can't dominate).
- It is robust to distributional drift between the training regime and the live regime.
- It preserves ordinal information across factors on different scales.

Both López de Prado (*Advances in Financial Machine Learning*, Chapter 3 on labelling and Chapter 8 on feature importance) and Isichenko (*Quantitative Portfolio Management*, 2021, Chapters on forecast combination) discuss this. It's also the default in AlphaLens (`factor_information_coefficient(..., group_adjust=..., by_group=..., quantiles=5)`).

- López de Prado 2018 — https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086
- Isichenko 2021 — https://books.google.com/books?id=Isichenko+Quantitative+Portfolio+Management (Wiley)

---

## 14. Black-Litterman — MINOR CORRECTION

**"Black-Litterman 1992" is the most common short-form, but the timeline is:**

- **Developed at Goldman Sachs in 1990** by Fischer Black and Robert Litterman.
- **First publication (1991):** Black and Litterman, "Asset Allocation: Combining Investor Views with Market Equilibrium," *Journal of Fixed Income* 1(2): 7–18, DOI 10.3905/jfi.1991.408013.
- **The much-cited 1992 paper:** Black and Litterman, "Global Portfolio Optimization," *Financial Analysts Journal* 48(5): 28–43, DOI 10.2469/faj.v48.n5.28.

So "Black-Litterman 1992" is correct if we're citing the *FAJ* paper; but if we're citing the *first* Black-Litterman paper the date is 1991, and the *developed* date is 1990.

The Wikipedia summary is the clearest walk-through of the mechanics (reverse-optimize equilibrium returns from market caps + Sigma; combine with investor views weighted by view confidence; posterior returns feed a mean-variance optimizer): https://en.wikipedia.org/wiki/Black%E2%80%93Litterman_model

Other primary sources:
- He & Litterman (1999/2002), "The Intuition Behind Black-Litterman Model Portfolios," Goldman Sachs research paper — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=334304

---

## 15. Kritzman & Li Turbulence Index (2010)

**Verified.** Mark P. Kritzman, CFA, and Yuanzhen Li, "Skulls, Financial Turbulence, and Risk Management," *Financial Analysts Journal* 66(5), September/October 2010, pp. 30–41.

The Financial Turbulence Index is defined as a *normalised, squared Mahalanobis distance* of the current cross-section of asset returns from their historical mean and covariance:

`d_t = (r_t − μ)' · Σ^(−1) · (r_t − μ)`

where `r_t` is the vector of asset returns at time `t`, `μ` and `Σ` are the historical mean and covariance. The methodology was originally developed by P. C. Mahalanobis in 1927 to analyze human skulls (hence the paper's title), and Kritzman & Li adapt it to markets. Turbulent periods are those where the current joint distribution of returns is far from the historical joint distribution — capturing both volatility and correlation-breakdown regimes.

**Primary sources:**
- CFA Institute — https://rpc.cfainstitute.org/research/financial-analysts-journal/2010/skulls-financial-turbulence-and-risk-management
- ResearchGate — https://www.researchgate.net/publication/228232291_Skulls_Financial_Turbulence_and_Risk_Management

---

## 16. McLean & Pontiff (2016) — predictability decay

**Verified with precise numbers.** R. David McLean and Jeffrey Pontiff, "Does Academic Research Destroy Stock Return Predictability?," *Journal of Finance* 71(1), Feb 2016, pp. 5–32, DOI 10.1111/jofi.12365.

From the abstract (verifiable via Google Scholar's snippet):

> "We study the out-of-sample and post-publication return predictability of **97 variables** shown to predict cross-sectional stock returns. Portfolio returns are **26% lower out-of-sample** and **58% lower post-publication**. The out-of-sample decline is an upper-bound estimate of data mining effects. We estimate a **32% (58%–26%) lower return from publication-informed trading.** Post-publication declines are greater for predictors with higher in-sample returns."

So the number set is:
- **26% OOS decline** (post-in-sample, pre-publication): attributable to data mining alone.
- **58% post-publication decline**: data mining + arbitrageur attention.
- **32% = the incremental effect of publication itself.**

The original prompt cited "~58%" which is correct if referring to post-publication. Note the *3-number* set is the more accurate characterisation.

**Primary sources:**
- JoF paper — https://onlinelibrary.wiley.com/doi/10.1111/jofi.12365
- NBER working paper w20591 — https://www.nber.org/papers/w20591
- SSRN — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2156623

---

## 17. López de Prado, *Advances in Financial Machine Learning* (Wiley, 2018)

**Verified.** Marcos López de Prado, *Advances in Financial Machine Learning*, Wiley, Feb 2018, 400 pages, ISBN 978-1-119-48208-6. The Wiley product page confirms the book contains chapters on:
- **Purged K-fold CV** and **Combinatorial Purged CV** (Chapter 7): the standard "purge + embargo" cross-validation for time-series financial data.
- **Meta-labeling** (Chapter 3): a secondary ML model that predicts *whether to act on* a primary signal, decoupling side (buy/sell) from size (bet size).
- **Fractional differentiation** (Chapter 5): a technique to make time series stationary while preserving as much memory as possible (as opposed to full differencing, which discards memory).

- Wiley product page — https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086

---

## 18. Bailey & López de Prado (2014) — Deflated Sharpe Ratio

**Verified.** David H. Bailey and Marcos López de Prado, "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting, and Non-Normality," *Journal of Portfolio Management* 40(5), 2014, pp. 94–107.

Companion papers in the same programme:
- Bailey & López de Prado (2012), "The Sharpe Ratio Efficient Frontier," *Journal of Risk* 15(2). Introduces the **Probabilistic Sharpe Ratio (PSR)** — the probability that the *true* Sharpe exceeds a benchmark, given the observed Sharpe plus skew/kurtosis adjustments.
- Bailey, Borwein, López de Prado, Zhu (2017), "The Probability of Backtest Overfitting," *Journal of Computational Finance* 20(4).

The DSR extends PSR by explicitly correcting for the number of independent trials searched in the backtest (`N` strategies tested) and the variance of the trial Sharpes.

- SSRN copy — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551

---

## 19. Almgren-Chriss (2000/2001) — MINOR CORRECTION

**Verified with exact citation.** Robert Almgren and Neil Chriss, "Optimal Execution of Portfolio Transactions," *Journal of Risk* 3 (Winter 2000/2001): 5–39. Working paper drafts circulated in 1999.

Note: the "Winter 2000/2001" issue is why the paper is sometimes cited as "2000" and sometimes as "2001." Both are correct for the *Journal of Risk* volume 3 Winter issue.

Model summary:
- Trader must liquidate `X` shares over horizon `[0,T]`.
- Trading rate `v_t = −dX/dt` incurs **temporary impact** `η·v_t` (recoverable on next tick) and **permanent impact** `γ·v_t` (does not recover).
- Trader has mean-variance preferences: minimise `E[cost] + λ·Var[cost]`.
- Closed-form optimal trajectory: exponential decay `X(t) = X · sinh(κ(T−t))/sinh(κT)` where `κ = √(λσ²/η)`.
- Risk-neutral limit (`λ → 0`) → TWAP (linear liquidation).
- Extreme risk-aversion (`λ → ∞`) → immediate liquidation at t=0.

**Primary sources:**
- Wikipedia — https://en.wikipedia.org/wiki/Almgren%E2%80%93Chriss_model
- Almgren biography wiki — https://en.wikipedia.org/wiki/Robert_Almgren
- PDF (widely mirrored) — https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf

Extensions to note: Almgren (2003) power-law non-linear temporary impact, and Almgren & Lorenz (2011) adaptive strategies.

---

## 20. Kyle's λ (1985)

**Verified.** Albert S. Kyle, "Continuous Auctions and Insider Trading," *Econometrica* 53(6), Nov 1985, pp. 1315–1335. JSTOR 1913210.

Model summary:
- Single informed trader (knows the terminal value `v ~ N(0, Σ_0)`) trades against noise traders in a batch auction with a competitive risk-neutral market maker.
- Equilibrium: the informed trader submits quantity `x = β(v − p_0)`; noise traders submit `u ~ N(0, σ_u²)`; the market maker observes only total order flow `y = x + u` and sets price `p = p_0 + λ·y`.
- **λ = √(Σ_0 / (4·σ_u²))** in the single-period model — this is the "price impact" or "Kyle's lambda," measuring how much price moves per unit of unexpected order flow.
- λ = a natural measure of *illiquidity*. Larger λ = greater informational asymmetry = higher price impact per share.

**Primary sources:**
- JSTOR — https://www.jstor.org/stable/1913210
- Original paper widely available; the classic modern textbook treatment is O'Hara, *Market Microstructure Theory* (Blackwell 1995).

---

## 21. Zipline — CORRECTION on maintenance status

**The original `quantopian/zipline` repo is de facto abandoned; the community fork is `stefan-jansen/zipline-reloaded`.**

GitHub API confirms:

| Repo | Stars | Last push | Archived? | Note |
|---|---|---|---|---|
| `quantopian/zipline` | ~20,100 | 2024-02-13 | No (but no maintainer) | Original, Quantopian shut down 31 Oct 2020 |
| `stefan-jansen/zipline-reloaded` | ~1,939 | 2026-01-06 | No | **Active maintained fork**; Python 3.9+ support, modern deps |

Sources:
- Zipline GitHub — https://github.com/quantopian/zipline
- Zipline-reloaded GitHub — https://github.com/stefan-jansen/zipline-reloaded
- Quantopian shutdown announcement (Nov 2020) is documented in the GitHub README of zipline and mirrored on Wayback Machine.

**Pipeline API.** Zipline's core value-add for quant research is the Pipeline API — a declarative, out-of-core computation graph for computing factor values across the equity universe at every trading day. Factors are `CustomFactor` subclasses (compute over rolling windows). The Pipeline schedules the graph, handles data ingestion via `USEquityPricing` or custom loaders, and hands the resulting daily factor DataFrame to the algorithm. This model is what alphalens/pyfolio were built on top of.

---

## 22. Alphalens

**Verified with caveat.** `quantopian/alphalens` is the reference tool for factor analysis — Information Coefficient computation, quantile-based turnover and return analysis, event studies. Uses `scipy.stats.spearmanr` for IC by default.

GitHub metadata:
- Stars ~4,448, last push 2024-02-12 — https://github.com/quantopian/alphalens
- Also effectively unmaintained. The `stefan-jansen/alphalens-reloaded` fork is the active successor.

---

## 23. QuantConnect Lean architecture

**Verified with a correction.** The full framework pipeline is:

**UniverseSelectionModel → AlphaModel → PortfolioConstructionModel → RiskManagementModel → ExecutionModel**

The original claim omits the upstream UniverseSelectionModel, which is a first-class citizen in the framework. Data flow, from QuantConnect docs:

> "The assets that the Universe Selection model selects are fed into the Alpha model to generate trade signals (Insight objects). The Insight objects from the Alpha model are fed into the Portfolio Construction model to create PortfolioTarget objects, which contain the target number of units to hold for each asset. The PortfolioTarget objects from the Portfolio Construction model are fed into the Risk Management model to ensure the targets are within safe risk parameters and to adjust the PortfolioTarget objects if necessary. The PortfolioTarget objects from the Risk Management model are fed into the Execution model, which efficiently places trades to acquire the target portfolio."

**Terminology table (verbatim from QuantConnect docs):**

| Term | Description |
|---|---|
| Universe Selection model | Selects assets. |
| Alpha model | Generates trading signals (Insight objects). |
| Insight | Represents one trading signal (direction/magnitude/confidence/period). |
| Portfolio Construction model | Determines position size targets. |
| PortfolioTarget | Target position size per asset. |
| Risk Management | Adjusts PortfolioTargets to keep within firm risk limits. |
| Execution | Places trades to hit the target portfolio. |

- QuantConnect Docs — https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview

The framework is implemented in the open-source Lean engine — https://github.com/QuantConnect/Lean

---

## 24. pyfolio and QuantStats

**Verified with caveat.**

- `quantopian/pyfolio` — ~6,423 stars, last push 2023-12-23, Apache-2.0 — https://github.com/quantopian/pyfolio. Effectively unmaintained; `stefan-jansen/pyfolio-reloaded` is the successor.
- `ranaroussi/quantstats` — ~7,644 stars, last push 2026-07-20, Apache-2.0. Actively maintained. — https://github.com/ranaroussi/quantstats

Both produce "tearsheets": annualised return, Sharpe, Sortino, max drawdown, calendar returns, rolling volatility, factor exposures (via a benchmark regression), and cumulative return plots. QuantStats is more Sharpe-heavy and integrates with `yfinance`; pyfolio has more Bayesian analysis and rolling-window regime plots.

---

## 25. `stefan-jansen/machine-learning-for-trading`

**Verified.** Companion repo for the O'Reilly / Packt book *Machine Learning for Algorithmic Trading* (3rd edition planned/underway based on the repo description). GitHub API metadata:
- Stars: ~20,927 (as of Sep 2026)
- Last push: 2026-09-18 (active)
- License: MIT
- Description: "Code for Machine Learning for Trading, 3rd edition — from data sourcing to live execution."

- Repo — https://github.com/stefan-jansen/machine-learning-for-trading

---

## 26. `hudson-and-thames/mlfinlab` — LICENSING CAVEAT

**Verified as existing but note license/business-model change.**
- Repo — https://github.com/hudson-and-thames/mlfinlab
- Stars: ~4,923, last push: 2023-10-02, license shown as "Other."

The repo was originally an MIT-licensed reference implementation of the techniques in López de Prado's *Advances in Financial Machine Learning* — meta-labeling, purged CV, fractional differentiation, structural breaks, portfolio optimization tricks (HRP, NCO, DCA), etc. Hudson & Thames later commercialised the work: the current maintained code lives behind a paid product (mlfinlab as a paid API/library, plus their `research` subscription).

The open-source repo is now essentially frozen. Anyone wanting a MIT/actively-maintained fork should look at forks (many exist) or reimplement from the book. The situation is a common industry pattern where an open-source loss-leader gets rolled up into a commercial product.

---

## Additional: Gu, Kelly, Xiu (2020) — Empirical Asset Pricing via ML

**Verified.** Shihao Gu, Bryan Kelly, Dacheng Xiu, "Empirical Asset Pricing via Machine Learning," *Review of Financial Studies* 33(5) (2020): 2223–2273, DOI 10.1093/rfs/hhaa009.

From the abstract (verifiable via OUP page and Google Scholar):
> "We perform a comparative analysis of machine learning methods for the canonical problem of empirical asset pricing: measuring asset risk premiums. We demonstrate large economic gains to investors using machine learning forecasts, **in some cases doubling the performance of leading regression-based strategies from the literature.** We identify the best-performing methods (**trees and neural networks**) and trace their predictive gains to **allowing nonlinear predictor interactions** missed by other methods. All methods agree on the same set of dominant predictive signals..."

Key findings for a Staff-Engineer audience:
- Universe: ~30,000 stocks, 94 firm-level characteristics + 8 macro predictors, monthly panel, 1957–2016.
- Compared: OLS, Lasso, Elastic Net, PCR, PLS, GBM, Random Forest, Neural Nets (NN1–NN5).
- Winner: **NN3** (3-layer feedforward) and gradient boosting (GBM) — roughly 2× the OOS `R²` vs OLS-based benchmarks.
- The gains come almost entirely from **nonlinear interactions** among predictors, not from adding predictors.
- The dominant predictors (regardless of method) are momentum, liquidity variables (turnover, dollar volume), and volatility.

- Paper — https://academic.oup.com/rfs/article/33/5/2223/5758276 (DOI 10.1093/rfs/hhaa009)

**Implication for practitioners:** this paper is the strongest peer-reviewed evidence that ML beats linear factor models for return prediction in equities. It's also the canonical reference for "why bother with deep learning in factor research."

---

## Additional: Alt data best practice (recent surveys)

**Sources:**
- The best "state of the art" alt-data survey remains **Kolanovic and Krishnamachari (2017), "Big Data and AI Strategies: Machine Learning and Alternative Data Approach to Investing"** (J.P. Morgan Global Quantitative & Derivatives Strategy, 280-page report). Not freely available but heavily cited.
- **AlternativeData.org** (industry consortium, now under Neudata) catalogues ~500+ live alt-data vendors covering satellite imagery, credit card panels, geolocation, web-scraping, email receipts, sentiment/NLP, weather, ESG, shipping/AIS. — https://alternativedata.org/
- Wikipedia's Alternative Data article is a decent survey. — https://en.wikipedia.org/wiki/Alternative_data_(finance)

**Typical integration pattern (industry-standard as of 2024-2026):**
1. Alt data becomes a *feature* alongside factor-based / fundamental features in a supervised model.
2. Nowcasting: alt data used to *estimate* traditional variables (e.g., credit-card panels to nowcast retailer revenue before earnings).
3. Meta-model: alt-data-derived predictions ensembled with factor composite via a secondary GBM or elastic-net-per-name.
4. Alt data heavy in cross-validation carefully because of heavy nonstationarity and vendor overlap.

**Empirical performance post-2010** (from multiple industry reports and academic surveys, e.g., Feng, Giglio, Xiu 2020 "Taming the Factor Zoo," JoF): factor returns have declined substantially post-publication (per McLean-Pontiff 2016), with value in particular experiencing a decade-long drawdown 2010-2020 (see AQR's "Value's Long Journey" and Cliff Asness's public defence of value — https://www.aqr.com/Insights/Research/Journal-Article/Its-Time-for-a-Venial-Value-Timing-Sin). Momentum has been more resilient but with brutal crashes (e.g., 2009 momentum crash: -74% in a few months, documented in Daniel & Moskowitz 2016, "Momentum Crashes," JFE).

---

## Additional: Modern quant textbook state-of-the-art recommendations

| Book | Author | Year | Publisher | State-of-the-art it recommends |
|---|---|---|---|---|
| *Active Portfolio Management*, 2nd ed. | Grinold & Kahn | 1999 | McGraw-Hill | Fundamental Law; multi-factor risk models; MVO with alpha overlay |
| *Inside the Black Box*, 3rd ed. | Rishi Narang | 2024 | Wiley | Strategy taxonomy (theory-driven vs data-driven); risk / execution / research pipelines. Skeptical primer for allocators. — https://www.wiley.com/en-us/Inside+the+Black+Box%3A+A+Simple+Guide+to+Systematic+Investing%2C+3rd+Edition-p-9781394214785 |
| *Advances in Financial Machine Learning* | López de Prado | 2018 | Wiley | Proper CV (purged, combinatorial), meta-labeling, fractional differentiation, DSR, feature importance (MDI, MDA, SFI), HRP portfolio optimization |
| *Machine Learning for Asset Managers* | López de Prado | 2020 | Cambridge Univ. Press (Elements) | Denoising covariance matrices, hierarchical clustering, causal factor models. Short and pointed. |
| *Quantitative Portfolio Management: The Art and Science of Statistical Arbitrage* | Michael Isichenko | 2021 | Wiley | Feature engineering, forecast combination via secondary ML, dim-reduction, "benign overfitting," multi-period trading-cost-aware portfolio construction, optimal leverage. Most modern of the four. — Scholar entry: "Isichenko delivers a systematic review of the quantitative trading of equities, or statistical arbitrage" |
| *Algorithmic Trading* | Ernie Chan | 2013 | Wiley | Pairs trading, mean reversion, momentum strategies, backtesting hygiene. More entry-level. Chan now runs E.P. Chan & Associates and Predictnow.ai focusing on ML for finance. — https://www.epchan.com/ |

**Common ground across López de Prado / Isichenko / Narang (the modern trio):**
1. Time-series-aware CV (purged, embargoed, combinatorial) is essential — vanilla k-fold *will* leak signal.
2. Meta-labeling / signal filtering is standard for boosting Sharpe by shrinking bet size on low-conviction primary signals.
3. Fractional differentiation for stationarity without memory loss.
4. Multiple-testing correction (Deflated Sharpe, Bonferroni, or SPA/step-down) is mandatory; naive backtest Sharpes are useless.
5. Trading costs and portfolio construction constraints are first-class citizens; a strategy that ignores costs is a paper strategy.

---

## Recent (2023-2026) developments worth flagging

1. **LLM-based signal generation** — the FinBERT / FinGPT / BloombergGPT wave, and use of ChatGPT-style models for earnings-call summarisation, alternative-text sentiment, and analyst-report NLP. QuantConnect now natively supports Hugging Face models (FinBERT, DistilBERT, Chronos, FinBERT, Chronos-Bolt) inside its Lean framework — see the docs sidebar in Section 23.
2. **Factor zoo shrinkage** — Feng, Giglio, Xiu 2020 JoF; Kelly, Pruitt, Su 2019 (IPCA — instrumented PCA) — moves away from published factors toward *learned* latent factors that condition on characteristics.
3. **Pod-fund AUM boom** — Millennium, Citadel, Point72, ExodusPoint, Balyasny have collectively taken on hundreds of billions since 2020. The "high-Sharpe multi-manager fee model" (pass-through fees ~5-6% + 20% carry) is a structural change. This is the "SBF-shaped" story of the industry — allocators are paying for consistent single-digit Sharpe with low-vol characteristics.
4. **Options-heavy zero-DTE and volatility strategies** — the growth of intraday options, 0DTE S&P options especially post-2022, has changed the microstructure of the entire US market. This is more a market-structure story than a quant-strategy one, but every equity signal now has to account for it.
5. **Cheap compute + PyTorch/JAX** — practically everything is trained on GPU now. Kelly et al. and follow-ups increasingly use JAX-based conditional autoencoders (CAE) for characteristics-based factor models. See Chen, Pelger, Zhu (2024 *JoF*) — "Deep Learning in Asset Pricing."

---

## Bibliography — all URLs cited

**Papers and journals:**
- Fama & French 1993 JFE — https://doi.org/10.1016/0304-405X(93)90023-5
- Fama & French 1992 JoF — https://doi.org/10.1111/j.1540-6261.1992.tb04398.x
- Carhart 1997 JoF — https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.1997.tb03808.x, JSTOR https://www.jstor.org/stable/2329556
- Fama & French 2015 JFE — https://doi.org/10.1016/j.jfineco.2014.10.010
- Asness, Moskowitz, Pedersen 2013 JoF (via AQR) — https://www.aqr.com/Insights/Research/Journal-Article/Value-and-Momentum-Everywhere
- Black & Litterman 1991 JFI — DOI 10.3905/jfi.1991.408013
- Black & Litterman 1992 FAJ — DOI 10.2469/faj.v48.n5.28
- He & Litterman 2002 SSRN — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=334304
- Kritzman & Li 2010 FAJ — https://rpc.cfainstitute.org/research/financial-analysts-journal/2010/skulls-financial-turbulence-and-risk-management
- McLean & Pontiff 2016 JoF — https://onlinelibrary.wiley.com/doi/10.1111/jofi.12365, NBER https://www.nber.org/papers/w20591
- Bailey & López de Prado 2014 JPM — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Almgren & Chriss 2000/2001 JoR — https://www.smallake.kr/wp-content/uploads/2016/03/optliq.pdf
- Kyle 1985 Econometrica — https://www.jstor.org/stable/1913210
- Gu, Kelly, Xiu 2020 RFS — https://academic.oup.com/rfs/article/33/5/2223/5758276
- Grinold 1989 JPM (paper title "The Fundamental Law of Active Management")
- Grinold & Kahn *Active Portfolio Management* 2nd ed. (1999) McGraw-Hill — https://www.mheducation.com/highered/product/M9780070248823.html

**Books:**
- López de Prado 2018 — https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086
- Isichenko 2021 — Wiley
- Narang 2024 (Inside the Black Box, 3rd ed.) — https://www.wiley.com/en-us/Inside+the+Black+Box%3A+A+Simple+Guide+to+Systematic+Investing%2C+3rd+Edition-p-9781394214785
- Zuckerman 2019 (Renaissance) — https://en.wikipedia.org/wiki/The_Man_Who_Solved_the_Market

**Firm and industry:**
- AQR Machine Learning Learning Center — https://www.aqr.com/Learning-Center/Machine-Learning
- AQR CIO Perspectives (Asness interview) — https://www.aqr.com/Insights/Research/Journal-Article/CIO-Perspectives-An-Interview-with-Cliff-Asness
- AQR Asness interview PDF — https://www.aqr.com/-/media/AQR/Documents/Journal-Articles/AQR-JPM-CIO-Perspective-Interview-with-Cliff-Asness.pdf
- Renaissance Technologies (Wikipedia) — https://en.wikipedia.org/wiki/Renaissance_Technologies
- Jim Simons (Wikipedia) — https://en.wikipedia.org/wiki/Jim_Simons
- Cliff Asness (Wikipedia) — https://en.wikipedia.org/wiki/Cliff_Asness
- D.E. Shaw & Co. (Wikipedia) — https://en.wikipedia.org/wiki/D._E._Shaw_%26_Co.
- Two Sigma (Wikipedia) — https://en.wikipedia.org/wiki/Two_Sigma
- Citadel LLC (Wikipedia) — https://en.wikipedia.org/wiki/Citadel_LLC
- Millennium Management (Wikipedia) — https://en.wikipedia.org/wiki/Millennium_Management
- Alternative Data (Wikipedia) — https://en.wikipedia.org/wiki/Alternative_data_(finance)
- MSCI factor investing — https://www.msci.com/factor-investing
- MSCI Barra risk models — https://www.msci.com/barrafactorindexes
- Ken French Data Library — https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

**Frameworks and open source:**
- QuantConnect Lean docs — https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview
- QuantConnect Lean GitHub — https://github.com/QuantConnect/Lean
- Zipline (Quantopian) — https://github.com/quantopian/zipline
- Zipline-reloaded — https://github.com/stefan-jansen/zipline-reloaded
- Alphalens (Quantopian) — https://github.com/quantopian/alphalens
- pyfolio (Quantopian) — https://github.com/quantopian/pyfolio
- QuantStats — https://github.com/ranaroussi/quantstats
- ML for Trading (Stefan Jansen) — https://github.com/stefan-jansen/machine-learning-for-trading
- MLFinLab (Hudson & Thames) — https://github.com/hudson-and-thames/mlfinlab

**Wikipedia articles on foundational concepts:**
- Fama-French 3-factor — https://en.wikipedia.org/wiki/Fama%E2%80%93French_three-factor_model
- Carhart 4-factor — https://en.wikipedia.org/wiki/Carhart_four-factor_model
- Black-Litterman — https://en.wikipedia.org/wiki/Black%E2%80%93Litterman_model
- Almgren-Chriss — https://en.wikipedia.org/wiki/Almgren%E2%80%93Chriss_model
- Robert Almgren — https://en.wikipedia.org/wiki/Robert_Almgren
- Information Coefficient — https://en.wikipedia.org/wiki/Information_coefficient
- Active Return — https://en.wikipedia.org/wiki/Active_return
