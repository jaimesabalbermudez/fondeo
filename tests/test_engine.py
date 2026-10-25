"""Validación del motor contra resultados analíticos conocidos."""

from pathlib import Path

import numpy as np
import pytest

from fondeos_sim.engine import EvalStrategy, FundedStrategy, simulate_eval, simulate_funded
from fondeos_sim.market import bernoulli_trade, path_trade
from fondeos_sim.plan import Costs, EvalRules, FundedRules, Plan, PayoutRules, load_plan, load_plans

N = 200_000


def course_plan(**funded_overrides) -> Plan:
    """Lucid Flex 50K tal como lo describe el curso (consistencia 50%, suelo no salta en el payout)."""
    funded = dict(mll=2000, drawdown="eod", lock_offset=0,
                  payout=PayoutRules(split=0.9, min_green_days=5, green_min=150, min_amount=500,
                                     max_amount=(2000,), pct_of_profit=0.5))
    funded.update(funded_overrides)
    return Plan(id="curso", firm="t", name="t", start_balance=50_000, costs=Costs(eval_price=91),
                eval=EvalRules(mll=2000, drawdown="eod", lock_offset=0, profit_target=3000,
                               consistency=0.5, min_days=2),
                funded=FundedRules(**funded))


def test_bernoulli_breakeven_probability():
    rng = np.random.default_rng(0)
    bal = np.full(N, 50_000.0)
    pnl = bernoulli_trade(rng, bal, bal - 2000, np.full(N, 2000.0), np.full(N, 4000.0))
    assert (pnl > 0).mean() == pytest.approx(1 / 3, abs=0.005)
    assert pnl.mean() == pytest.approx(0, abs=25)


def test_liquidation_acts_as_stop():
    """Stop a $600 con solo $300 de margen: la probabilidad debe ser la de 300 vs 150, no la de 600."""
    rng = np.random.default_rng(1)
    bal = np.full(N, 50_000.0)
    pnl = bernoulli_trade(rng, bal, bal - 300, np.full(N, 600.0), np.full(N, 150.0))
    assert (pnl > 0).mean() == pytest.approx(300 / 450, abs=0.005)
    assert pnl.min() == pytest.approx(-300)


def test_path_trade_matches_gamblers_ruin_without_trailing():
    rng = np.random.default_rng(2)
    n = 20_000
    bal = np.full(n, 50_000.0)
    pnl, _ = path_trade(rng, bal, bal - 1e9, np.full(n, 1000.0), np.full(n, 2000.0), 0.0,
                        mll=1e9, lock_level=np.full(n, np.inf))
    assert (pnl > 0).mean() == pytest.approx(1 / 3, abs=0.015)


def test_path_trade_intraday_trailing_drawup_drawdown():
    """Paseo aleatorio: P(subir W antes de caer D desde el máximo) = exp(-W/D)."""
    rng = np.random.default_rng(3)
    n = 20_000
    bal = np.full(n, 50_000.0)
    pnl, _ = path_trade(rng, bal, bal - 2000, np.full(n, np.inf), np.full(n, 2000.0), 0.0,
                        mll=2000, lock_level=np.full(n, np.inf), resolution=40)
    assert (pnl > 0).mean() == pytest.approx(np.exp(-1), abs=0.02)


def test_course_eval_pass_rate():
    rng = np.random.default_rng(4)
    # sin límite de tamaño ni de tiempo: cada trade se resuelve el mismo día
    r = simulate_eval(course_plan(), EvalStrategy(day_target=1500, contracts=float("inf")), N, rng)
    assert r["p_pass"] == pytest.approx((4 / 7) ** 2, abs=0.004)
    assert r["days_if_pass"] == pytest.approx(2)


def test_course_funded_hits_martingale_bound():
    """Retiros esperados = pérdida absorbida por la firma = 2000 x 2/3 (bruto)."""
    rng = np.random.default_rng(5)
    r = simulate_funded(course_plan(), FundedStrategy(gordo_target=4000, grind_target=150, grind_risk=600),
                        N, rng, horizon=400)
    assert r["gross"] == pytest.approx(2000 * 2 / 3, rel=0.02)


@pytest.mark.parametrize("gordo,grind,grind_risk", [(0, 150, 600), (2000, 300, 300), (6000, 150, 1000)])
def test_funded_never_exceeds_mll(gordo, grind, grind_risk):
    """Con edge 0 ninguna estrategia puede retirar (en esperanza) más que el MLL."""
    rng = np.random.default_rng(6)
    r = simulate_funded(course_plan(floor_after_payout=100),
                        FundedStrategy(gordo_target=gordo, grind_target=grind, grind_risk=grind_risk),
                        50_000, rng, horizon=300)
    assert r["gross"] <= 2000 * 1.02


def test_all_plan_files_load():
    plans = load_plans("plans")
    assert len(plans) >= 5
    assert {p.id for p in plans if not p.all_eod} >= {"mffu_rapid_50k", "tpt_50k"}


