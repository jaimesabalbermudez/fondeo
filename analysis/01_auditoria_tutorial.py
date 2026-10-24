"""Auditoría numérica del plan del curso (Lucid Flex 50K) y de las herramientas HTML de tutorial/.

Modelo: cada trade es un Bernoulli que gana `win` o pierde `risk`. Con edge=0 la probabilidad de
ganar es la de breakeven risk/(risk+win). La fricción (comisión + slippage) se resta en cada trade.

Reglas Lucid Flex 50K (según curso/comparador; pendientes de verificar con el FAQ actual):
  - MLL $2,000 trailing EOD; el suelo deja de subir al llegar al balance inicial ($50,000).
  - Funded: payout cuando hay >=5 días verdes (>= $150) en el ciclo y profit >= $500;
    retiras min(50% del profit, $2,000); split 90%. Tras el payout el contador de días verdes se reinicia.
"""

import numpy as np

START, DD, LOCK = 50_000.0, 2_000.0, 50_000.0
rng = np.random.default_rng(7)


def breakeven_p(risk, win):
    return risk / (risk + win)


def day_trade(n, risk, win, edge, friction, margin=None):
    """P&L de un trade para n cuentas en paralelo.

    `risk`/`win` son distancias en $ hasta stop/TP; la fricción se paga en ambos casos, así que el TP
    se amplía en `friction` para que un trade ganador aporte `win` neto. Si el suelo está más cerca que
    el stop, la liquidación hace de stop: la distancia efectiva es el margen y la probabilidad de
    acierto se recalcula con ella (paseo aleatorio), en vez de regalar la parte de la pérdida que
    absorbería la firma.
    """
    risk = np.full(n, float(risk))
    if margin is not None:
        risk = np.minimum(risk, margin - friction)
    tp = win + friction
    p = np.clip(breakeven_p(risk, tp) + edge, 0, 1)
    return np.where(rng.random(n) < p, win, -(risk + friction))


def eval_two_days(n=1_000_000, edge=0.0, friction=0.0):
    """Plan del curso: día 1 y día 2 arriesgan $2,000 para ganar $1,500 (consistencia 50%)."""
    bal = np.full(n, START)
    floor = np.full(n, START - DD)
    alive = np.ones(n, bool)
    for _ in range(2):
        pnl = day_trade(n, 2000, 1500, edge, friction, margin=bal - floor)
        bal = np.where(alive, bal + pnl, bal)
        alive &= bal > floor
        floor = np.where(alive, np.maximum(floor, np.minimum(bal - DD, LOCK)), floor)
    return (alive & (bal - START >= 3000 - 1e-9)).mean()


def funded(n=400_000, d1=(2000, 4000), deff=(600, 150), edge_d1=0.0, edge_def=0.0,
           fric_d1=0.0, fric_def=0.0, cap=2000, split=0.9, min_profit=500, greens_needed=5,
           max_payouts=99, horizon=250):
    """Día gordo (riesgo, ganancia) + días defensivos (riesgo, ganancia) hasta reventar o fin de horizonte.

    Devuelve retiros netos por cuenta (media), distribución de nº de payouts y colchón residual medio.
    """
    bal = np.full(n, START)
    floor = np.full(n, START - DD)
    alive = np.ones(n, bool)
    greens = np.zeros(n, int)
    payouts = np.zeros(n, int)
    withdrawn = np.zeros(n)
    first_payout_day = np.full(n, -1)
    for day in range(1, horizon + 1):
        margin = bal - floor
        if day == 1:
            pnl = day_trade(n, *d1, edge_d1, fric_d1, margin)
        else:
            pnl = day_trade(n, *deff, edge_def, fric_def, margin)
        active = alive & (payouts < max_payouts)
        bal = np.where(active, bal + pnl, bal)
        died = active & (bal <= floor + 1e-9)
        alive &= ~died
        active &= ~died
        floor = np.where(active, np.maximum(floor, np.minimum(bal - DD, LOCK)), floor)
        greens += (active & (pnl >= 150)).astype(int)
        profit = bal - START
        can = active & (greens >= greens_needed) & (profit >= min_profit)
        amt = np.where(can, np.minimum(cap, 0.5 * profit), 0.0)
        bal -= amt
        withdrawn += amt * split
        first_payout_day = np.where(can & (payouts == 0), day, first_payout_day)
        payouts += can.astype(int)
        greens = np.where(can, 0, greens)
    residual = np.where(alive, bal - floor, 0.0)
    return dict(
        ev_net=withdrawn.mean(),
        p_payout=(payouts >= 1).mean(),
        payout_dist=np.bincount(payouts, minlength=6)[:6] / n,
        alive_end=alive.mean(),
        residual=residual.mean(),
        days_first=first_payout_day[first_payout_day > 0].mean() if (first_payout_day > 0).any() else float('nan'),
    )


