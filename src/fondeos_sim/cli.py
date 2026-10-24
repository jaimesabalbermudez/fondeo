"""CLI: `uv run fondeos-sim [--solo-eod] [--n 20000] [--denegacion 0] [--plans plans]`."""

import argparse
from pathlib import Path

from .optimize import Frictions, optimize_plan, with_denial
from .plan import load_plans


def _fmt_eval(r):
    if r.eval_strat is None:
        return "directo"
    s = r.eval_strat
    risk = "todo" if s.risk is None else f"${s.risk:,.0f}"
    return f"+${s.day_target:,.0f}/día, stop {risk}"


def _fmt_funded(r):
    s = r.funded_strat
    gordo = f"gordo +${s.gordo_target:,.0f}" if s.gordo_target else "sin gordo"
    again = f"; tras cada payout otro gordo +${s.cycle_gordo:,.0f}" if s.cycle_gordo else ""
    return f"{gordo}; luego +${s.grind_target:,.0f} / stop {_stop(s.grind_risk)}{again}"


def report(results, solo_eod: bool) -> str:
    rows = sorted(results, key=lambda r: r.ev_attempt, reverse=True)
    lines = [
        "| Plan | EOD | p deneg. | Evaluación | P(pasar) | Coste/intento | Funded | V neto | P(≥1 payout) "
        "| **EV/intento** | ROI | Días funded | EV/día de hueco |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if solo_eod and not r.plan.all_eod:
            continue
        lines.append(
            f"| {r.plan.firm} {r.plan.name} | {'✓' if r.plan.all_eod else '✗ intradía'} | {r.plan.p_payout_denial:.0%} "
            f"| {_fmt_eval(r)} | {r.p_pass:.1%} | ${r.cost:,.0f} | {_fmt_funded(r)} | ${r.value:,.0f} "
            f"| {r.fd['p_payout']:.1%} | **${r.ev_attempt:,.0f}** | {r.roi:+.0%} | {r.fd['days']:.1f} "
            f"| ${r.ev_per_slot_day:,.0f} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Optimiza y compara planes de fondeo")
    ap.add_argument("--plans", default="plans")
    ap.add_argument("--n", type=int, default=20_000)
    ap.add_argument("--n-refine", type=int, default=100_000)
    ap.add_argument("--solo-eod", action="store_true", help="solo planes sin drawdown intradía")
    ap.add_argument("--denegacion", type=float, default=None,
                    help="sobrescribe p_payout_denial en todos los planes")
    ap.add_argument("--objetivo-funded", choices=["value", "per_day"], default="value")
    ap.add_argument("--friccion", type=float, nargs=3, metavar=("EVAL", "GORDO", "GRIND"), default=(10, 10, 8))
    ap.add_argument("--precios", choices=["verificados", "todos", "lista"], default="verificados",
                    help="qué códigos de descuento usar")
    ap.add_argument("--out", default="reports/ranking.md")
    a = ap.parse_args()

    plans = [p.with_price_mode(a.precios) for p in load_plans(a.plans)]
    if a.solo_eod:
        plans = [p for p in plans if p.all_eod]
    if a.denegacion is not None:
        plans = [with_denial(p, a.denegacion) for p in plans]
    fr = Frictions(*a.friccion)
    results = []
    for p in plans:
        print(f"optimizando {p.id}...", flush=True)
        results.append(optimize_plan(p, n=a.n, n_refine=a.n_refine, fr=fr, funded_objective=a.objetivo_funded))
    table = report(results, a.solo_eod)
    print("\n" + table)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(table + "\n")
    print(f"\nGuardado en {a.out}")


def dashboard():
    import sys

    from streamlit.web import cli as stcli

    sys.argv = ["streamlit", "run", str(Path(__file__).with_name("dashboard.py")), *sys.argv[1:]]
    sys.exit(stcli.main())
