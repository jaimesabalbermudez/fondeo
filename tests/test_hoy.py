from datetime import date

import pytest

from fondeos_sim import hoy
from fondeos_sim import recommended as rec
from fondeos_sim.engine import EvalStrategy, FundedStrategy

TODAY = date(2026, 11, 3)
EVAL = {"lucid_flex_50k_dll": EvalStrategy(1200, 1500, friction=10),
        "tradeify_select_flex_50k": EvalStrategy(1200, None, friction=10)}
FUNDED = FundedStrategy(gordo_target=6000, grind_target=150, grind_risk=600, friction_gordo=10,
                        friction_grind=8, grind_contracts=0.5)


def strats(pid):
    return rec.plan(pid), EVAL.get(pid, EvalStrategy(1000, None, friction=10)), FUNDED


def state(cash, *accs):
    return {"caja": cash, "por_cobrar": 0.0, "cuentas": list(accs), "compras": []}


def test_eval_bracket_whole_margin_and_dll():
    tradeify = rec.plan("tradeify_select_flex_50k")
    t = hoy.eval_trade(hoy.new_eval("t", tradeify, TODAY), tradeify, EVAL[tradeify.id])
    assert (t.tp_pts, t.sl_pts) == (60.5, 98.5)          # +$1.210 brutos; stop 1 punto por encima del suelo
    assert t.p_win == pytest.approx(1990 / 3200)
    lucid = rec.plan("lucid_flex_50k_dll")
    t = hoy.eval_trade(hoy.new_eval("l", lucid, TODAY), lucid, EVAL["lucid_flex_50k_dll"])
    assert t.sl_pts == 59.5 and t.p_win == pytest.approx(1190 / 2400)   # el DLL de $1.200 corta el stop


def test_three_green_eval_days_pass_and_activate_prudent_funded():
    plan = rec.plan("tradeify_select_flex_50k")
    acc = hoy.new_eval("tradeify-1", plan, TODAY)
    st = state(1000, acc)
    targets = []
    for _ in range(3):
        t = hoy.eval_trade(acc, plan, EVAL[plan.id])
        targets.append(t.target)
        hoy.record_result(acc, t.target, st, TODAY, strats)
    assert targets == [1200, 1200, 600]                   # consistencia 40%: el tercer día solo faltan $600
    assert acc["fase"] == "funded" and acc["modo"] == "prudente"
    assert acc["nivel_gordo"] == 52000                     # día gordo prudente de +$2.000
    assert acc["suelo"] == 48000


def test_loss_to_floor_loses_account():
    plan = rec.plan("tradeify_select_flex_50k")
    acc = hoy.new_eval("t", plan, TODAY)
    hoy.record_result(acc, -2000, state(0, acc), TODAY, strats)
    assert acc["fase"] == "perdida"


def test_funded_gordo_then_green_days_then_payout():
    plan = rec.plan("lucid_flex_50k_dll")
    st = state(10000)
    acc = {"id": "lucid-1", "plan": plan.id, **hoy.activate_funded(plan, FUNDED, st, TODAY)}
    st["cuentas"].append(acc)
    assert acc["modo"] == "optimo" and hoy.funded_trade(acc, plan, FUNDED).kind == "gordo"
    hoy.record_result(acc, 6000, st, TODAY, strats)
    assert acc["gordo_hecho"]
    for _ in range(4):
        assert hoy.funded_trade(acc, plan, FUNDED).kind == "verde"
        hoy.record_result(acc, 150, st, TODAY, strats)
    assert hoy.payout_due(acc, plan) == 2000              # 50% de $6.600 con tope de $2.000
    hoy.record_payout(acc, 2000, st, TODAY, strats)
    assert acc["suelo"] == 50100 and acc["dias_verdes"] == 0 and st["por_cobrar"] == pytest.approx(1800)


def test_copying_evals_takes_one_slot():
    cfg = rec.Config(trades_per_day=2, copy_evals_from=10000)
    plan = rec.plan("lucid_flex_50k_dll")
    evals = [hoy.new_eval(f"lucid-{k}", plan, TODAY) for k in range(4)]
    funded = {"id": "lucid-9", "plan": plan.id, **hoy.activate_funded(plan, FUNDED, state(10000), TODAY)}
    chosen, later, copying = hoy.day_plan(state(20000, *evals, funded), TODAY, strats, cfg)
    assert copying and len(chosen) == 5 and not later      # 4 evaluaciones en un bloque + 1 funded
    chosen, later, copying = hoy.day_plan(state(5000, *evals, funded), TODAY, strats, cfg)
    assert not copying and len(chosen) == 2 and len(later) == 3


def test_yearly_ledger_spent_vs_paid(tmp_path):
    st = state(0)
    st["compras"] = [{"fecha": "2026-03-01", "plan": "lucid_flex_50k_dll", "cuenta": "lucid-1", "precio": 69, "eur": 63.5},
                     {"fecha": "2026-03-01", "plan": "tradeify_select_flex_50k", "cuenta": "tradeify-1", "precio": 165},
                     {"fecha": "2025-12-30", "plan": "lucid_flex_50k_dll", "cuenta": "lucid-0", "precio": 69}]
    st["gastos"] = [{"fecha": "2026-04-01", "concepto": "VPS", "usd": 30, "eur": 28},
                    {"fecha": "2026-10-04", "concepto": "Curso", "eur": 100},
                    {"fecha": "2026-10-05", "concepto": "Reembolso curso", "eur": -40}]
    st["cobros"] = [{"fecha": "2026-05-01", "usd": 1800, "eur": 1650, "cuenta": "lucid-1", "plan": "lucid_flex_50k_dll"}]
    rows = hoy.movements(st, 2026)
    assert len(rows) == 6 and sum(r["usd"] or 0 for r in rows) == pytest.approx(1800 - 69 - 165 - 30)
    assert sum(r["eur"] or 0 for r in rows) == pytest.approx(1650 - 63.5 - 28 - 100 + 40)   # gastos solo en €
    text = hoy.summary(st, 2026)
    assert "faltan 1" in text and "Faltan 5 tickets" in text       # Tradeify sin €; ningún ticket adjunto
    ticket = tmp_path / "recibo.PDF"
    ticket.write_bytes(b"%PDF")
    rel = hoy.store_ticket(ticket, date(2026, 3, 1), "lucid-1", ledger=tmp_path / "conta")
    assert rel == "tickets/2026/2026-03-01_lucid-1.pdf"
    assert hoy.store_ticket(ticket, date(2026, 3, 1), "lucid-1", ledger=tmp_path / "conta").endswith("_2.pdf")
    folder = hoy.write_summary(st, 2026, ledger=tmp_path / "conta")
    assert (folder / "movimientos.csv").read_text(encoding="utf-8-sig").count("\n") == 7


def test_purchases_respect_cash_and_firm_limits():
    buys = {pid: (n, price) for pid, n, price in hoy.purchases(state(600), TODAY, strats)}
    # Lucid con cupón reutilizable ($80,50); Tradeify a precio de lista ($165): con lo que queda solo cabe 1
    assert buys == {"lucid_flex_50k_dll": (5, 80.5), "tradeify_select_flex_50k": (1, 165)}
