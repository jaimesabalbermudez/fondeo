from datetime import date, timedelta

import pytest

from fondeos_sim import hoy
from fondeos_sim import recommended as rec
from fondeos_sim.engine import EvalStrategy, FundedStrategy

TODAY = date(2026, 11, 3)
EVAL = {"lucid_flex_50k_dll": EvalStrategy(1200, 1500, friction=10),
        "tradeify_select_flex_50k": EvalStrategy(1200, None, friction=10)}
FUNDED = FundedStrategy(gordo_target=6000, grind_target=150, grind_risk=600, friction_gordo=10,
                        friction_grind=8, grind_contracts=0.5)


# cartera de antes del 2026-11-04 (Lucid y Tradeify desde el inicio, MFFU y FundedNext con $3.000):
# fija para que estos tests no dependan de la cartera recomendada del momento
OLD = rec.Config(slots=(rec.Slot("lucid_flex_50k_dll", 5), rec.Slot("tradeify_select_flex_50k", 5),
                        rec.Slot("mffu_rapid_eod_50k", 3, 3000), rec.Slot("fundednext_flex_50k", 5, 3000)))


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
    for i in range(3):
        t = hoy.eval_trade(acc, plan, EVAL[plan.id])
        targets.append(t.target)
        hoy.record_result(acc, t.target, st, TODAY + timedelta(days=i), strats, OLD)
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
    for i in range(1, 5):
        assert hoy.funded_trade(acc, plan, FUNDED).kind == "verde"
        hoy.record_result(acc, 150, st, TODAY + timedelta(days=i), strats)
    assert hoy.payout_due(acc, plan) == 2000              # 50% de $6.600 con tope de $2.000
    hoy.record_payout(acc, 2000, st, TODAY, strats)
    assert acc["suelo"] == 50100 and acc["dias_verdes"] == 0 and st["por_cobrar"] == pytest.approx(1800)


def test_copying_evals_takes_one_slot():
    cfg = rec.Config(trades_per_day=2, copy_evals_from=10000)
    plan = rec.plan("lucid_flex_50k_dll")
    evals = [hoy.new_eval(f"lucid-{k}", plan, TODAY) for k in range(4)]
    funded = {"id": "lucid-9", "plan": plan.id, **hoy.activate_funded(plan, FUNDED, state(10000), TODAY)}
    chosen, later, copying, _ = hoy.day_plan(state(20000, *evals, funded), TODAY, strats, cfg)
    assert copying and len(chosen) == 5 and not later      # 4 evaluaciones en un bloque + 1 funded
    chosen, later, copying, _ = hoy.day_plan(state(5000, *evals, funded), TODAY, strats, cfg)
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
    buys = {pid: (n, price) for pid, n, price in hoy.purchases(state(600), TODAY, strats, OLD)}
    # Lucid con cupón reutilizable ($80,50); Tradeify a precio de lista ($165): con lo que queda solo cabe 1
    assert buys == {"lucid_flex_50k_dll": (5, 80.5), "tradeify_select_flex_50k": (1, 165)}


def test_close_from_firm_email_is_idempotent_across_computers():
    """El Daily Wire de Lucid (balance y suelo) se aplica una sola vez aunque lo procesen dos ordenadores."""
    plan = rec.plan("lucid_flex_50k_dll")
    acc = {**hoy.new_eval("lucid-1", plan, TODAY), "numero": "LFE05098099680001"}
    st = state(4919.5, acc)
    found = hoy._find(st, "LFE05098099680001")
    assert found is acc
    msg = hoy.record_close(found, 51207, st, TODAY, floor=49207, strats=strats)
    assert "balance $51,207" in msg and acc["suelo"] == 49207 and acc["dias"] == 1 and acc["mejor_dia"] == 1207
    assert "cuadra" in hoy.record_close(acc, 51207, st, TODAY, floor=49207, strats=strats)   # el otro ordenador
    assert "ya estaba registrado" in hoy.record_result(acc, 1206.5, st, TODAY, strats)       # y a mano
    assert acc["dias"] == 1 and acc["balance"] == 51207
    # si el usuario lo registró a mano con otra cifra, el dato de la firma lo corrige sin contar otro día
    acc2 = hoy.new_eval("lucid-2", plan, TODAY)
    hoy.record_result(acc2, 1200, st, TODAY, strats)
    assert "corrijo" in hoy.record_close(acc2, 51207, st, TODAY, floor=49207, strats=strats)
    assert acc2["balance"] == 51207 and acc2["suelo"] == 49207 and acc2["dias"] == 1


