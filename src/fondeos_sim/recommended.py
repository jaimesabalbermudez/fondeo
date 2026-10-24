"""La forma de operar recomendada: qué planes, en qué orden, con qué estrategia y cuántas cuentas.

Todo el dashboard usa esta configuración. Los parámetros por defecto salen de
`analysis/04_config_recomendada.py` (búsqueda en rejilla minimizando la ruina sin perder rentabilidad).

Reglas de operación:
- Solo firmas con drawdown EOD y sin prohibiciones contra la estrategia (p_payout_denial bajo).
- Cada cuenta hace su propio trade, una detrás de otra (resultados independientes; nunca copiar el
  mismo trade en todas a la vez).
- Se empieza por los planes de más ROI y se amplía la cartera cuando crece la caja.
- Con poca caja se juega "prudente": día gordo más pequeño, que cobra más a menudo.
"""

from dataclasses import dataclass, replace

from .cache import ROOT, cached
from .engine import FundedStrategy
from .optimize import Frictions, PlanResult, optimize_plan
from .plan import Plan, load_plan, load_plans
from .portfolio import Allocation, PortfolioResult, bankroll_for_ruin, simulate_portfolio

PLANS_DIR = ROOT / "plans"
PRICE_MODE = "verificados"
OBJECTIVE = "per_day"
FRICTIONS = Frictions()


@dataclass(frozen=True)
class Slot:
    plan_id: str
    parallel: int          # evaluaciones a la vez
    from_cash: float = 0   # se activa con caja libre >= esto


@dataclass(frozen=True)
class Config:
    slots: tuple[Slot, ...] = (
        Slot("lucid_flex_50k_dll", 5),
        Slot("tradeify_select_flex_50k", 5),
        Slot("mffu_rapid_eod_50k", 3, 3000),
        Slot("fundednext_flex_50k", 5, 3000),
    )
    prudent_below: float = 3000   # con caja libre por debajo se juega prudente
    prudent_gordo: float = 2000   # día gordo prudente; después días verdes +150 / stop 600


DEFAULT = Config()


def plan(plan_id: str) -> Plan:
    return load_plan(PLANS_DIR / f"{plan_id}.yaml").with_price_mode(PRICE_MODE)


def optimized(plan_id: str) -> PlanResult:
    """Mejor estrategia de un plan (en disco: solo se recalcula si cambian reglas o motor)."""
    return cached("opt", (plan_id, PRICE_MODE, OBJECTIVE, FRICTIONS),
                  lambda: optimize_plan(plan(plan_id), n=20_000, n_refine=100_000, fr=FRICTIONS,
                                        funded_objective=OBJECTIVE))


def all_plans_ranked() -> list[PlanResult]:
    ids = [p.id for p in load_plans(PLANS_DIR)]
    return sorted((optimized(i) for i in ids), key=lambda r: r.ev_attempt, reverse=True)


def prudent_strategy(fs: FundedStrategy, cfg: Config = DEFAULT) -> FundedStrategy:
    return replace(fs, gordo_target=cfg.prudent_gordo, grind_target=150.0, grind_risk=600.0, cycle_gordo=0.0)


def allocations(cfg: Config = DEFAULT) -> list[Allocation]:
    out = []
    for s in cfg.slots:
        r = optimized(s.plan_id)
        lo = s.from_cash
        if lo < cfg.prudent_below:
            out.append(Allocation(r.plan, r.eval_strat, prudent_strategy(r.funded_strat, cfg), s.parallel,
                                  min_cash=lo, max_cash=cfg.prudent_below, label=f"{s.plan_id}:prudente"))
            lo = cfg.prudent_below
        out.append(Allocation(r.plan, r.eval_strat, r.funded_strat, s.parallel, min_cash=lo, label=s.plan_id))
    return out


def simulate(bankroll: float, months: float = 6, n_paths: int = 2000, cfg: Config = DEFAULT,
             **kw) -> PortfolioResult:
    return cached("cartera", (bankroll, months, n_paths, cfg, sorted(kw.items())),
                  lambda: simulate_portfolio(allocations(cfg), bankroll, months, n_paths=n_paths, seed=7, **kw))


def bankroll_needed(target: float, months: float = 6, cfg: Config = DEFAULT) -> tuple[float, float]:
    return cached("bankroll", (target, months, cfg),
                  lambda: bankroll_for_ruin(allocations(cfg), target, months, n_paths=1500))


def precompute():
    """Calcula y guarda en disco todo lo que usa el dashboard."""
    for r in all_plans_ranked():
        print(f"  {r.plan.id}: EV/intento ${r.ev_attempt:,.0f}")
    for target in (0.10, 0.05, 0.01):
        b, r = bankroll_needed(target)
        print(f"  bankroll para ruina <= {target:.0%}: ${b:,.0f}")
    for b in BANKROLL_LEVELS:
        simulate(b, n_paths=1500)
    for months in (3, 6, 12):               # cifras de la Guía y valores por defecto de la Simulación
        simulate(5000, months)
    print("  listo")


BANKROLL_LEVELS = (500, 1000, 2000, 3000, 5000, 8000, 12000)
