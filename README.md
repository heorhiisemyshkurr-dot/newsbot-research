# Newsbot — does crypto news actually predict price?

A measurement study, not a trading product. The question was simple and the
answer was allowed to be "no": **do crypto news headlines carry predictive
power over price?**

The bot read 21 news sources, scored each item by rules into 0–100, opened a
paper trade, and then measured what the price actually did. Everything was
built so that a negative result would be visible rather than explained away.

## What the data said

**News: no signal.** 81% of the move happens *before* the headline appears.
None of five horizons (15/30/60/120/240 min) showed an effect — every
confidence interval covered 50%.

**Price: a small, real edge.** On a year of minute candles across 7 coins
with 13 features:

| Measurement | Result |
|---|---|
| Direction hit rate | 53.2%, CI [51.9%, 54.5%] — excludes 50% |
| Independent samples | 6 015 of 100 122 predictions, after correcting for coin correlation (÷5.3) and window overlap |
| Amplitude | Last-hour volatility separates deciles by 4.8× while hit rate holds |
| Exit structure | Symmetric stop/take −0.112% vs −0.113% — made no difference |
| Gross edge | +0.010%, CI [−0.004%, +0.024%] — **not distinguishable from zero** |
| Costs | 0.12% — twelve times the gross edge |

**Conclusion: the edge exists in direction but is eaten by execution costs.**
That is the honest finding, and the project reports it as the headline rather
than burying it.

## Method rules the project held itself to

These are written down in [`HYPOTHESES.md`](HYPOTHESES.md) and were fixed
*before* looking at results:

- every number from a sample is reported with confidence intervals — a point
  estimate on a small sample is a trap
- the threshold and the verdict are declared before the data is examined
- when many variants are tried, attempts are counted honestly: the verdict is
  passed at the pre-announced level, everything else is diagnostics
- corrections for correlated assets and overlapping windows are applied before
  claiming independence

## Layout

| Path | What it is |
|---|---|
| [`HYPOTHESES.md`](HYPOTHESES.md) | Hypotheses with thresholds fixed in advance |
| [`RESEARCH.md`](RESEARCH.md) | Methodology and results |
| [`ДОСЛІДЖЕННЯ-РИНКІВ.md`](ДОСЛІДЖЕННЯ-РИНКІВ.md) | Market/data-source survey (Ukrainian) |
| [`research/`](research) | The analysis pipeline |

## Not included

This repository is research only. The live trading server, deployment
scripts, Android client, credentials and infrastructure addresses are
deliberately left out.

Written in Python. Research notes are in Ukrainian; this summary is the
English entry point.
