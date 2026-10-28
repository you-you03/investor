# Offline weight sensitivity — 2026-10-28

Live weights were not changed. `investor/config.py` and the research score formula were not written.

- Live mix: fundamentals 0.60 / momentum 0.25 / catalyst 0.15
- Run ids with any week12 alpha fetched (all strategy versions, diagnostic): 22
- /review gate is unchanged: no live weight change below 10 independent matured Strategy V2 runs, and this report does not clear that gate.
- HIGH conviction stays disabled until 30 matured OOS observations.
- Catalyst rows tagged `catalyst_data_missing` are left out of these blends.
- Spearman below is diagnostic pooled IC of the blended score versus SPY alpha. It is not a permission to retune.

| Mix | Horizon | N | Spearman ρ |
|---|---|---|---|
| live | week4 | 294 | +0.084 |
| live | week12 | 293 | +0.262 |
| more_fundamental | week4 | 294 | +0.106 |
| more_fundamental | week12 | 293 | +0.297 |
| more_momentum | week4 | 294 | +0.046 |
| more_momentum | week12 | 293 | +0.195 |
| more_catalyst | week4 | 294 | +0.111 |
| more_catalyst | week12 | 293 | +0.296 |
| balanced_momentum | week4 | 294 | +0.025 |
| balanced_momentum | week12 | 293 | +0.145 |
| equal | week4 | 294 | +0.025 |
| equal | week12 | 293 | +0.133 |

Next live decision remains: keep Strategy V2 weights fixed until the review gates say otherwise.
