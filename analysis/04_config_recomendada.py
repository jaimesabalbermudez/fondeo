"""Elige los parámetros de la forma de operar recomendada (recommended.Config).

Rejilla sobre: caja a partir de la que se amplía la cartera (MFFU + FundedNext), umbral de juego
prudente y tamaño del día gordo prudente. Se evalúa con bankrolls pequeños y medianos (6 meses).
"""

from itertools import product

import numpy as np

from fondeos_sim.portfolio import simulate_portfolio
from fondeos_sim.recommended import Config, Slot, allocations

BANKROLLS = (1000, 3000)
rows = []
for expand, below, gordo in product((2000, 3000, 5000), (1000, 2000, 3000), (1000, 2000, 3000)):
    cfg = Config(slots=(Slot("lucid_flex_50k_dll", 5), Slot("tradeify_select_flex_50k", 5),
                        Slot("mffu_rapid_eod_50k", 3, expand), Slot("fundednext_flex_50k", 5, expand)),
                 prudent_below=below, prudent_gordo=gordo)
    al = allocations(cfg)
    m = []
    for b in BANKROLLS:
        r = simulate_portfolio(al, b, 6, n_paths=1500, seed=3)
        pr = r.final - b
        m += [r.ruined.mean(), np.median(pr), pr.mean()]
    rows.append(((expand, below, gordo), m))
    print(f"ampliar {expand:>5} prudente<{below:>5} gordo {gordo:>5} | "
          + " | ".join(f"${b}: ruina {m[3*i]:.0%} mediana {m[3*i+1]:>7,.0f} media {m[3*i+2]:>7,.0f}"
                       for i, b in enumerate(BANKROLLS)), flush=True)

best = min(rows, key=lambda x: x[1][0] + x[1][3])
print("\nMenor ruina media:", best)
