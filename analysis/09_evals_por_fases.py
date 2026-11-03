"""¿Ir a saco con las evaluaciones desde el principio o solo cuando hay caja?

Consejo de Victor: evaluaciones todas a la vez y funded de una en una. Con poco bankroll eso dispara la
ruina (`reports/evals_a_la_vez.txt`), así que se comparan:
- Opción 2: evaluaciones a la vez desde el primer día, con trades distintos (ρ=0,7) o el mismo (ρ=1).
- Opción 3: cada cuenta su trade mientras la caja libre esté por debajo de un umbral; por encima, se
  copian las evaluaciones. Si la caja vuelve a bajar del umbral, se vuelve al modo prudente.
También con estrés (20% de payouts denegados y 30% anual de que cada firma deje de pagar).

`uv run python analysis/09_evals_por_fases.py`
"""

from dataclasses import replace

import numpy as np

from fondeos_sim.portfolio import simulate_portfolio
from fondeos_sim.recommended import DEFAULT, allocations

BANKROLL, MONTHS, PATHS, TPD = 5000, 12, 2000, 12
UMBRALES = (8000, 10000, 15000, 20000)

base = allocations(DEFAULT)
stress = [replace(a, plan=replace(a.plan, p_payout_denial=max(a.plan.p_payout_denial, 0.2))) for a in base]

CASES = [("Cada cuenta su trade, uno detrás de otro", dict(copy="none"))]
for rho in (0.7, 1.0):
    CASES.append((f"Opción 2: evals a la vez desde el inicio (ρ={rho:g})", dict(copy="evals", rho=rho)))
for rho in (0.7, 1.0):
    for u in UMBRALES:
        CASES.append((f"Opción 3: evals a la vez con caja ≥ ${u:,} (ρ={rho:g})",
                      dict(copy="evals", rho=rho, copy_from_cash=u)))

for title, allocs, kw in (("Modelo base", base, {}),
                          ("Estrés: 20% payouts denegados + 30%/año de que cada firma deje de pagar", stress,
                           dict(firm_failure_year=0.3))):
    print(f"\n### {title}\n\nBankroll ${BANKROLL:,} · {MONTHS} meses · {TPD} trades/día")
    print(f"  {'':58} {'ruina':>6} {'mediana':>9} {'media':>9} {'p10':>9} {'p90':>9} {'evals':>6}")
    for label, extra in CASES:
        r = simulate_portfolio(allocs, BANKROLL, MONTHS, n_paths=PATHS, seed=7,
                               trades_per_day=TPD, **kw, **extra)
        p = r.final - BANKROLL
        print(f"  {label:58} {r.ruined.mean():6.1%} {np.median(p):9,.0f} {p.mean():9,.0f} "
              f"{np.percentile(p, 10):9,.0f} {np.percentile(p, 90):9,.0f} {r.evals.mean():6.0f}")