def test_close_below_floor_loses_account_and_pass_keeps_number():
    tradeify = rec.plan("tradeify_select_flex_50k")
    acc = hoy.new_eval("tradeify-1", tradeify, TODAY)
    hoy.record_close(acc, 47990, state(0, acc), TODAY, strats=strats)
    assert acc["fase"] == "perdida"
    acc = {**hoy.new_eval("tradeify-2", tradeify, TODAY), "numero": "TDY-123"}
    st = state(1000, acc)
    for i, bal in enumerate((51200, 52400, 53000)):
        hoy.record_close(acc, bal, st, TODAY + timedelta(days=i), strats=strats)
    assert acc["fase"] == "funded" and acc["numero"] == "TDY-123" and len(acc["registrados"]) == 3


def test_write_lock_blocks_other_computer(tmp_path):
    (tmp_path / ".bloqueo").write_text("OTRO-PC", encoding="utf-8")
    with pytest.raises(SystemExit, match="OTRO-PC"):
        with hoy.write_lock(tmp_path):
            pass
    (tmp_path / ".bloqueo").unlink()
    with hoy.write_lock(tmp_path):
        assert (tmp_path / ".bloqueo").exists()
    assert not (tmp_path / ".bloqueo").exists()


def test_history_activity_and_people(tmp_path, monkeypatch):
    plan = rec.plan("lucid_flex_50k_dll")
    acc = hoy.new_eval("lucid-1", plan, TODAY)
    st = {**state(1000, acc), "gastos": [], "cobros": [], "retiros": [],
          "compras": [{"fecha": "2026-11-03", "plan": plan.id, "cuenta": "lucid-1", "precio": 80.5}]}
    hoy.record_close(acc, 51207, st, TODAY, floor=49207, strats=strats)
    hoy.record_close(acc, 50607, st, TODAY + timedelta(days=1), strats=strats)
    assert [h["pnl"] for h in acc["historial"]] == [1207, -600]
    hoy.record_close(acc, 50700, st, TODAY + timedelta(days=1), strats=strats)       # la firma corrige el día
    assert acc["historial"][-1] == {"fecha": "2026-11-04", "pnl": -507, "balance": 50700}
    ev = hoy.activity(st, lambda pid: "Lucid")
    assert ev[0]["tipo"] == "Día operado" and sorted(e["tipo"] for e in ev[1:]) == ["Compra de evaluación", "Día operado"]
    # cuentas registradas antes del historial: el único día se deduce del balance
    old = {**hoy.new_eval("lucid-2", plan, TODAY), "balance": 51207.0, "registrados": ["2026-11-03"]}
    assert hoy.day_history(old, plan)[0]["pnl"] == 1207
    # una carpeta por persona, con el nombre del título de su contexto.md
    for folder, title in (("Fondeo", "# Contexto privado de Lucas (fondeo)"), ("Fondeo-Lucas 2", "# Contexto de Lucas 2")):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "cuentas.yaml").write_text("caja: 0\n", encoding="utf-8")
        (tmp_path / folder / "contexto.md").write_text(title + "\n", encoding="utf-8")
    monkeypatch.setenv("OneDrive", str(tmp_path))
    monkeypatch.setattr(hoy, "DATA", tmp_path / "Fondeo")
    people = hoy.person_folders()
    assert people["Lucas"] == tmp_path / "Fondeo" and people["Lucas 2"] == tmp_path / "Fondeo-Lucas 2"


