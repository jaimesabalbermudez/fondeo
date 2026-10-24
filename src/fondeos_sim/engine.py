"""Simulación vectorizada (n cuentas en paralelo, día a día) de evaluación y fase funded.

Supuestos de la v1:
- Un trade por día (stop/TP fijos). Es lo que hace el plan del curso y lo que mejor encaja con
  límites diarios; varios trades por día equivalen a un trade con otro stop/TP en un paseo aleatorio.
- Los payouts se piden en cuanto se cumplen los requisitos, por el máximo permitido.
- Al llegar al máximo de payouts la cuenta sale de la simulación (pasa a live o se cierra); el
  colchón que quede dentro no se cuenta como valor.
"""

from dataclasses import dataclass

import numpy as np

from .market import bernoulli_trade, intraday_trade
from .plan import EvalRules, FundedRules, Plan, PhaseRules


@dataclass(frozen=True)
class EvalStrategy:
    day_target: float            # profit buscado cada día (se recorta a lo que falte)
    risk: float | None = None    # stop en $; None = todo el margen hasta el suelo
    friction: float = 0.0
    edge: float = 0.0


@dataclass(frozen=True)
class FundedStrategy:
    gordo_target: float = 0.0    # profit a buscar antes de empezar a sumar días (0 = sin día gordo)
    gordo_risk: float | None = None
    grind_target: float = 150.0  # profit buscado cada día tras el día gordo
    grind_risk: float = 600.0
    friction_gordo: float = 0.0
    friction_grind: float = 0.0
    edge: float = 0.0
    cycle_gordo: float = 0.0     # tras cada payout, profit a buscar de golpe antes de volver a sumar días


def _lock_level(rules: PhaseRules, start: float) -> float:
    return start + rules.lock_offset if rules.lock_offset is not None else np.inf


def _dll(rules: PhaseRules, start, peak):
    """DLL de cada cuenta según su mayor balance EOD (fijo, o LucidScale por encima del trail inicial)."""
    if rules.dll is None:
        return None
    if rules.dll_scale_pct is None:
        return np.full(peak.shape, float(rules.dll))
    trail = start + rules.mll + (rules.lock_offset or 0)
    return np.where(peak >= trail, rules.dll_scale_pct * (peak - start), rules.dll)


def _trade(rng, rules: PhaseRules, start, bal, floor, risk, target, friction, edge, u=None, peak=None):
    """Devuelve (pnl, floor) para las cuentas dadas, según el tipo de drawdown."""
    dll = _dll(rules, start, bal if peak is None else peak)
    if rules.drawdown == "intraday":
        if edge:
            raise NotImplementedError("edge != 0 no está soportado con drawdown intradía")
        if dll is not None:
            risk = np.minimum(risk, dll - friction)
        lock = np.full(bal.shape, _lock_level(rules, start))
        return intraday_trade(rng, bal, floor, risk, target, friction, rules.mll, lock, u)
    return bernoulli_trade(rng, bal, floor, risk, target, friction, edge, dll, u), floor


def _eod_trail(rules: PhaseRules, start, bal, floor):
    if rules.drawdown == "static":
        return floor
    return np.maximum(floor, np.minimum(bal - rules.mll, _lock_level(rules, start)))


class EvalState:
    """Estado de n cuentas en evaluación. `reset` reinicia las cuentas indicadas (cuenta nueva)."""

    def __init__(self, plan: Plan, n: int):
        self.plan, self.start = plan, float(plan.start_balance)
        self.bal, self.floor, self.max_day, self.peak = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
        self.alive, self.passed = np.zeros(n, bool), np.zeros(n, bool)
        self.days = np.zeros(n, int)
        self.reset(np.arange(n))

    def reset(self, idx):
        self.bal[idx] = self.start
        self.peak[idx] = self.start
        self.floor[idx] = self.start - self.plan.eval.mll
        self.max_day[idx] = 0
        self.alive[idx] = True
        self.passed[idx] = False
        self.days[idx] = 0


