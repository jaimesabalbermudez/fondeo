"""Simulación de cartera: bankroll inicial, varias firmas, tiempo real y huecos limitados.

Todas las cuentas de todos los caminos se simulan a la vez, día a día, con el mismo motor que la
optimización (`eval_step`, `funded_step`):

- Compra evaluaciones mientras haya caja libre y huecos: como mucho `parallel` evaluaciones a la vez
  por plan, respetando los límites de la firma (evaluaciones, cuentas abiertas, compras por 30 días)
  y solo si queda hueco funded libre (plan y firma) contando las aprobadas que esperan.
- Una evaluación aprobada sin hueco funded (o sin cupo de activaciones del mes) espera al siguiente
  hueco si la firma lo permite (`hold_passed` del plan; si se desconoce, `queue_passed`) o se pierde.
- Suscripciones mensuales: se cobran cada 21 días de evaluación; sin caja para renovar, se pierde.
- La activación se reserva al comprar. Los payouts llegan `payout_delay` días después.
- `copy` decide qué cuentas copian el mismo trade cada día:
    "none"  - cada cuenta opera por su cuenta (independientes);
    "firms" - stacking entre firmas: la k-ésima cuenta abierta de cada firma copia el mismo trade;
    "all"   - todas las cuentas abiertas copian el mismo trade;
    "evals" - todas las evaluaciones abiertas (de todas las firmas) copian el mismo trade a la vez y las
              funded operan cada una el suyo. Las evaluaciones copiadas cuentan como un solo trade en
              `trades_per_day`, así que deja más tiempo para las funded.
  Las cuentas que copian comparten un factor común con correlación `rho` (cópula gaussiana): cada
  cuenta mantiene su probabilidad de acierto (su stop/objetivo), solo cambia cuánto se mueven juntas.
  rho = 1 es el caso extremo (mismo bracket); con stops/objetivos distintos sobre el mismo movimiento
  la correlación real ronda 0,1-0,8.
- `firm_failure_year`: probabilidad anual de que cada firma deje de pagar a todo el mundo (cierre,
  cambio de reglas, impagos). Desde ese día no se cobra nada pendiente de esa firma ni se compra más.
- Al llegar al horizonte se deja de comprar y se dejan correr las cuentas abiertas ("cierre").
- `trades_per_day`: trades que caben en una sesión (uno detrás de otro). Cada día operan como mucho
  esas cuentas por camino: primero las que están a punto de incumplir la regla de inactividad de su
  firma, después las que llevan más días paradas (desempate al azar). Una cuenta que supera el plazo
  de inactividad (`inactivity_days` del plan, días naturales -> 5/7 en días de trading) se pierde.
  None = todas las cuentas operan cada día.
"""

from dataclasses import dataclass

import numpy as np
from scipy.special import ndtr

from .engine import EvalState, EvalStrategy, FundedState, FundedStrategy, eval_step, funded_step
from .plan import Plan

MONTH = 21           # días de trading por mes
EVAL_HORIZON = 60    # días máximos de una evaluación sin límite propio
FUNDED_HORIZON = 120


@dataclass(frozen=True)
class Allocation:
    plan: Plan
    eval_strat: EvalStrategy | None
    funded_strat: FundedStrategy
    parallel: int = 1   # evaluaciones a la vez en este plan
    min_cash: float = 0.0            # solo se compra en este plan con caja libre >= min_cash
    max_cash: float = float("inf")   # ... y < max_cash (para cambiar de estrategia según el bankroll)
    label: str = ""

    @property
    def key(self) -> str:
        return self.label or self.plan.id


@dataclass
class PortfolioResult:
    days: np.ndarray            # eje temporal (días de trading)
    cash: np.ndarray            # (caminos, días) caja disponible cada día
    final: np.ndarray           # caja tras el cierre (sin comprar más y dejando correr las cuentas)
    ruined: np.ndarray          # bool por camino: sin cuentas abiertas y sin caja para comprar ninguna
    ruin_day: np.ndarray
    min_cash: np.ndarray
    spent: np.ndarray
    paid: np.ndarray
    evals: np.ndarray
    funded: np.ndarray
    per_plan: dict              # key -> medias por camino (evaluaciones, funded, gastado, cobrado, perdidas)


class _Pool:
    """Cuentas de una asignación: `slots` huecos por camino, aplanados como camino * slots + hueco."""

    def __init__(self, state, n_paths, slots):
        self.st, self.slots = state, slots
        self.occ = np.zeros((n_paths, slots), bool)

    def flat(self, paths, s):
        return paths * self.slots + s


