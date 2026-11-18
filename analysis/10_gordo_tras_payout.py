"""Tras un payout: ¿otro día gordo o directamente días verdes?

El optimizador (`optimize.funded_grid`) elegía para Lucid Flex 50K un día gordo de +1.000 $ tras cada
payout (`cycle_gordo`). Aquí se compara con volver directamente a los días verdes (+150 $, 5 MNQ):
1. Desde el estado justo después de un payout, para varios colchones (beneficio sobre el balance inicial
   que queda en la cuenta), con gordos de ciclo de 0 a 3.000 $.
2. Una funded nueva de principio a fin (con su primer día gordo, que no cambia).
3. La cartera recomendada a 12 meses, con y sin estrés.
Resultado (2026-11-18): sin gordo de ciclo hay más payouts y más dinero con cualquier colchón; solo
tarda más días. `hoy.GREENS_AFTER_PAYOUT` lo aplica al plan del día en Lucid.

`uv run python analysis/10_gordo_tras_payout.py > reports/gordo_tras_payout.txt`
"""

from dataclasses import replace

import numpy as np

from fondeos_sim import engine
from fondeos_sim import recommended as rec
from fondeos_sim.portfolio import simulate_portfolio

PID = "lucid_flex_50k_dll_c50"
GORDOS = (0.0, 500.0, 1000.0, 2000.0, 3000.0)
COLCHONES = (500, 1000, 2000, 3000, 4000, 5000, 6000, 8000)
N = 60_000

r = rec.optimized(PID)
plan, fs0 = r.plan, r.funded_strat
split = plan.funded.payout.split
print(f"# {PID}: día gordo tras cada payout frente a solo días verdes\n")
print(f"Estrategia del optimizador: {fs0}")
print("Edge 0, retiros pagados. Neto = bruto x split.\n")

print("## 1. Desde justo después de un payout (quedan 4 payouts como máximo)\n")
print(f"  {'colchón':>8} {'gordo':>6} {'payouts':>8} {'neto':>7} {'P(>=1)':>7} {'P(4)':>6} {'días':>5}")
for P in COLCHONES:
    for cg in GORDOS:
        st = engine.FundedState(plan, replace(fs0, cycle_gordo=cg), N)
        b = plan.start_balance + P
        st.bal[:] = b
        st.peak[:] = b
        st.floor[:] = plan.start_balance + plan.funded.floor_after_payout
        st.gordo_done[:] = cg <= 0
        st.gordo_level[:] = b + cg
        st.cyc_start[:] = b
        st.payouts[:] = 1
        rng = np.random.default_rng(7)
        for _ in range(400):
            idx = np.flatnonzero(st.active)
            if not idx.size:
                break
            engine.funded_step(st, idx, rng)
        more = st.payouts - 1
        print(f"  {P:>8,} {cg:>6,.0f} {more.mean():>8.2f} {(st.gross * split).mean():>7,.0f}"
              f" {(more >= 1).mean():>7.0%} {(more >= 4).mean():>6.0%} {st.days.mean():>5.0f}")
    print()

print("## 2. Funded nueva, de principio a fin\n")
p_keep = 1 - plan.p_payout_denial
for cg in (1000.0, 0.0):
    f = engine.simulate_funded(plan, replace(fs0, cycle_gordo=cg), 300_000, np.random.default_rng(11), horizon=400)
    value = f["net"] * p_keep
    print(f"  gordo tras payout {cg:>5,.0f}: valor por funded {value:,.0f} $ · payouts {f['payouts_mean']:.2f}"
          f" · P(>=1) {f['p_payout']:.0%} · días {f['days']:.0f} · por evaluación {r.p_pass * value - r.cost:+,.0f} $")

print("\n## 3. Cartera recomendada, 12 meses\n")
base = rec.allocations()
for title, deny, fail in (("Modelo base", 0.0, 0.0), ("Estrés (20% denegados, 30%/año firma deja de pagar)", 0.2, 0.3)):
    print(f"### {title}")
    for bank in (3000.0, 5000.0):
        for cg in (1000.0, 0.0):
            allocs = [replace(a, plan=replace(a.plan, p_payout_denial=max(a.plan.p_payout_denial, deny)),
                              funded_strat=replace(a.funded_strat, cycle_gordo=cg)
                              if a.plan.id.startswith("lucid") and a.funded_strat.cycle_gordo else a.funded_strat)
                      for a in base]
            res = simulate_portfolio(allocs, bank, 12, n_paths=1500, seed=7, firm_failure_year=fail,
                                     trades_per_day=rec.DEFAULT.trades_per_day, **rec.copy_kw())
            g = res.final - bank
            print(f"  bankroll {bank:>6,.0f} · gordo {cg:>5,.0f}: ruina {res.ruined.mean():.1%} · mediana {np.median(g):+,.0f}"
                  f" · p10 {np.percentile(g, 10):+,.0f} · p90 {np.percentile(g, 90):+,.0f}")
    print()
