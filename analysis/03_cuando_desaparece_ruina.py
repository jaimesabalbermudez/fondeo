"""¿Con qué bankroll, y a partir de cuántas evaluaciones, la ruina deja de ser un riesgo?

Cartera por defecto del dashboard: Lucid DLL y Tradeify (5 evaluaciones a la vez) desde el inicio,
jugando prudente (día gordo $2k) con caja < $2k; MFFU Rapid EOD y FundedNext a partir de $3k.
"""

from dataclasses import replace

import numpy as np

from fondeos_sim.optimize import optimize_plan
from fondeos_sim.plan import load_plan
from fondeos_sim.portfolio import Allocation, simulate_portfolio

MONTHS = 12
PATHS = 4000
BANKROLLS = (250, 500, 1000, 1500, 2000, 3000, 4000, 6000, 8000, 12000)

opt = {}
for pid in ("lucid_flex_50k_dll", "tradeify_select_flex_50k", "mffu_rapid_eod_50k", "fundednext_flex_50k"):
    plan = load_plan(f"plans/{pid}.yaml").with_price_mode("verificados")
    opt[pid] = optimize_plan(plan, n=10_000, n_refine=50_000, funded_objective="per_day")


def alloc(pid, parallel, prudent=False, **kw):
    r = opt[pid]
    fs = replace(r.funded_strat, gordo_target=2000.0, grind_target=150.0, grind_risk=600.0, cycle_gordo=0.0) \
        if prudent else r.funded_strat
    return Allocation(r.plan, r.eval_strat, fs, parallel, label=pid + ("_p" if prudent else ""), **kw)


allocs = [alloc("lucid_flex_50k_dll", 5, True, max_cash=2000), alloc("tradeify_select_flex_50k", 5, True, max_cash=2000),
          alloc("lucid_flex_50k_dll", 5, min_cash=2000), alloc("tradeify_select_flex_50k", 5, min_cash=2000),
          alloc("mffu_rapid_eod_50k", 3, min_cash=3000), alloc("fundednext_flex_50k", 5, min_cash=3000)]
price = np.mean([opt[p].plan.costs.attempt_price() for p in ("lucid_flex_50k_dll", "tradeify_select_flex_50k")])

print(f"Precio medio de una evaluación al empezar: ${price:.0f}\n")
print(f"{'Bankroll':>8} {'= evals':>7} {'P(ruina)':>9} | ruinas: evals compradas p50/p95/p99/máx | día p95/máx"
      f" | riesgo que queda tras comprar >N evals: N=10   20   40   80")
for b in BANKROLLS:
    res = simulate_portfolio(allocs, b, MONTHS, n_paths=PATHS, seed=4)
    ru, ev = res.ruined, res.evals
    line = f"{b:>8,} {b / price:>7.0f} {ru.mean():>9.1%} | "
    if ru.any():
        e, d = ev[ru], res.ruin_day[ru]
        line += f"{np.median(e):>5.0f} {np.percentile(e, 95):>5.0f} {np.percentile(e, 99):>5.0f} {e.max():>5.0f}" \
                f"           | {np.percentile(d, 95):>4.0f} {d.max():>4.0f}"
    else:
        line += f"{'—':>29}           | {'—':>9}"
    rest = [(ru & (ev > n)).sum() / max((ev > n).sum(), 1) for n in (10, 20, 40, 80)]
    print(line + " | " + "  ".join(f"{r:>5.1%}" for r in rest))