def eval_step(st: EvalState, strat: EvalStrategy, idx, rng, u=None):
    """Un día de trading para las cuentas `idx` (vivas y sin aprobar). `u`: uniformes por cuenta."""
    r: EvalRules = st.plan.eval
    start, bal, floor, max_day = st.start, st.bal, st.floor, st.max_day
    profit = bal[idx] - start
    need = r.profit_target - profit
    if r.consistency:
        need = np.maximum(need, max_day[idx] / r.consistency - profit)
    trading = need > 1e-9   # si solo faltan días mínimos, se cuenta un día sin riesgo
    pnl = np.zeros(idx.size)
    fl = floor[idx]
    if trading.any():
        t = idx[trading]
        target = np.minimum(strat.day_target, need[trading])
        risk = np.full(t.size, np.inf if strat.risk is None else strat.risk)
        pnl[trading], fl[trading] = _trade(rng, r, start, bal[t], floor[t], risk, target, strat.friction,
                                           strat.edge, None if u is None else u[trading], st.peak[t])
    bal[idx] += pnl
    st.peak[idx] = np.maximum(st.peak[idx], bal[idx])
    st.days[idx] += 1
    died = bal[idx] <= fl + 1e-9
    st.alive[idx[died]] = False
    floor[idx] = _eod_trail(r, start, bal[idx], fl)
    max_day[idx] = np.maximum(max_day[idx], pnl)

    profit = bal[idx] - start
    ok = (~died) & (profit >= r.profit_target - 1e-9) & (st.days[idx] >= r.min_days)
    if r.consistency:
        ok &= max_day[idx] <= r.consistency * profit + 1e-6
    st.passed[idx[ok]] = True
    if r.max_days:
        st.alive[idx[~ok & (st.days[idx] >= r.max_days)]] = False


def simulate_eval(plan: Plan, strat: EvalStrategy, n: int, rng, horizon: int = 60,
                  return_paths: bool = False) -> dict:
    st = EvalState(plan, n)
    for _ in range(horizon):
        idx = np.flatnonzero(st.alive & ~st.passed)
        if not idx.size:
            break
        eval_step(st, strat, idx, rng)

    passed, days = st.passed, st.days
    months = np.ceil(days / 21).clip(min=1)
    out = dict(
        p_pass=passed.mean(),
        days=days.mean(),
        days_if_pass=days[passed].mean() if passed.any() else np.nan,
        months_billed=months.mean(),
    )
    if return_paths:
        out["paths"] = dict(passed=passed, days=days)
    return out


class FundedState:
    """Estado de n cuentas funded (balance, suelo, ciclo de payout...)."""

    def __init__(self, plan: Plan, strat: FundedStrategy, n: int):
        self.plan, self.strat, self.start = plan, strat, float(plan.start_balance)
        f = lambda dtype=float: np.zeros(n, dtype)   # noqa: E731
        self.bal, self.floor, self.gordo_level, self.gross, self.trapped = f(), f(), f(), f(), f()
        self.cyc_start, self.cyc_max_day, self.peak = f(), f(), f()   # peak: mayor balance EOD
        self.alive, self.closed, self.gordo_done = f(bool), f(bool), f(bool)
        self.payouts, self.days, self.first_payout_day, self.greens, self.cyc_days = f(int), f(int), f(int), f(int), f(int)
        self.reset(np.arange(n))

    def reset(self, idx):
        start, s = self.start, self.strat
        self.bal[idx] = start
        self.peak[idx] = start
        self.floor[idx] = start - self.plan.funded.mll
        self.gordo_level[idx] = start + s.gordo_target   # balance que cierra la fase de día gordo
        self.gordo_done[idx] = s.gordo_target <= 0
        self.alive[idx] = True
        self.closed[idx] = False
        self.trapped[idx] = 0     # colchón que queda dentro al cerrarse la cuenta por máximo de payouts
        self.gross[idx] = 0
        self.payouts[idx] = 0
        self.days[idx] = 0
        self.first_payout_day[idx] = -1
        self.greens[idx] = 0
        self.cyc_days[idx] = 0
        self.cyc_start[idx] = start
        self.cyc_max_day[idx] = 0

    @property
    def active(self):
        return self.alive & ~self.closed


