"""Plan del día: qué hacer hoy en cada cuenta según su estado (`cuentas.yaml`).

Aplica la forma de operar recomendada (`recommended.py`) a las cuentas reales:
- Evaluaciones: el trade de la estrategia optimizada (objetivo recortado a lo que falte, consistencia).
- Funded: primero el día gordo (prudente si se activó con poca caja) y después días verdes hasta el payout.
- Orden del día (13:00-17:00 en España): días verdes en premercado, evaluaciones desde la apertura
  (todas a la vez si la caja libre >= `copy_evals_from`) y los días gordos al final, con stop y TP puestos.
- Como mucho `trades_per_day` trades: primero las cuentas a punto de incumplir la inactividad, después
  las que llevan más días paradas.

El estado se actualiza con los mismos cálculos que el motor (suelo EOD, consistencia, días verdes,
payouts), así que el plan de mañana sale de lo que pasó hoy:

    uv run fondeos-hoy                        # plan de hoy
    uv run fondeos-hoy compra lucid 5         # añade 5 evaluaciones (precio con código; --precio para otro)
    uv run fondeos-hoy resultado lucid-1 1210 # P&L neto de hoy (negativo si pierde)
    uv run fondeos-hoy retiro tradeify-2      # payout pedido (por defecto el máximo permitido)
    uv run fondeos-hoy cobro 1800             # ha llegado dinero de un payout
    uv run fondeos-hoy caja 5000              # fija la caja libre

Los datos son personales y no van al repo: viven en la carpeta `FONDEOS_DATOS` si está definida; si no,
en `OneDrive/Fondeo` (sincronizada entre ordenadores) cuando existe OneDrive; si no, en la raíz del repo.

Contabilidad (`contabilidad/` dentro de esa carpeta): cada compra, gasto y cobro queda registrado con su
importe en $ y, si se indica, en € (lo que cargó el banco). Los tickets se copian a
`contabilidad/tickets/AÑO/` y `resumen` saca el gastado frente a lo cobrado del año fiscal:

    uv run fondeos-hoy compra lucid 1 --eur 59.80 --ticket ~/Downloads/recibo.pdf
    uv run fondeos-hoy ticket lucid-3 ~/Downloads/recibo.pdf   # adjunta el ticket a una compra ya hecha
    uv run fondeos-hoy gasto VPS octubre --usd 35 --eur 32.10 --ticket factura.pdf
    uv run fondeos-hoy cobro 1800 --eur 1655.20 --cuenta lucid-1
    uv run fondeos-hoy resumen 2026           # -> contabilidad/2026/resumen.md y movimientos.csv
"""

import argparse
import csv
import math
import os
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import yaml

from . import recommended as rec
from .cache import ROOT
from .engine import EvalStrategy, FundedStrategy, _dll
from .market import NQ_POINT


def data_dir() -> Path:
    """Carpeta de los datos personales (estado, contabilidad, planes guardados)."""
    if os.environ.get("FONDEOS_DATOS"):
        return Path(os.environ["FONDEOS_DATOS"]).expanduser()
    if os.environ.get("OneDrive") and Path(os.environ["OneDrive"]).is_dir():
        return Path(os.environ["OneDrive"]) / "Fondeo"
    return ROOT


DATA = data_dir()
STATE = DATA / "cuentas.yaml"
LEDGER = DATA / "contabilidad"
PLANS_OUT = DATA / "planes"

# tiempo medio hasta TP o SL en cada franja (reports/horario.txt), para estimar si cabe el día
MINUTES = {"verde": 18, "eval": 15, "gordo": 28}
PREMARKET_MIN, OPEN_MIN = 140, 90   # 13:00-15:25 sin el dato de las 14:30 / 15:30-17:00


def default_strats(plan_id: str):
    r = rec.optimized(plan_id)
    return r.plan, r.eval_strat, r.funded_strat


def resolve_plan(name: str, cfg: rec.Config = rec.DEFAULT) -> str:
    """'lucid' -> 'lucid_flex_50k_dll' (por prefijo entre los planes de la cartera)."""
    ids = [s.plan_id for s in cfg.slots]
    hits = [i for i in ids if i == name] or [i for i in ids if i.startswith(name.lower())]
    if len(hits) != 1:
        raise SystemExit(f"Plan '{name}' ambiguo o desconocido; usa uno de: {', '.join(ids)}")
    return hits[0]