@pytest.mark.parametrize("bal,floor,risk,target,lock", [
    (50_000, 48_000, np.inf, 4000, 50_100),
    (50_000, 48_000, 600, 150, 50_100),
    (51_000, 49_000, np.inf, 2600, 50_100),
    (53_000, 50_100, 800, 500, 50_100),
    (50_500, 48_500, 1500, 1000, 50_000),
])
def test_intraday_exact_sampler_matches_random_walk(bal, floor, risk, target, lock):
    from fondeos_sim.market import intraday_trade
    n = 20_000
    args = lambda: (np.full(n, float(bal)), np.full(n, float(floor)), np.full(n, float(risk)), np.full(n, float(target)))
    lk = np.full(n, float(lock))
    p1, f1 = intraday_trade(np.random.default_rng(7), *args(), 5.0, 2000, lk)
    p2, f2 = path_trade(np.random.default_rng(8), *args(), 5.0, 2000, lk, resolution=40)
    assert (p1 >= target).mean() == pytest.approx((p2 >= target).mean(), abs=0.02)
    assert p1.mean() == pytest.approx(p2.mean(), abs=60)
    assert f1.mean() == pytest.approx(f2.mean(), abs=40)


def test_portfolio_profit_matches_attempts_times_ev():
    """Sin ruina, beneficio esperado de la cartera = nº de intentos x EV por intento."""
    from fondeos_sim.portfolio import Allocation, simulate_portfolio
    plan = course_plan()
    es, fs = EvalStrategy(day_target=1500), FundedStrategy(gordo_target=4000)
    rng = np.random.default_rng(9)
    p_pass = simulate_eval(plan, es, N, rng)["p_pass"]
    value = simulate_funded(plan, fs, N, rng)["net"]
    res = simulate_portfolio([Allocation(plan, es, fs, parallel=2)], bankroll=100_000, months=6, n_paths=2000)
    assert res.ruined.mean() == 0
    expected = res.evals.mean() * (p_pass * value - plan.costs.eval_price)
    assert (res.final - 100_000).mean() == pytest.approx(expected, rel=0.08)


@pytest.mark.parametrize("copy", ["firms", "all"])
def test_copying_trades_keeps_expected_value(copy):
    """Copiar trades solo correlaciona resultados: el beneficio medio por intento no cambia."""
    from dataclasses import replace
    from fondeos_sim.portfolio import Allocation, simulate_portfolio
    es, fs = EvalStrategy(day_target=1500), FundedStrategy(gordo_target=4000)
    a = course_plan()
    b = replace(a, id="curso_b", firm="otra")
    allocs = [Allocation(a, es, fs, parallel=2), Allocation(b, es, fs, parallel=2)]
    ind = simulate_portfolio(allocs, 100_000, 6, n_paths=2000, seed=1)
    cop = simulate_portfolio(allocs, 100_000, 6, n_paths=2000, seed=2, copy=copy, rho=1.0)
    per_eval = lambda r: (r.final - 100_000).sum() / r.evals.sum()   # noqa: E731
    assert per_eval(cop) == pytest.approx(per_eval(ind), rel=0.1)
    assert (cop.final - 100_000).std() > (ind.final - 100_000).std()


PLANS = Path(__file__).resolve().parents[1] / "plans"


def test_trades_per_day_cap_and_inactivity():
    from dataclasses import replace
    from fondeos_sim.portfolio import Allocation, simulate_portfolio
    plan = load_plan(PLANS / "lucid_flex_50k_dll.yaml")
    al = [Allocation(plan, EvalStrategy(1200, None, 10.0), FundedStrategy(2000, None, 150, 600), parallel=5)]
    free = simulate_portfolio(al, 20000, 3, n_paths=300, seed=1)
    capped = simulate_portfolio(al, 20000, 3, n_paths=300, seed=1, trades_per_day=2)
    assert capped.evals.mean() < 0.8 * free.evals.mean()
    assert capped.per_plan[plan.id]["cerradas por inactividad"] == 0   # 30 días: margen de sobra
    strict = [replace(al[0], plan=replace(plan, inactivity_days=2))]
    starved = simulate_portfolio(strict, 20000, 3, n_paths=300, seed=1, trades_per_day=1)
    assert starved.per_plan[plan.id]["cerradas por inactividad"] > 0


def test_session_trade_unresolved_keeps_zero_edge():
    """Con pocos contratos un objetivo lejano no siempre se resuelve en el día, pero la media sigue en 0."""
    rng = np.random.default_rng(11)
    n = 200_000
    bal = np.full(n, 50_000.0)
    out = {}
    for c in (1, 2, 4):
        pnl = bernoulli_trade(rng, bal, bal - 1e9, np.full(n, 2000.0), np.full(n, 8000.0), contracts=c)
        out[c] = 1 - ((pnl == 8000) | (pnl == -2000)).mean()
        assert pnl.mean() == pytest.approx(0, abs=4 * pnl.std() / n**0.5)
        assert pnl.min() >= -2000 and pnl.max() <= 8000
    assert out[1] > 0.25 and 0.04 < out[2] < 0.15 and out[4] < 0.02   # backtest NQ: 2 NQ ~11%, 4 NQ ~0%


def test_scaling_plan_contracts():
    lucid = load_plan(PLANS / "lucid_flex_50k_dll.yaml")
    assert list(lucid.funded.max_contracts(np.array([0, 999, 1000, 2500, -300]))) == [2, 2, 3, 4, 2]
    assert list(lucid.eval.max_contracts(np.array([0, 2000]))) == [4, 4]