def test_default_portfolio_starts_with_lucid_and_grows_with_cash():
    """Cartera recomendada: 10 Lucid al empezar; Tradeify con $6.000 y MFFU + FundedNext con $10.000."""
    def buys(cash):
        return {pid: n for pid, n, _ in hoy.purchases(state(cash), TODAY, strats)}
    assert buys(5000) == {"lucid_flex_50k_dll_c50": 10}
    assert set(buys(8000)) == {"lucid_flex_50k_dll_c50", "tradeify_select_flex_50k"}
    assert set(buys(20000)) == {"lucid_flex_50k_dll_c50", "tradeify_select_flex_50k", "mffu_rapid_eod_50k",
                                "fundednext_flex_50k"}
    # una cuenta de un plan fuera de la cartera (lucid-1, Flex 40%) aprueba sin romper nada
    plan = rec.plan("lucid_flex_50k_dll")
    assert hoy.activate_funded(plan, FUNDED, state(1000), TODAY)["modo"] == "prudente"


def test_evals_wait_when_funded_slots_are_full():
    """Lucid: 5 fondeadas por hogar. Con 5 fondeadas, las evaluaciones esperan; con 1 hueco, solo una
    evaluación hace el trade que la aprobaría (la que menos tiene por ganar)."""
    plan = rec.plan("lucid_flex_50k_dll")
    funded = [{"id": f"lucid-f{k}", "plan": plan.id, **hoy.activate_funded(plan, FUNDED, state(10000), TODAY)}
              for k in range(5)]
    near = [{**hoy.new_eval(f"lucid-{k}", plan, TODAY), "balance": 51200.0 + 1200 * (k > 1), "dias": 1 + (k > 1),
             "mejor_dia": 1200.0} for k in range(4)]   # lucid-2 y lucid-3: les faltan $600 para aprobar
    st = state(10000, *funded, *near)
    chosen, _, _, waiting = hoy.day_plan(st, TODAY, strats, rec.Config(trades_per_day=20))
    assert {a["id"] for a, _ in waiting} == {"lucid-0", "lucid-1", "lucid-2", "lucid-3"}
    assert all(t.acc["fase"] == "funded" for t in chosen)
    assert "En espera" in hoy.render(st, TODAY, strats, rec.Config(trades_per_day=20))
    # una funded perdida libera un hueco: todas vuelven a operar; de las dos que aprobarían hoy, la
    # segunda es condicional (solo si la primera no ha aprobado) y van primero
    funded[0]["fase"] = "perdida"
    chosen, _, _, waiting = hoy.day_plan(st, TODAY, strats, rec.Config(trades_per_day=20))
    evals = [t for t in chosen if t.kind == "eval"]
    assert {t.acc["id"] for t in evals} == {"lucid-0", "lucid-1", "lucid-2", "lucid-3"} and not waiting
    assert [t.final for t in evals[:2]] == [True, True] and [t.conditional for t in evals[:2]] == [0, 1]
    assert "condicionales" in hoy.render(st, TODAY, strats, rec.Config(trades_per_day=20))
    # en espera y a punto de incumplir la inactividad: trade mínimo
    funded[0]["fase"] = "funded"
    near[0]["ultimo_trade"] = "2026-10-06"   # 28 días parada (límite 30)
    chosen, _, _, _ = hoy.day_plan(st, TODAY, strats, rec.Config(trades_per_day=20))
    assert any(t.acc["id"] == "lucid-0" and t.kind == "minimo" for t in chosen)