def load(path: Path = STATE) -> dict:
    if not path.exists():
        return {"caja": 0.0, "por_cobrar": 0.0, "cuentas": [], "compras": [], "gastos": [], "retiros": [],
                "cobros": []}
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    d.setdefault("caja", 0.0)
    d.setdefault("por_cobrar", 0.0)
    for k in ("cuentas", "compras", "gastos", "retiros", "cobros"):
        d.setdefault(k, [])
    return d


def save(state: dict, path: Path = STATE):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(state, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _date(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x))


def _start(acc, plan) -> float:
    return float(acc.get("inicio", plan.start_balance))


@dataclass
class Trade:
    acc: dict
    kind: str          # verde | eval | gordo | minimo
    contracts: float   # NQ (0,5 = 5 MNQ)
    target: float      # $ netos buscados
    risk: float        # $ que se arriesgan (sin comisiones)
    friction: float
    tp_pts: float
    sl_pts: float
    p_win: float
    urgent: bool = False
    idle: int = 0

    @property
    def size(self) -> str:
        if self.contracts < 1:
            return f"{self.contracts * 10:g} MNQ"
        return f"{self.contracts:g} NQ"


def bracket(acc, kind, bal, floor, risk, target, friction, dll, contracts) -> Trade:
    """TP y stop en puntos para ganar `target` netos; el stop nunca toca el suelo."""
    margin = bal - floor - friction
    r = margin if risk is None else min(risk, margin)
    if dll is not None:
        r = min(r, dll - friction)
    r = max(r, 0.0)
    tp = target + friction
    pv = contracts * NQ_POINT
    sl_pts = math.floor(r / pv * 4) / 4
    if r >= margin - 1e-9:   # stop en el suelo: 1 punto de margen para no tocarlo con el deslizamiento
        sl_pts -= 1
    return Trade(acc, kind, contracts, target, r, friction, math.ceil(tp / pv * 4) / 4, max(sl_pts, 0.25),
                 r / (r + tp) if r + tp > 0 else 0.0)


def eval_need(acc, plan) -> float:
    """Profit que falta para aprobar (objetivo y consistencia); <= 0 = ya cumple."""
    r, start = plan.eval, _start(acc, plan)
    profit = acc["balance"] - start
    need = r.profit_target - profit
    if r.consistency:
        need = max(need, acc.get("mejor_dia", 0.0) / r.consistency - profit)
    return need


def eval_trade(acc, plan, es: EvalStrategy) -> Trade | None:
    r, start = plan.eval, _start(acc, plan)
    need = eval_need(acc, plan)
    if need <= 1e-9:
        if acc.get("dias", 0) >= r.min_days:
            return None
        return Trade(acc, "minimo", 0.1, 0, 0, 0, 0, 0, 1.0)   # solo falta contar días
    c = float(min(es.contracts, r.max_contracts(acc["balance"] - start)))
    return bracket(acc, "eval", acc["balance"], acc["suelo"], es.risk, min(es.day_target, need), es.friction,
                   r.dll, c)


def funded_strategy(acc, fs: FundedStrategy, cfg: rec.Config = rec.DEFAULT) -> FundedStrategy:
    return rec.prudent_strategy(fs, cfg) if acc.get("modo") == "prudente" else fs


def funded_trade(acc, plan, fs: FundedStrategy) -> Trade:
    r, start, bal = plan.funded, _start(acc, plan), acc["balance"]
    cap = float(r.max_contracts(bal - start))
    dll = _dll(r, start, np.array([acc.get("maximo", bal)]))
    dll = None if dll is None else float(dll[0])
    if not acc.get("gordo_hecho", False):
        c = cap if np.isfinite(cap) else 1.0
        return bracket(acc, "gordo", bal, acc["suelo"], fs.gordo_risk, acc["nivel_gordo"] - bal,
                       fs.friction_gordo * c, dll, c)
    c = min(fs.grind_contracts, cap)
    return bracket(acc, "verde", bal, acc["suelo"], fs.grind_risk, fs.grind_target, fs.friction_grind, dll, c)


