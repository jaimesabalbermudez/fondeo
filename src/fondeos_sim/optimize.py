"""Búsqueda de la mejor estrategia por plan y ranking entre planes.

La evaluación y la fase funded se optimizan por separado: el valor de una cuenta funded no depende
de cómo se pasó la evaluación, y la evaluación solo necesita ese valor para decidir cuánto vale pasar.

Métricas:
- EV por intento = P(pasar) x V_funded x (1 - p_denegación) - coste esperado del intento
  (precio o reset, meses facturados si es suscripción, activación si pasa).
- EV por día de hueco funded: beneficio por cuenta funded (V - coste de conseguirla) / días que
  ocupa el hueco. Relevante porque las firmas limitan las cuentas funded simultáneas.
"""

from dataclasses import dataclass, replace
from itertools import product

import numpy as np

from .engine import EvalStrategy, FundedStrategy, simulate_eval, simulate_funded
from .plan import Plan


@dataclass(frozen=True)
class Frictions:
    eval: float = 10.0    # 1 NQ: comisión ida y vuelta + ~1 tick de slippage
    gordo: float = 10.0
    grind: float = 8.0    # ~5 MNQ


@dataclass
class PlanResult:
    plan: Plan
    eval_strat: EvalStrategy | None
    funded_strat: FundedStrategy
    ev: dict
    fd: dict
    p_pass: float
    cost: float
    value: float
    ev_attempt: float
    roi: float
    profit_per_funded: float
    ev_per_slot_day: float


def eval_grid(plan: Plan, fr: Frictions):
    r = plan.eval
    targets = {r.profit_target, r.profit_target / 2, r.profit_target / 3, 750.0, 1000.0, 1500.0, 2000.0}
    if r.consistency:
        targets.add(round(r.consistency * r.profit_target))
    risks = [None, 1500.0, 1000.0]
    return [EvalStrategy(day_target=t, risk=k, friction=fr.eval) for t, k in product(sorted(targets), risks)]


def funded_grid(plan: Plan, fr: Frictions):
    po = plan.funded.payout
    gordos = {0.0, 1000.0, 2000.0, 3000.0, 4000.0, 6000.0, 8000.0, 10000.0}
    if po.buffer:
        gordos |= {po.buffer + max(po.min_amount, po.min_cycle_profit), po.buffer + 1000.0}
    base = max(po.green_min, 150.0)
    grinds = sorted({base, 300.0, 500.0})
    out = []
    # stop de los días verdes como múltiplo del objetivo; inf = sin stop (arriesgar todo el margen)
    for g, t, mult, cg in product(sorted(gordos), grinds, (2.0, 4.0, 7.0, 10.0, float("inf")), (0.0, 1000.0, 4000.0)):
        out.append(FundedStrategy(gordo_target=g, grind_target=t, grind_risk=t * mult, cycle_gordo=cg,
                                  friction_gordo=fr.gordo, friction_grind=fr.grind))
    return out


def _best(results, key, refine, top=3):
    """Elige por `key` y re-simula los mejores con más muestras para evitar la maldición del ganador."""
    results.sort(key=key, reverse=True)
    refined = [(s, refine(s)) for s, _ in results[:top]]
    return max(refined, key=key)


def optimize_plan(plan: Plan, n: int = 20_000, n_refine: int = 100_000, fr: Frictions = Frictions(),
                  funded_objective: str = "value", horizon: int = 120, seed: int = 0) -> PlanResult:
    rng = np.random.default_rng(seed)
    p_keep = 1 - plan.p_payout_denial

    def run_funded(s, size):
        return simulate_funded(plan, s, size, rng, horizon=horizon)

    def f_key(item):
        s, f = item
        if funded_objective == "per_day":
            return f["net"] / max(f["days"], 1)
        return f["net"]

    funded = [(s, run_funded(s, n)) for s in funded_grid(plan, fr)]
    fs, fd = _best(funded, f_key, lambda s: run_funded(s, n_refine))
    value = fd["net"] * p_keep

    if plan.eval is None:
        es, ed, p_pass, cost = None, {"days": 0.0, "months_billed": 1.0}, 1.0, plan.costs.eval_price
    else:
        def e_cost(e):
            months = e["months_billed"] if plan.costs.billing == "monthly" else 1.0
            return plan.costs.attempt_price() * months + e["p_pass"] * plan.costs.activation_fee

        def e_key(item):
            _, e = item
            return e["p_pass"] * value - e_cost(e)

        evals = [(s, simulate_eval(plan, s, n, rng)) for s in eval_grid(plan, fr)]
        es, ed = _best(evals, e_key, lambda s: simulate_eval(plan, s, n_refine, rng))
        p_pass, cost = ed["p_pass"], e_cost(ed)

    ev_attempt = p_pass * value - cost
    profit_per_funded = value - cost / max(p_pass, 1e-9)
    return PlanResult(plan=plan, eval_strat=es, funded_strat=fs, ev=ed, fd=fd, p_pass=p_pass, cost=cost,
                      value=value, ev_attempt=ev_attempt, roi=ev_attempt / cost,
                      profit_per_funded=profit_per_funded,
                      ev_per_slot_day=profit_per_funded / max(fd["days"], 1))


def with_denial(plan: Plan, p: float) -> Plan:
    return replace(plan, p_payout_denial=p)