def simulate_portfolio(allocs: list[Allocation], bankroll: float, months: float, n_paths: int = 2000,
                       copy: str = "none", rho: float = 1.0, payout_delay: int = 2, seed: int = 0,
                       queue_passed: bool = True, max_extra_days: int = 400,
                       firm_failure_year: float = 0.0, trades_per_day: int | None = None) -> PortfolioResult:
    rng = np.random.default_rng(seed)
    P, k = n_paths, len(allocs)
    horizon = int(round(months * MONTH))
    total_days = horizon + max_extra_days
    inf = 10**6

    firms = sorted({a.plan.firm for a in allocs})
    plan_ids = sorted({a.plan.id for a in allocs})
    firm_of = np.array([firms.index(a.plan.firm) for a in allocs])
    pid_of = np.array([plan_ids.index(a.plan.id) for a in allocs])

    def firm_limit(f, attr, fallback=None):
        vals = [getattr(a.plan, attr) or (fallback and getattr(a.plan, fallback)) for a in allocs
                if a.plan.firm == firms[f]]
        return min([v for v in vals if v] or [inf])

    n_firms = len(firms)
    cap_funded_firm = np.array([firm_limit(f, "firm_max_funded", "max_funded_accounts") for f in range(n_firms)])
    cap_open_firm = np.array([firm_limit(f, "firm_max_open") for f in range(n_firms)])
    cap_evals_firm = np.array([firm_limit(f, "firm_max_evals") for f in range(n_firms)])
    cap_buys_firm = np.array([firm_limit(f, "firm_max_purchases_30d") for f in range(n_firms)])
    cap_acts_firm = np.array([firm_limit(f, "firm_max_activations_30d") for f in range(n_firms)])
    cap_funded_pid = np.array([min(a.plan.max_funded_accounts or inf for a in allocs if a.plan.id == pid)
                               for pid in plan_ids])
    can_hold = [queue_passed if a.plan.hold_passed is None else a.plan.hold_passed for a in allocs]

    epools, fpools = [], []
    for j, a in enumerate(allocs):
        fslots = int(min(cap_funded_pid[pid_of[j]], cap_funded_firm[firm_of[j]], 50))
        epools.append(_Pool(EvalState(a.plan, P * a.parallel), P, a.parallel) if a.plan.eval else None)
        fpools.append(_Pool(FundedState(a.plan, a.funded_strat, P * fslots), P, fslots))
    denied = [np.zeros((P, fp.slots), bool) for fp in fpools]
    # días seguidos sin operar de cada cuenta y plazo de inactividad en días de trading
    e_idle = [np.zeros((P, ep.slots), int) if ep else None for ep in epools]
    f_idle = [np.zeros((P, fp.slots), int) for fp in fpools]
    idle_limit = np.array([a.plan.inactivity_days * 5 // 7 if a.plan.inactivity_days else inf for a in allocs])
    e_sel = [np.zeros((P, ep.slots), bool) if ep else None for ep in epools]
    f_sel = [np.zeros((P, fp.slots), bool) for fp in fpools]
    fresh = [np.zeros((P, fp.slots), bool) for fp in fpools]   # activadas hoy: operan desde mañana

    first_price = np.array([a.plan.costs.eval_price for a in allocs])
    retry_price = np.array([a.plan.costs.attempt_price() for a in allocs])
    monthly = [a.plan.costs.billing == "monthly" for a in allocs]
    activation = np.array([a.plan.costs.activation_fee for a in allocs])
    split = np.array([a.plan.funded.payout.split for a in allocs])
    p_deny = np.array([a.plan.p_payout_denial for a in allocs])

    cash = np.full(P, float(bankroll))
    committed = np.zeros(P)
    arrivals = np.zeros((P, n_firms, total_days + payout_delay + 2))   # payouts pendientes por firma
    daily_hazard = 1 - (1 - firm_failure_year) ** (1 / 252)
    fail_day = (rng.geometric(daily_hazard, (P, n_firms)) - 1 if daily_hazard > 0
                else np.full((P, n_firms), 10**9))
    n_eval, n_fund, n_queue, bought = (np.zeros((P, k), int) for _ in range(4))
    buys_log = np.zeros((P, n_firms, total_days + 1), int)
    acts_log = np.zeros((P, n_firms, total_days + 1), int)
    stats = np.zeros((k, 6))   # evaluaciones, funded, gastado, cobrado, aprobadas perdidas, cerradas por inactividad
    spent, paid, n_evals_tot, n_funded_tot = np.zeros(P), np.zeros(P), np.zeros(P), np.zeros(P)
    cash_hist = np.zeros((P, horizon + 1))
    ruin_day = np.full(P, -1)
    min_cash = cash.copy()

    def firm_sum(arr, f):
        return arr[:, firm_of == f].sum(axis=1)

    def pid_sum(arr, q):
        return arr[:, pid_of == q].sum(axis=1)

    def window(log, f, day):
        return log[:, f, max(day - MONTH + 1, 0):day + 1].sum(axis=1)

    def funded_room(j, day):
        f, q = firm_of[j], pid_of[j]
        return ((pid_sum(n_fund, q) + 1 <= cap_funded_pid[q]) & (firm_sum(n_fund, f) + 1 <= cap_funded_firm[f])
                & (window(acts_log, f, day) + 1 <= cap_acts_firm[f]))

    def pay(m, j, amount):
        amount = np.where(m, amount, 0.0)
        cash[:] -= amount
        spent[:] += amount
        stats[j, 2] += amount.sum()

    def start_funded(m, j, day):
        """Activa una cuenta funded del plan j en los caminos `m` (hay hueco garantizado)."""
        fp, need = fpools[j], m.copy()
        for s in range(fp.slots):
            take = need & ~fp.occ[:, s]
            if take.any():
                paths = np.flatnonzero(take)
                fp.st.reset(fp.flat(paths, s))
                fp.occ[paths, s] = True
                fresh[j][paths, s] = True
                f_idle[j][paths, s] = 0
                denied[j][paths, s] = rng.random(paths.size) < p_deny[j]
                need &= ~take
        pay(m, j, activation[j])
        committed[m] -= activation[j]
        n_fund[m, j] += 1
        n_funded_tot[m] += 1
        stats[j, 1] += m.sum()
        acts_log[m, firm_of[j], day] += 1

    def drain_queues(day):
        for j in range(k):
            for _ in range(int(n_queue[:, j].max(initial=0))):
                m = (n_queue[:, j] > 0) & funded_room(j, day)
                if not m.any():
                    break
                n_queue[m, j] -= 1
                start_funded(m, j, day)

    def can_buy(j, day):
        a, f, q = allocs[j], firm_of[j], pid_of[j]
        free = cash - committed
        price = np.where(bought[:, j] < a.parallel, first_price[j], retry_price[j])
        open_firm = firm_sum(n_eval, f) + firm_sum(n_fund, f) + firm_sum(n_queue, f)
        ok = ((ruin_day < 0) & (fail_day[:, f] > day) & (a.min_cash <= free) & (free < a.max_cash) & (free >= price + activation[j])
              & (n_eval[:, j] + 1 <= a.parallel)
              & (firm_sum(n_eval, f) + 1 <= cap_evals_firm[f])
              & (open_firm + 1 <= cap_open_firm[f])
              & (pid_sum(n_fund, q) + pid_sum(n_queue, q) + 1 <= cap_funded_pid[q])
              & (firm_sum(n_fund, f) + firm_sum(n_queue, f) + 1 <= cap_funded_firm[f])
              & (window(buys_log, f, day) + 1 <= cap_buys_firm[f]))
        return ok, price

    def buy(day):
        for j, a in enumerate(allocs):
            ep = epools[j]
            if ep is None:
                continue
            for s in range(a.parallel):
                ok, price = can_buy(j, day)
                m = ok & ~ep.occ[:, s]
                if not m.any():
                    continue
                paths = np.flatnonzero(m)
                ep.st.reset(ep.flat(paths, s))
                ep.occ[paths, s] = True
                e_idle[j][paths, s] = 0
                pay(m, j, price)
                committed[m] += activation[j]
                bought[m, j] += 1
                n_eval[m, j] += 1
                n_evals_tot[m] += 1
                stats[j, 0] += m.sum()
                buys_log[m, firm_of[j], day] += 1

    def uniforms():
        """Uniformes de hoy por (tipo, asignación) -> (caminos, huecos); vacío si las cuentas son independientes."""
        if copy == "none" or rho <= 0:
            return {}
        if copy == "evals":   # un factor común por camino para todas las evaluaciones; funded independientes
            z0 = rng.standard_normal((P, 1))
            return {("e", j): ndtr(np.sqrt(rho) * z0 + np.sqrt(1 - rho) * rng.standard_normal((P, ep.slots)))
                    for j, ep in enumerate(epools) if ep is not None}
        groups = []
        for f in range(n_firms):
            blocks = [(kind, j, pool) for j in np.flatnonzero(firm_of == f)
                      for kind, pool in (("e", epools[j]), ("f", fpools[j])) if pool is not None]
            occ = np.concatenate([pool.occ for _, _, pool in blocks], axis=1)
            # "firms": la k-ésima cuenta abierta de cada firma copia el trade k; "all": todas el mismo
            rank = np.cumsum(occ, axis=1) - 1 if copy == "firms" else np.zeros(occ.shape, int)
            groups.append((blocks, occ, rank))
        width = max(g[1].shape[1] for g in groups)
        common = rng.standard_normal((P, width))
        out = {}
        for blocks, occ, rank in groups:
            z = (np.sqrt(rho) * np.take_along_axis(common, np.clip(rank, 0, width - 1), axis=1)
                 + np.sqrt(1 - rho) * rng.standard_normal(occ.shape))
            u, c = ndtr(z), 0
            for kind, j, pool in blocks:
                out[(kind, j)] = u[:, c:c + pool.slots]
                c += pool.slots
        return out

    def step_evals(j, a, day, U):
        ep = epools[j]
        if ep is None or not ep.occ.any():
            return
        paths, slots = np.nonzero(ep.occ)
        idx = ep.flat(paths, slots)
        tr = e_sel[j][paths, slots]
        if tr.any():
            eval_step(ep.st, a.eval_strat, idx[tr], rng,
                      U[("e", j)][paths[tr], slots[tr]] if ("e", j) in U else None)
        st = ep.st
        passed = st.passed[idx] & tr
        expired = e_idle[j][paths, slots] > idle_limit[j]
        failed = ~passed & (~st.alive[idx] | (st.days[idx] >= EVAL_HORIZON) | expired)
        stats[j, 5] += expired.sum()
        if monthly[j]:   # renovación de la suscripción
            due = ~passed & ~failed & (st.days[idx] % MONTH == 0)
            if due.any():
                price = retry_price[j]
                renew = due & ((cash - committed)[paths] >= price)
                failed |= due & ~renew
                np.add.at(cash, paths[renew], -price)
                np.add.at(spent, paths[renew], price)
                stats[j, 2] += price * renew.sum()
        done = passed | failed
        if not done.any():
            return
        ep.occ[paths[done], slots[done]] = False
        np.subtract.at(n_eval[:, j], paths[done], 1)
        np.subtract.at(committed, paths[failed], activation[j])
        pp = paths[passed]
        while pp.size:   # aprobadas de una en una por camino, para respetar los huecos
            uniq, first = np.unique(pp, return_index=True)
            pp = np.delete(pp, first)
            m = np.zeros(P, bool)
            m[uniq] = True
            room = m & funded_room(j, day)
            if room.any():
                start_funded(room, j, day)
            wait = m & ~room
            if can_hold[j]:
                n_queue[wait, j] += 1
            else:
                committed[wait] -= activation[j]
                stats[j, 4] += wait.sum()

    def step_funded(j, day, U):
        fp = fpools[j]
        live = fp.occ & ~fresh[j]
        trading = live & f_sel[j]
        fresh[j][:] = False
        if not live.any():
            return
        w, amount = np.zeros(0, int), np.zeros(0)
        if trading.any():
            tp, ts = np.nonzero(trading)
            w, amount = funded_step(fp.st, fp.flat(tp, ts), rng, U[("f", j)][tp, ts] if ("f", j) in U else None)
        paths, slots = np.nonzero(live)
        idx = fp.flat(paths, slots)
        if w.size:
            wp, ws = np.divmod(w, fp.slots)
            ok = ~denied[j][wp, ws]
            net = amount[ok] * split[j]
            np.add.at(arrivals[:, firm_of[j], day + payout_delay], wp[ok], net)
            stats[j, 3] += net.sum()
        expired = f_idle[j][paths, slots] > idle_limit[j]
        stats[j, 5] += expired.sum()
        done = ~fp.st.active[idx] | (fp.st.days[idx] >= FUNDED_HORIZON) | expired
        if done.any():
            fp.occ[paths[done], slots[done]] = False
            np.subtract.at(n_fund[:, j], paths[done], 1)

    def select():
        """Marca en e_sel / f_sel las cuentas que operan hoy y actualiza los días sin operar."""
        blocks = [(e_sel[j], e_idle[j], epools[j].occ, j) for j in range(k) if epools[j] is not None]
        blocks += [(f_sel[j], f_idle[j], fpools[j].occ & ~fresh[j], j) for j in range(k)]
        for sel, _, occ, _ in blocks:
            sel[:] = occ
        if trades_per_day is not None:
            n_e = sum(1 for ep in epools if ep is not None)
            cap = np.full(P, trades_per_day)
            ranked = range(len(blocks))
            if copy == "evals":   # todas las evaluaciones operan, como un único trade copiado
                any_eval = np.zeros(P, bool)
                for _, _, occ, _ in blocks[:n_e]:
                    any_eval |= occ.any(axis=1)
                cap -= any_eval
                ranked = range(n_e, len(blocks))
            cand = [(np.nonzero(blocks[b][2]), b) for b in ranked]
            path = np.concatenate([pp for (pp, _), _ in cand])
            if path.size:
                idle = np.concatenate([blocks[b][1][pp, ss] for (pp, ss), b in cand])
                lim = np.concatenate([np.full(pp.size, idle_limit[blocks[b][3]]) for (pp, _), b in cand])
                urgent = idle + 1 >= lim
                score = -idle - 1e4 * urgent + 0.5 * rng.random(path.size)   # menor = antes
                order = np.lexsort((score, path))
                first = np.searchsorted(path[order], path[order], side="left")
                rank = np.empty(path.size, int)
                rank[order] = np.arange(path.size) - first
                keep = rank < cap[path]
                c = 0
                for (pp, ss), b in cand:
                    blocks[b][0][pp, ss] = keep[c:c + pp.size]
                    c += pp.size
        for sel, idle, occ, _ in blocks:
            idle[sel] = 0
            idle[occ & ~sel] += 1

    for day in range(total_days):
        failed_firm = fail_day <= day
        arrivals[:, :, day][failed_firm] = 0.0   # la firma ya no paga
        today = arrivals[:, :, day].sum(axis=1)
        cash += today
        paid += today
        drain_queues(day)
        if day <= horizon:
            buy(day)
            # ruina: tras intentar comprar no queda nada abierto ni ningún payout pendiente
            open_any = (n_eval.sum(1) + n_fund.sum(1) + n_queue.sum(1)) > 0
            stuck = (ruin_day < 0) & ~open_any & ~(arrivals[:, :, day + 1:].sum(axis=(1, 2)) > 0)
            ruin_day[stuck] = day
        U = uniforms()
        select()
        for j, a in enumerate(allocs):
            step_evals(j, a, day, U)
            step_funded(j, day, U)

        open_any = (n_eval.sum(1) + n_fund.sum(1) + n_queue.sum(1)) > 0
        pending = arrivals[:, :, day + 1:].sum(axis=(1, 2)) > 0
        if day <= horizon:
            cash_hist[:, day] = cash
            np.minimum(min_cash, cash, out=min_cash)
        elif not open_any.any() and not pending.any():
            break

    keys = ("evaluaciones", "funded", "gastado", "cobrado", "aprobadas perdidas", "cerradas por inactividad")
    per_plan = {a.key: dict(zip(keys, stats[j] / P)) for j, a in enumerate(allocs)}
    return PortfolioResult(days=np.arange(horizon + 1), cash=cash_hist, final=cash, ruined=ruin_day >= 0,
                           ruin_day=ruin_day, min_cash=min_cash, spent=spent, paid=paid, evals=n_evals_tot,
                           funded=n_funded_tot, per_plan=per_plan)


def bankroll_for_ruin(allocs: list[Allocation], target: float = 0.05, months: float = 6, n_paths: int = 1000,
                      lo: float = 100.0, hi: float = 200_000.0, iters: int = 12, **kw) -> tuple[float, float]:
    """Bankroll mínimo con P(ruina) <= target (bisección en escala log, mismas semillas en cada prueba).

    Devuelve (bankroll, P(ruina) con ese bankroll); bankroll = inf si ni con `hi` se consigue.
    """
    ruin = lambda b: simulate_portfolio(allocs, b, months, n_paths=n_paths, seed=11, **kw).ruined.mean()  # noqa: E731
    r_hi = ruin(hi)
    if r_hi > target:
        return float("inf"), r_hi
    for _ in range(iters):
        mid = float(np.sqrt(lo * hi))
        r = ruin(mid)
        if r <= target:
            hi, r_hi = mid, r
        else:
            lo = mid
        if hi / lo < 1.05:
            break
    return hi, r_hi