def show(title, r, eval_cost=91, p_pass=None):
    line = (f"{title:<44} EV neto/funded ${r['ev_net']:>6.0f} | P(>=1 payout) {r['p_payout']:.1%} | "
            f"payouts 0..5: {np.round(r['payout_dist'], 3)} | vivas al final {r['alive_end']:.1%} "
            f"(colchón medio ${r['residual']:.0f}) | días a 1er payout {r['days_first']:.1f}")
    if p_pass is not None:
        ev_eval = p_pass * r['ev_net'] - eval_cost
        line += f" | EV/eval ${ev_eval:.0f} (ROI {ev_eval / eval_cost:+.0%})"
    print(line)


if __name__ == "__main__":
    print("=== EVALUACIÓN (2 días, $2,000 -> $1,500) ===")
    p0 = eval_two_days()
    print(f"edge 0, sin fricción: P(pasar) = {p0:.4f}  (teórico (4/7)^2 = {(4/7)**2:.4f})")
    for fr in (10, 20):
        print(f"edge 0, fricción ${fr}/trade: P(pasar) = {eval_two_days(friction=fr):.4f}")
    for e in (-0.03, +0.03, +0.06):
        print(f"edge {e:+.2f}: P(pasar) = {eval_two_days(edge=e):.4f}")

    print("\n=== FUNDED: plan del curso (día gordo 2R + días verdes $600->$150) ===")
    print(f"Cota teórica (martingala): retiros brutos <= $2,000 x P(morir antes del lock) = "
          f"2000 x 2/3 = $1,333 -> neto 90% = $1,200")
    base = funded()
    show("Curso, edge 0, sin fricción", base, p_pass=p0)
    show("Curso, edge 0, fricción $10 / $8", funded(fric_d1=10, fric_def=8), p_pass=eval_two_days(friction=10))
    show("Curso, tope 5 payouts (paso a live)", funded(max_payouts=5), p_pass=p0)

    print("\n=== FUNDED: variantes del día gordo (edge 0, sin fricción) ===")
    for mult in (1, 2, 3, 5, 8):
        r = funded(d1=(2000, 2000 * mult))
        show(f"Día gordo {mult}R", r, p_pass=p0)
    show("Sin día gordo (solo días verdes)", funded(d1=(600, 150)), p_pass=p0)

    print("\n=== Lo que muestran las herramientas del curso con sus valores por defecto ===")
    # LIVESIM Día 1: d1 55% WR a 2R (breakeven 33%) y defensivo 90% WR a 1R (breakeven 50%)
    print(f"Edge implícito por trade: día gordo 55% a 2R -> EV = {0.55*4000-0.45*2000:+.0f}$ por trade; "
          f"defensivo 90% a 1R ($150) -> EV = {0.9*150-0.1*150:+.0f}$ por día")
    show("LiveSim defaults (55%@2R, 90%@1R $150)",
         funded(d1=(2000, 4000), deff=(150, 150), edge_d1=0.55 - 1/3, edge_def=0.9 - 0.5), p_pass=p0)
    # 'ROI medio real' del resumen: (rec1+rec2+rec3 si todo sale bien) / coste por 1er retiro
    rec = 1800 + 900 + 450
    cost_first = 91 / p0 / base['p_payout']
    print(f"'ROI medio real' estilo curso: (1800+900+450) / (91/{p0:.3f}/{base['p_payout']:.3f} = ${cost_first:.0f})"
          f" = {rec / cost_first:.0%}  vs EV real por eval: {(p0 * base['ev_net'] - 91) / 91:+.0%}")