def payout_due(acc, plan) -> float:
    """Importe bruto del payout que se puede pedir ahora (0 si aún no)."""
    po, start, bal = plan.funded.payout, _start(acc, plan), acc["balance"]
    cyc_profit = bal - acc.get("inicio_ciclo", start)
    if (acc.get("dias_verdes", 0) < po.min_green_days or acc.get("dias_ciclo", 0) < po.min_trading_days
            or cyc_profit < po.min_cycle_profit):
        return 0.0
    if po.consistency and acc.get("mejor_dia_ciclo", 0.0) > po.consistency * cyc_profit + 1e-6:
        return 0.0
    profit = bal - start
    amount = min(po.cap(acc.get("payouts", 0)), profit - po.buffer)
    if po.pct_of_profit is not None:
        amount = min(amount, po.pct_of_profit * profit)
    return amount if amount >= max(po.min_amount, 1e-9) else 0.0


def _trail(rules, start, bal, floor) -> float:
    if rules.drawdown == "static":
        return floor
    lock = start + rules.lock_offset if rules.lock_offset is not None else math.inf
    return max(floor, min(bal - rules.mll, lock))


def new_eval(acc_id, plan, today) -> dict:
    start = float(plan.start_balance)
    return {"id": acc_id, "plan": plan.id, "fase": "eval", "balance": start, "suelo": start - plan.eval.mll,
            "maximo": start, "mejor_dia": 0.0, "dias": 0, "comprada": today.isoformat(),
            "ultimo_trade": today.isoformat()}


def activate_funded(plan, fs: FundedStrategy, state, today, cfg: rec.Config = rec.DEFAULT) -> dict:
    """La evaluación aprobada pasa a funded. Con poca caja juega prudente toda la vida de la cuenta."""
    slot = next(s for s in cfg.slots if s.plan_id == plan.id)
    modo = "prudente" if state["caja"] < cfg.prudent_below and slot.from_cash < cfg.prudent_below else "optimo"
    s = funded_strategy({"modo": modo}, fs, cfg)
    start = float(plan.start_balance)
    return {"fase": "funded", "modo": modo, "balance": start, "suelo": start - plan.funded.mll, "maximo": start,
            "nivel_gordo": start + s.gordo_target, "gordo_hecho": s.gordo_target <= 0, "dias_verdes": 0,
            "dias_ciclo": 0, "mejor_dia_ciclo": 0.0, "inicio_ciclo": start, "payouts": 0,
            "activada": today.isoformat(), "ultimo_trade": today.isoformat()}


def record_result(acc, pnl, state, today, strats=default_strats, cfg: rec.Config = rec.DEFAULT) -> str:
    """Registra el P&L neto de hoy (mismas reglas que engine.eval_step / funded_step)."""
    plan, es, fs = strats(acc["plan"])
    start = _start(acc, plan)
    rules = plan.eval if acc["fase"] == "eval" else plan.funded
    acc["balance"] += pnl
    acc["maximo"] = max(acc.get("maximo", start), acc["balance"])
    acc["ultimo_trade"] = today.isoformat()
    if acc["balance"] <= acc["suelo"] + 1e-9:
        acc["fase"] = "perdida"
        acc["perdida"] = today.isoformat()
        return f"{acc['id']}: ha tocado el suelo, cuenta perdida."
    acc["suelo"] = _trail(rules, start, acc["balance"], acc["suelo"])
    if acc["fase"] == "eval":
        acc["dias"] = acc.get("dias", 0) + 1
        acc["mejor_dia"] = max(acc.get("mejor_dia", 0.0), pnl)
        if eval_need(acc, plan) <= 1e-9 and acc["dias"] >= plan.eval.min_days:
            keep = {"id": acc["id"], "plan": acc["plan"], "comprada": acc.get("comprada")}
            funded = activate_funded(plan, fs, state, today, cfg)
            acc.clear()
            acc.update(keep | funded)
            return (f"{acc['id']}: ¡evaluación aprobada! Activa la funded en la web de {plan.firm}. "
                    f"Modo {funded['modo']}: día gordo hasta ${funded['nivel_gordo']:,.0f}.")
        return f"{acc['id']}: balance ${acc['balance']:,.0f}, suelo ${acc['suelo']:,.0f}."
    po = plan.funded.payout
    acc["gordo_hecho"] = acc.get("gordo_hecho", False) or acc["balance"] >= acc["nivel_gordo"] - 1e-9
    acc["dias_verdes"] = acc.get("dias_verdes", 0) + (pnl >= po.green_min - 1e-9)
    acc["dias_ciclo"] = acc.get("dias_ciclo", 0) + 1
    acc["mejor_dia_ciclo"] = max(acc.get("mejor_dia_ciclo", 0.0), pnl)
    msg = f"{acc['id']}: balance ${acc['balance']:,.0f}, suelo ${acc['suelo']:,.0f}, días verdes {acc['dias_verdes']}."
    due = payout_due(acc, plan)
    if due:
        msg += f" Ya puedes pedir un retiro de ${due:,.0f} (${due * po.split:,.0f} netos)."
    return msg


