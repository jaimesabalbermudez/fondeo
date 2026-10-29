"""¿Evaluaciones todas a la vez (el mismo trade copiado) y funded una detrás de otra?

Compara con la configuración recomendada (cada cuenta su trade, uno detrás de otro). Copiar las
evaluaciones tiene dos efectos:
- Ahorra tiempo: todas cuentan como un solo trade, así que caben más trades de funded al día.
- Correlación: aprueban y suspenden juntas. rho = 1 si todas usan el mismo bracket (Lucid y Tradeify
  ±$1.200); con brackets distintos (MFFU +$900/−$2.000) la correlación real es menor (~0,7).

`uv run python analysis/08_evals_a_la_vez.py`
"""

import numpy as np

from fondeos_sim.portfolio import simulate_portfolio
from fondeos_sim.recommended import DEFAULT, allocations

CASES = [("Recomendado: cada cuenta su trade, uno detrás de otro", "none", 0.0),
         ("Evaluaciones a la vez (mismo trade, ρ=1), funded de una en una", "evals", 1.0),
         ("Evaluaciones a la vez (brackets distintos, ρ=0,7), funded de una en una", "evals", 0.7)]

allocs = allocations(DEFAULT)
for tpd in (DEFAULT.trades_per_day, None):
    print(f"\n### Trades al día: {tpd or 'sin límite'}")
    for bankroll in (1000, 2000, 5000):
        print(f"\nBankroll ${bankroll:,} · 12 meses")
        print(f"  {'':72} {'mediana':>9} {'media':>9} {'p10':>9} {'ruina':>6} {'evals compradas':>15}")
        for label, copy, rho in CASES:
            r = simulate_portfolio(allocs, bankroll, 12, n_paths=1500, seed=7, copy=copy, rho=rho,
                                   trades_per_day=tpd)
            p = r.final - bankroll
            print(f"  {label:72} {np.median(p):9,.0f} {p.mean():9,.0f} {np.percentile(p, 10):9,.0f} "
                  f"{r.ruined.mean():6.1%} {r.evals.mean():15.0f}")
