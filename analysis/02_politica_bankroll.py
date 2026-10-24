"""¿Conviene empezar con pocas cuentas de alto rendimiento y ampliar al crecer el bankroll?

Compara políticas de cartera con el mismo bankroll inicial (6 meses, precios verificados).
"""

from dataclasses import replace

import numpy as np

from fondeos_sim.optimize import optimize_plan
from fondeos_sim.plan import load_plan
from fondeos_sim.portfolio import Allocation, simulate_portfolio

MONTHS = 6
PATHS = 2000
BANKROLLS = (500, 1000, 2000, 3000, 5000)

opt = {}
for pid in ("lucid_flex_50k_dll", "tradeify_select_flex_50k", "mffu_rapid_eod_50k", "fundednext_flex_50k"):
    plan = load_plan(f"plans/{pid}.yaml").with_price_mode("verificados")
    opt[pid] = optimize_plan(plan, n=10_000, n_refine=50_000, funded_objective="per_day")


def alloc(pid, parallel, prudent=False, lo=0.0, hi=float("inf")):
    r = opt[pid]
    fs = replace(r.funded_strat, gordo_target=2000.0, grind_target=150.0, grind_risk=600.0, cycle_gordo=0.0) \
        if prudent else r.funded_strat
    return Allocation(r.plan, r.eval_strat, fs, parallel, min_cash=lo, max_cash=hi,
                      label=f"{pid}{'_prudente' if prudent else ''}_{lo:.0f}")


TOP = ("lucid_flex_50k_dll", "tradeify_select_flex_50k")
REST = (("mffu_rapid_eod_50k", 3), ("fundednext_flex_50k", 5))
SCALE = 3000   # caja a partir de la que se amplía la cartera
SAFE = 2000    # caja por debajo de la que se juega prudente

policies = {
    "A. Todo desde el inicio": [alloc(p, 5) for p in TOP] + [alloc(p, n) for p, n in REST],
    "B. Solo Lucid DLL + Tradeify": [alloc(p, 5) for p in TOP],
    f"C. B y ampliar con caja ≥ ${SCALE:,}": [alloc(p, 5) for p in TOP] + [alloc(p, n, lo=SCALE) for p, n in REST],
    "D. C + día gordo de $2k con poca caja": (
        [alloc(p, 5, prudent=True, hi=SAFE) for p in TOP] + [alloc(p, 5, lo=SAFE) for p in TOP]
        + [alloc(p, n, lo=SCALE) for p, n in REST]),
    "E. D + solo 2 evals por plan con poca caja": (
        [alloc(p, 2, prudent=True, hi=SAFE) for p in TOP] + [alloc(p, 5, lo=SAFE) for p in TOP]
        + [alloc(p, n, lo=SCALE) for p, n in REST]),
    "F. Todo prudente siempre (día gordo $2k)": [alloc(p, 5, prudent=True) for p in TOP]
                                               + [alloc(p, n, lo=SCALE) for p, n in REST],
}

print(f"{'Política':45} {'Bankroll':>8} {'Media':>9} {'Mediana':>9} {'P(ruina)':>9} {'p10':>9} {'p90':>9}")
for name, allocs in policies.items():
    for b in BANKROLLS:
        res = simulate_portfolio(allocs, b, MONTHS, n_paths=PATHS, seed=7)
        pr = res.final - b
        print(f"{name:45} {b:>8,} {pr.mean():>9,.0f} {np.median(pr):>9,.0f} {res.ruined.mean():>9.0%} "
              f"{np.percentile(pr, 10):>9,.0f} {np.percentile(pr, 90):>9,.0f}")
    print()