def record_payout(acc, amount, state, today, strats=default_strats) -> str:
    plan, _, fs = strats(acc["plan"])
    r, po, start = plan.funded, plan.funded.payout, _start(acc, plan)
    acc["balance"] -= amount
    acc["payouts"] = acc.get("payouts", 0) + 1
    acc["dias_verdes"] = acc["dias_ciclo"] = 0
    acc["mejor_dia_ciclo"] = 0.0
    acc["inicio_ciclo"] = acc["balance"]
    if r.floor_after_payout is not None:
        acc["suelo"] = start + r.floor_after_payout
    s = funded_strategy(acc, fs)
    acc["nivel_gordo"] = acc["balance"] + s.cycle_gordo
    acc["gordo_hecho"] = s.cycle_gordo <= 0
    state["por_cobrar"] = state.get("por_cobrar", 0.0) + amount * po.split
    state.setdefault("retiros", []).append({"fecha": today.isoformat(), "cuenta": acc["id"], "plan": acc["plan"],
                                            "bruto": amount, "neto": amount * po.split})
    msg =f"{acc['id']}: retiro de ${amount:,.0f} registrado (${amount * po.split:,.0f} netos por cobrar)."
    if po.max_payouts is not None and acc["payouts"] >= po.max_payouts:
        acc["fase"] = "cerrada"
        msg += f" Era el payout {acc['payouts']}: la cuenta pasa a live o se cierra."
    return msg