def test_no_purchases_when_a_funded_account_is_about_to_go_live():
    """Lucid cierra todas las cuentas simuladas al pasar a live: con una fondeada en su 4º retiro de 5 no se
    compran más evaluaciones de Lucid y el plan lo avisa."""
    plan = rec.plan("lucid_flex_50k_dll")
    acc = {"id": "lucid-1", "plan": plan.id, **hoy.activate_funded(plan, FUNDED, state(10000), TODAY), "payouts": 4}
    st = state(5000, acc)
    assert "lucid_flex_50k_dll" not in {pid for pid, _, _ in hoy.purchases(st, TODAY, strats, OLD)}
    assert "Cerca de live" in hoy.render(st, TODAY, strats, OLD)
    acc["payouts"] = 3
    assert "lucid_flex_50k_dll" in {pid for pid, _, _ in hoy.purchases(st, TODAY, strats, OLD)}


def test_eval_finishes_today_when_need_barely_exceeds_day_target():
    """lucid-8 del 4-nov: +$1.507 el primer día con consistencia 50% -> le faltan $1.507; se busca todo hoy."""
    plan = rec.plan("lucid_flex_50k_dll_c50")
    acc = {**hoy.new_eval("lucid-8", plan, TODAY), "balance": 51507.0, "suelo": 49507.0, "mejor_dia": 1507.0, "dias": 1}
    t = hoy.eval_trade(acc, plan, EvalStrategy(1500, None, friction=10))
    assert t.target == pytest.approx(1507)
    hoy.record_result(acc, t.target, state(1000, acc), TODAY, strats)
    assert acc["fase"] == "funded"
    # si falta bastante más que el objetivo diario, se mantiene el objetivo diario
    acc2 = {**hoy.new_eval("lucid-9", plan, TODAY), "balance": 50900.0, "mejor_dia": 900.0, "dias": 1}
    assert hoy.eval_trade(acc2, plan, EvalStrategy(1500, None, friction=10)).target == 1500


WIRE = """LucidEval
YOUR DAILY SNAPSHOT 11/04/2026

Account Number: LFE05098099680008

Account Balance
$51,507
Total Profit
$1,507
Session PnL
$1,507

Days Traded
1
Profit Target
$3,013
Minimum Balance
$49,507

Account Number: LFE05098099680007

Account Balance
$48,807
Total Profit
-$1,194
Session PnL
-$1,194

Days Traded
1
Profit Target
$3,000
Minimum Balance
$48,000

Account Number: LFE05098099680011

Account Balance
$50,000
Total Profit
$0
Session PnL
$0

Days Traded
0
Profit Target
$3,000
Minimum Balance
$48,000

For a full breakdown of your stats (including all accounts and historical performance), please visit your trading dashboard.
"""


def test_daily_wire_registers_every_account_in_the_email():
    """Lucid manda varias cuentas en un mismo Daily Wire: se registran todas (el fallo del 4-nov)."""
    day, accs = hoy.parse_daily_wire(WIRE)
    assert day == date(2026, 11, 4)
    assert [(a["numero"], a["balance"], a["pnl"], a["suelo"]) for a in accs] == [
        ("LFE05098099680008", 51507, 1507, 49507), ("LFE05098099680007", 48807, -1194, 48000),
        ("LFE05098099680011", 50000, 0, 48000)]
    plan = rec.plan("lucid_flex_50k_dll_c50")
    a8 = {**hoy.new_eval("lucid-8", plan, TODAY), "numero": "LFE05098099680008"}
    a7 = {**hoy.new_eval("lucid-7", plan, TODAY), "numero": "LFE05098099680007"}
    st = state(1000, a8, a7)
    out = hoy.record_daily_wire(WIRE, st, strats)
    assert a8["balance"] == 51507 and a7["balance"] == 48807 and a7["suelo"] == 48000 and a7["fase"] == "eval"
    assert "no hay ninguna cuenta" in out[2]          # número sin asociar: se avisa, no se inventa
    assert all("cuadra" in m for m in hoy.record_daily_wire(WIRE, st, strats)[:2])   # el otro ordenador