def funded_step(st: FundedState, idx, rng, u=None):
    """Un día de trading para las cuentas `idx` (activas). Devuelve (cuentas, importe bruto) de los payouts."""
    r: FundedRules = st.plan.funded
    po, strat, start = r.payout, st.strat, st.start
    bal, floor = st.bal, st.floor
    g = ~st.gordo_done[idx]
    target = np.where(g, st.gordo_level[idx] - bal[idx], strat.grind_target)
    risk = np.where(g, np.inf if strat.gordo_risk is None else strat.gordo_risk, strat.grind_risk)
    pnl = np.zeros(idx.size)
    fl = floor[idx]
    for mask, f in ((g, strat.friction_gordo), (~g, strat.friction_grind)):
        if mask.any():
            pnl[mask], fl[mask] = _trade(rng, r, start, bal[idx[mask]], floor[idx[mask]], risk[mask],
                                         target[mask], f, strat.edge, None if u is None else u[mask],
                                         st.peak[idx[mask]])
    bal[idx] += pnl
    st.peak[idx] = np.maximum(st.peak[idx], bal[idx])
    st.days[idx] += 1
    died = bal[idx] <= fl + 1e-9
    st.alive[idx[died]] = False
    floor[idx] = _eod_trail(r, start, bal[idx], fl)
    live = idx[~died]
    pnl = pnl[~died]
    st.gordo_done[live] |= bal[live] >= st.gordo_level[live] - 1e-9

    st.greens[live] += pnl >= po.green_min - 1e-9
    st.cyc_days[live] += 1
    st.cyc_max_day[live] = np.maximum(st.cyc_max_day[live], pnl)

    # payout
    profit = bal[live] - start
    cyc_profit = bal[live] - st.cyc_start[live]
    ok = (st.greens[live] >= po.min_green_days) & (st.cyc_days[live] >= po.min_trading_days)
    ok &= cyc_profit >= po.min_cycle_profit
    if po.consistency:
        ok &= st.cyc_max_day[live] <= po.consistency * cyc_profit + 1e-6
    caps = np.asarray(po.max_amount)
    cap = caps[np.minimum(st.payouts[live], caps.size - 1)]
    amount = np.minimum(cap, profit - po.buffer)
    if po.pct_of_profit is not None:
        amount = np.minimum(amount, po.pct_of_profit * profit)
    ok &= amount >= max(po.min_amount, 1e-9)
    w, amount = live[ok], amount[ok]
    if w.size:
        bal[w] -= amount
        st.gross[w] += amount
        first = w[st.payouts[w] == 0]
        st.first_payout_day[first] = st.days[first]
        st.payouts[w] += 1
        st.gordo_done[w] = strat.cycle_gordo <= 0
        st.gordo_level[w] = bal[w] + strat.cycle_gordo
        st.greens[w] = 0
        st.cyc_days[w] = 0
        st.cyc_max_day[w] = 0
        st.cyc_start[w] = bal[w]
        if r.floor_after_payout is not None:
            floor[w] = start + r.floor_after_payout
        if po.max_payouts is not None:
            done = w[st.payouts[w] >= po.max_payouts]
            st.closed[done] = True
            st.trapped[done] = bal[done] - floor[done]
    return w, amount


def simulate_funded(plan: Plan, strat: FundedStrategy, n: int, rng, horizon: int = 120,
                    return_paths: bool = False) -> dict:
    st = FundedState(plan, strat, n)
    po = plan.funded.payout
    events = []   # (cuenta, día, importe bruto) de cada payout
    for day in range(1, horizon + 1):
        idx = np.flatnonzero(st.active)
        if not idx.size:
            break
        w, amount = funded_step(st, idx, rng)
        if return_paths and w.size:
            events.append((w, np.full(w.size, day), amount))

    payouts, days, fpd = st.payouts, st.days, st.first_payout_day
    out = dict(
        gross=st.gross.mean(),
        net=st.gross.mean() * po.split,
        p_payout=(payouts > 0).mean(),
        payouts_mean=payouts.mean(),
        payout_dist=np.bincount(np.minimum(payouts, 6), minlength=7) / n,   # el último es "6 o más"
        days=days.mean(),
        days_first_payout=fpd[fpd > 0].mean() if (fpd > 0).any() else np.nan,
        alive_at_horizon=st.active.mean(),
        residual=np.where(st.active, st.bal - st.floor, 0.0).mean(),
        trapped=st.trapped.mean(),
    )
    if return_paths:
        acc, dd, amt = ([np.concatenate(x) for x in zip(*events)] if events
                        else (np.array([], int), np.array([], int), np.array([])))
        out["paths"] = dict(days=days, pay_account=acc, pay_day=dd, pay_amount=amt * po.split)
    return out