def purchases(state, today, strats=default_strats, cfg: rec.Config = rec.DEFAULT) -> list[tuple[str, int, float]]:
    """Evaluaciones a comprar hoy: (plan, cuántas, precio) con la caja libre y los límites de cada firma."""
    cash = state["caja"]
    active = [a for a in state["cuentas"] if a["fase"] in ("eval", "funded")]
    out = []
    for s in cfg.slots:
        if cash < s.from_cash:
            continue
        plan = strats(s.plan_id)[0]
        firm = [a for a in active if strats(a["plan"])[0].firm == plan.firm]
        n_eval = sum(a["fase"] == "eval" and a["plan"] == s.plan_id for a in active)
        n = s.parallel - n_eval
        if plan.firm_max_open:
            n = min(n, plan.firm_max_open - len(firm))
        if plan.max_funded_accounts:
            n = min(n, plan.max_funded_accounts - sum(a["fase"] == "funded" and a["plan"] == s.plan_id for a in active))
        if plan.firm_max_purchases_30d:
            recent = sum(1 for c in state["compras"] if c["plan"] == s.plan_id and (today - _date(c["fecha"])).days < 30)
            n = min(n, plan.firm_max_purchases_30d - recent)
        price = plan.costs.attempt_price() if any(
            a["plan"] == s.plan_id for a in state["cuentas"]) else plan.costs.eval_price
        price = min(price, plan.costs.eval_price)
        n = min(n, int(cash // price)) if price > 0 else n
        if n > 0:
            out.append((s.plan_id, n, price))
            cash -= n * price
    return out


def day_plan(state, today, strats=default_strats, cfg: rec.Config = rec.DEFAULT):
    """Trades de hoy (ya elegidos y ordenados por franja) y los que pasan a mañana."""
    trades = []
    for acc in state["cuentas"]:
        if acc["fase"] not in ("eval", "funded"):
            continue
        plan, es, fs = strats(acc["plan"])
        t = eval_trade(acc, plan, es) if acc["fase"] == "eval" else funded_trade(acc, plan, funded_strategy(acc, fs, cfg))
        if t is None:
            continue
        t.idle = (today - _date(acc.get("ultimo_trade", today))).days
        lim = plan.inactivity_days
        t.urgent = lim is not None and t.idle + 3 >= lim
        trades.append(t)
    copying = cfg.copy_evals_from is not None and state["caja"] >= cfg.copy_evals_from
    cap = cfg.trades_per_day or len(trades)
    evals = [t for t in trades if t.kind in ("eval", "minimo")]
    rest = [t for t in trades if t.kind not in ("eval", "minimo")]
    if copying and evals:
        cap -= 1   # todas las evaluaciones en un único bloque a la vez
        ranked = sorted(rest, key=lambda t: (not t.urgent, -t.idle))
        chosen, later = evals + ranked[:max(cap, 0)], ranked[max(cap, 0):]
    else:
        ranked = sorted(trades, key=lambda t: (not t.urgent, -t.idle))
        chosen, later = ranked[:cap], ranked[cap:]
    order = {"verde": 0, "eval": 1, "minimo": 1, "gordo": 2}
    chosen.sort(key=lambda t: (order[t.kind], not t.urgent, -t.idle))
    return chosen, later, copying


def _money(x):
    return f"${x:,.0f}".replace(",", ".")


def _eur(x):
    return f"{x:,.2f} €".replace(",", "_").replace(".", ",").replace("_", ".")


def render(state, today, strats=default_strats, cfg: rec.Config = rec.DEFAULT) -> str:
    chosen, later, copying = day_plan(state, today, strats, cfg)
    active = [a for a in state["cuentas"] if a["fase"] in ("eval", "funded")]
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    L = [f"# Plan del {dias[today.weekday()]} {today.isoformat()}", ""]
    if today.weekday() >= 5:
        L += ["Hoy no hay sesión (fin de semana). Revisa compras y retiros pendientes.", ""]
    n_eval = sum(a["fase"] == "eval" for a in active)
    L += [f"- Caja libre: **{_money(state['caja'])}**" + (f" (+{_money(state['por_cobrar'])} por cobrar)"
                                                         if state.get("por_cobrar") else ""),
          f"- Cuentas: {n_eval} evaluaciones, {len(active) - n_eval} funded",
          f"- Evaluaciones: **{'todas a la vez' if copying else 'una detrás de otra'}**"
          + ("" if cfg.copy_evals_from is None else f" (a la vez con caja ≥ {_money(cfg.copy_evals_from)})"),
          f"- Trades hoy: {len(chosen)}" + (f" ({len(later)} pasan a mañana)" if later else ""), ""]

    todo = []
    for acc in active:
        if acc["fase"] == "funded":
            plan = strats(acc["plan"])[0]
            due = payout_due(acc, plan)
            if due:
                todo.append(f"**Pide retiro** en {acc['id']}: {_money(due)} brutos "
                            f"({_money(due * plan.funded.payout.split)} netos) → `fondeos-hoy retiro {acc['id']}`")
    for pid, n, price in purchases(state, today, strats, cfg):
        plan = strats(pid)[0]
        todo.append(f"**Compra** {n} × {plan.firm} {plan.name} a {_money(price)} → "
                    f"`fondeos-hoy compra {pid} {n}` (guarda el ticket)")
    for t in chosen + later:
        if t.urgent:
            lim = strats(t.acc["plan"])[0].inactivity_days
            todo.append(f"**Inactividad**: {t.acc['id']} lleva {t.idle} días sin operar (límite {lim}); opérala hoy")
    if todo:
        L += ["## Antes de empezar", ""] + [f"- {x}" for x in todo] + [""]

    def table(ts):
        rows = ["| Cuenta | Tipo | Tamaño | Busca | TP (pts) | Stop (pts) | P(ganar) |", "|---|---|---|---|---|---|---|"]
        for t in ts:
            if t.kind == "minimo":
                rows.append(f"| {t.acc['id']} | día mínimo | 1 MNQ | cualquier trade | — | — | — |")
                continue
            tipo = {"verde": "día verde", "eval": "evaluación", "gordo": "día gordo"}[t.kind]
            rows.append(f"| {t.acc['id']} | {tipo} | {t.size} | +{_money(t.target)} / −{_money(t.risk + t.friction)} "
                        f"| {t.tp_pts:g} | {t.sl_pts:g} | {t.p_win:.0%} |")
        return rows

    greens = [t for t in chosen if t.kind == "verde"]
    evals = [t for t in chosen if t.kind in ("eval", "minimo")]
    gordos = [t for t in chosen if t.kind == "gordo"]
    if greens:
        est = len(greens) * MINUTES["verde"]
        L += ["## 13:00–15:25 · Premercado: días verdes, uno detrás de otro", "",
              "Nada abierto de 14:25 a 14:40 si hay dato a las 8:30 de Nueva York (IPC, empleo...).", ""]
        L += table(greens) + [""]
        if est > PREMARKET_MIN:
            L += [f"Estimación: ~{est} min y caben ~{PREMARKET_MIN}; los que no quepan, después de las evaluaciones.", ""]
    if evals:
        how = ("**Todas a la vez** en la apertura, en la misma dirección (nunca largo y corto a la vez) "
               "y con brackets distintos." if copying else "Una detrás de otra: no abras la siguiente hasta "
               "cerrar la anterior.")
        L += ["## 15:30 · Apertura: evaluaciones", "", how, ""] + table(evals) + [""]
        est = len(evals) * MINUTES["eval"] if not copying else MINUTES["eval"]
        if est > OPEN_MIN:
            L += [f"Estimación: ~{est} min; si no te da tiempo, deja las últimas para mañana.", ""]
    if gordos:
        L += ["## Al final · Días gordos", "",
              "Los últimos del día, de uno en uno, con stop y TP puestos: déjalos correr al irte "
              "(la firma cierra lo que siga abierto al final de la sesión).", ""] + table(gordos) + [""]
    if later:
        L += ["## Pasan a mañana", "", ", ".join(t.acc["id"] for t in later), ""]
    L += ["## Al terminar", "", "Registra el P&L neto de cada cuenta que hayas operado:", "",
          "```bash", *(f"uv run fondeos-hoy resultado {t.acc['id']} <pnl>" for t in chosen), "```"]
    return "\n".join(L)


# ---------------------------------------------------------------- contabilidad
def store_ticket(src, day: date, label: str, ledger: Path = LEDGER) -> str:
    """Copia el ticket a contabilidad/tickets/AÑO/ y devuelve su ruta relativa a la contabilidad."""
    src = Path(src).expanduser()
    if not src.is_file():
        raise SystemExit(f"No encuentro el ticket {src}")
    folder = ledger / "tickets" / str(day.year)
    folder.mkdir(parents=True, exist_ok=True)
    dest, k = folder / f"{day.isoformat()}_{label}{src.suffix.lower()}", 2
    while dest.exists():
        dest, k = folder / f"{day.isoformat()}_{label}_{k}{src.suffix.lower()}", k + 1
    shutil.copy2(src, dest)
    return dest.relative_to(ledger).as_posix()


def movements(state, year: int | None = None) -> list[dict]:
    """Gastos (evaluaciones y otros) en negativo y cobros en positivo, en $ y en € si se conocen."""
    rows = []
    for c in state.get("compras", []):
        rows.append({"fecha": str(c["fecha"]), "tipo": "evaluación", "firma": rec.plan(c["plan"]).firm,
                     "concepto": f"{c['plan']} · {c.get('cuenta', '')}", "usd": -float(c["precio"]),
                     "eur": None if c.get("eur") is None else -float(c["eur"]), "ticket": c.get("ticket", "")})
    for g in state.get("gastos", []):
        rows.append({"fecha": str(g["fecha"]), "tipo": "gasto", "firma": "", "concepto": g["concepto"],
                     "usd": None if g.get("usd") is None else -float(g["usd"]),
                     "eur": None if g.get("eur") is None else -float(g["eur"]),
                     "ticket": g.get("ticket", "")})
    for c in state.get("cobros", []):
        firm = rec.plan(c["plan"]).firm if c.get("plan") else ""
        rows.append({"fecha": str(c["fecha"]), "tipo": "cobro", "firma": firm, "concepto": c.get("cuenta", ""),
                     "usd": float(c["usd"]), "eur": None if c.get("eur") is None else float(c["eur"]),
                     "ticket": c.get("ticket", "")})
    if year is not None:
        rows = [r for r in rows if r["fecha"].startswith(str(year))]
    return sorted(rows, key=lambda r: r["fecha"])


def summary(state, year: int) -> str:
    rows = movements(state, year)
    evals = [r for r in rows if r["tipo"] == "evaluación"]
    other = [r for r in rows if r["tipo"] == "gasto"]
    paid = [r for r in rows if r["tipo"] == "cobro"]
    requested = [r for r in state.get("retiros", []) if str(r["fecha"]).startswith(str(year))]

    def tot(rs, cur):
        vals = [r[cur] for r in rs if r[cur] is not None]
        return sum(vals), len(rs) - len(vals)

    def cell(rs):
        out = []
        for cur, fmt in (("usd", _money), ("eur", _eur)):
            total, missing = tot(rs, cur)
            out.append(fmt(total) + (f" (faltan {missing})" if missing else "") if len(rs) > missing else "—")
        return " | ".join(out)

    L = [f"# Contabilidad {year}", "", "| Concepto | Nº | $ | € (cargado por el banco) |", "|---|---|---|---|",
         f"| Evaluaciones compradas | {len(evals)} | {cell(evals)} |",
         f"| Otros gastos | {len(other)} | {cell(other)} |",
         f"| **Total gastado** | {len(evals) + len(other)} | {cell(evals + other)} |",
         f"| **Total cobrado** | {len(paid)} | {cell(paid)} |",
         f"| **Resultado** | | {cell(rows)} |", ""]
    if requested:
        L += [f"Retiros pedidos en el año: {len(requested)}, {_money(sum(r['bruto'] for r in requested))} brutos "
              f"({_money(sum(r['neto'] for r in requested))} netos tras el split).", ""]
    firms = sorted({r["firma"] for r in evals + paid if r["firma"]})
    if firms:
        L += ["## Por firma", "", "| Firma | Evaluaciones | Gastado $ | Cobrado $ | Resultado $ |", "|---|---|---|---|---|"]
        for f in firms:
            g = sum(r["usd"] for r in evals if r["firma"] == f)
            c = sum(r["usd"] for r in paid if r["firma"] == f)
            L.append(f"| {f} | {sum(r['firma'] == f for r in evals)} | {_money(-g)} | {_money(c)} | {_money(c + g)} |")
        L.append("")
    sin_ticket = [r for r in evals + other if not r["ticket"]]
    if sin_ticket:
        L += [f"Faltan {len(sin_ticket)} tickets: " + ", ".join(f"{r['fecha']} {r['concepto']}" for r in sin_ticket), ""]
    L += ["Los importes en € son los que cargó o abonó el banco. Para la declaración, revisa con tu asesor "
          "cómo tributan estos ingresos y qué gastos son deducibles."]
    return "\n".join(L)


def write_summary(state, year: int, ledger: Path = LEDGER) -> Path:
    folder = ledger / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "resumen.md").write_text(summary(state, year) + "\n", encoding="utf-8")
    with open(folder / "movimientos.csv", "w", newline="", encoding="utf-8-sig") as f:   # BOM para Excel
        w = csv.DictWriter(f, ["fecha", "tipo", "firma", "concepto", "usd", "eur", "ticket"], delimiter=";")
        w.writeheader()
        w.writerows(movements(state, year))
    return folder


def _find(state, acc_id):
    for a in state["cuentas"]:
        if a["id"] == acc_id:
            return a
    raise SystemExit(f"No hay ninguna cuenta '{acc_id}' en {STATE.name}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fondeos-hoy", description="Plan del día y registro de las cuentas")
    ap.add_argument("--fecha", type=date.fromisoformat, default=None, help="AAAA-MM-DD (por defecto hoy)")
    ap.add_argument("--guardar", action="store_true", help="guarda el plan en <datos>/planes/FECHA.md")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("compra", help="añade evaluaciones nuevas")
    c.add_argument("plan")
    c.add_argument("n", type=int, nargs="?", default=1)
    c.add_argument("--precio", type=float, default=None)
    c.add_argument("--eur", type=float, default=None, help="€ cargados por el banco (por compra)")
    c.add_argument("--ticket", default=None, help="recibo a guardar en contabilidad/tickets")
    t = sub.add_parser("ticket", help="adjunta un ticket a la compra de una cuenta")
    t.add_argument("cuenta")
    t.add_argument("archivo")
    t.add_argument("--eur", type=float, default=None)
    g = sub.add_parser("gasto", help="otro gasto (VPS, datos, formación...); negativo = reembolso")
    g.add_argument("concepto", nargs="+")
    g.add_argument("--usd", type=float, default=None)
    g.add_argument("--eur", type=float, default=None)
    g.add_argument("--ticket", default=None)
    sub.add_parser("datos", help="dónde están los datos personales y qué hay")
    s = sub.add_parser("resumen", help="gastado vs cobrado del año fiscal")
    s.add_argument("anyo", type=int, nargs="?", default=None)
    r = sub.add_parser("resultado", help="P&L neto de hoy de una cuenta")
    r.add_argument("cuenta")
    r.add_argument("pnl", type=float)
    p = sub.add_parser("retiro", help="payout pedido (bruto)")
    p.add_argument("cuenta")
    p.add_argument("importe", type=float, nargs="?", default=None)
    k = sub.add_parser("cobro", help="ha llegado dinero de un payout")
    k.add_argument("importe", type=float)
    k.add_argument("--eur", type=float, default=None, help="€ abonados por el banco")
    k.add_argument("--cuenta", default=None)
    j = sub.add_parser("caja", help="fija la caja libre")
    j.add_argument("importe", type=float)
    a = ap.parse_args(argv)

    today = a.fecha or date.today()
    if a.cmd == "datos":
        print(f"Carpeta de datos: {DATA}")
        for name in ("contexto.md", "cuentas.yaml", "contabilidad", "planes"):
            print(f"  {name:13} {'sí' if (DATA / name).exists() else 'no existe'}")
        return
    state = load()
    if a.cmd is None:
        text = render(state, today)
        print(text)
        if a.guardar:
            out = PLANS_OUT / f"{today.isoformat()}.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text + "\n", encoding="utf-8")
        return
    if a.cmd == "compra":
        pid = resolve_plan(a.plan)
        plan = default_strats(pid)[0]
        price = plan.costs.eval_price if a.precio is None else a.precio
        prefix = pid.split("_")[0]
        used = {x["id"] for x in state["cuentas"]}
        for i in range(a.n):
            k = 1
            while f"{prefix}-{k}" in used:
                k += 1
            used.add(f"{prefix}-{k}")
            state["cuentas"].append(new_eval(f"{prefix}-{k}", plan, today))
            buy = {"fecha": today.isoformat(), "plan": pid, "cuenta": f"{prefix}-{k}", "precio": price}
            if a.eur is not None:
                buy["eur"] = a.eur
            if a.ticket and i == 0:   # un recibo por pedido: va en la primera cuenta
                buy["ticket"] = store_ticket(a.ticket, today, f"{prefix}-{k}")
            state["compras"].append(buy)
            state["caja"] -= price
        print(f"Añadidas {a.n} evaluaciones de {plan.firm} ({_money(price)} c/u). Caja: {_money(state['caja'])}")
    elif a.cmd == "resultado":
        print(record_result(_find(state, a.cuenta), a.pnl, state, today))
    elif a.cmd == "retiro":
        acc = _find(state, a.cuenta)
        amount = a.importe if a.importe is not None else payout_due(acc, default_strats(acc["plan"])[0])
        if not amount:
            raise SystemExit(f"{a.cuenta} todavía no puede pedir retiro")
        print(record_payout(acc, amount, state, today))
    elif a.cmd == "cobro":
        state["caja"] += a.importe
        state["por_cobrar"] = max(state.get("por_cobrar", 0.0) - a.importe, 0.0)
        entry = {"fecha": today.isoformat(), "usd": a.importe}
        if a.cuenta:
            entry |= {"cuenta": a.cuenta, "plan": _find(state, a.cuenta)["plan"]}
        if a.eur is not None:
            entry["eur"] = a.eur
        state["cobros"].append(entry)
        print(f"Caja: {_money(state['caja'])}")
    elif a.cmd == "ticket":
        buys = [c for c in state["compras"] if c.get("cuenta") == a.cuenta]
        if not buys:
            raise SystemExit(f"No hay ninguna compra de {a.cuenta}")
        buys[-1]["ticket"] = store_ticket(a.archivo, _date(buys[-1]["fecha"]), a.cuenta)
        if a.eur is not None:
            buys[-1]["eur"] = a.eur
        print(f"Ticket guardado en contabilidad/{buys[-1]['ticket']}")
    elif a.cmd == "gasto":
        if a.usd is None and a.eur is None:
            raise SystemExit("Indica el importe con --usd y/o --eur")
        concept = " ".join(a.concepto)
        entry = {"fecha": today.isoformat(), "concepto": concept}
        entry |= {k: v for k, v in (("usd", a.usd), ("eur", a.eur)) if v is not None}
        if a.ticket:
            entry["ticket"] = store_ticket(a.ticket, today, "gasto")
        state["gastos"].append(entry)
        amounts = " / ".join(x for x in (a.usd is not None and _money(a.usd), a.eur is not None and _eur(a.eur)) if x)
        print(f"Gasto registrado: {concept} {amounts}")
    elif a.cmd == "resumen":
        folder = write_summary(state, a.anyo or today.year)
        print(summary(state, a.anyo or today.year))
        print(f"\nGuardado en {folder}")
        return
    elif a.cmd == "caja":
        state["caja"] = a.importe
        print(f"Caja: {_money(state['caja'])}")
    save(state)
