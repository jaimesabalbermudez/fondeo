"""Modelo de mercado: resultado de un trade con stop y take-profit fijos.

El precio se modela como un paseo aleatorio sin deriva (estrategia breakeven), opcionalmente con un
`edge` que suma probabilidad de acierto. La fricción (comisión + slippage, en $) se paga en cada
trade: el TP se amplía en `friction` para que un trade ganador aporte exactamente `target` neto.

Si el suelo de la cuenta está más cerca que el stop, la liquidación hace de stop: la distancia
efectiva es el margen y la probabilidad se recalcula con ella. Sin esto el modelo regala valor
esperado (la firma absorbería gratis la parte de la pérdida que cae por debajo del suelo).

Dos modos:
- `bernoulli_trade`: exacto para drawdown EOD/estático (el suelo no se mueve durante el día).
- `path_trade`: paseo aleatorio discretizado para drawdown intradía, donde el suelo sigue al máximo
  no realizado de la equity y puede liquidar la posición antes de su stop.
"""

import numpy as np


def _effective_risk(bal, floor, risk, friction, dll):
    margin = bal - floor - friction
    r = np.minimum(risk, margin)
    if dll is not None:
        r = np.minimum(r, dll - friction)
    return np.maximum(r, 1e-6)


def bernoulli_trade(rng, bal, floor, risk, target, friction=0.0, edge=0.0, dll=None, u=None):
    """`u`: uniformes propias (p.ej. correlacionadas entre cuentas que copian el mismo trade)."""
    r = _effective_risk(bal, floor, risk, friction, dll)
    tp = target + friction
    p = np.clip(r / (r + tp) + edge, 0.0, 1.0)
    u = rng.random(bal.shape) if u is None else u
    return np.where(u < p, target, -(r + friction))


def _max_given_low_exit(u, low, high):
    """Máximo alcanzado por un BM que sale de (-low, high) por abajo, por inversión de
    P(M >= m | sale por abajo) = low (high - m) / ((low + m) high)."""
    return low * high * (1 - u) / (u * high + low)


def intraday_trade(rng, bal, floor, risk, target, friction, mll, lock_level, u=None):
    """Trade con drawdown intradía trailing, muestreado exactamente (movimiento browniano).

    Barrera inferior efectiva en función del máximo M del P&L: max(-R, min(M - mll, L)), con
    R = stop efectivo (<= margen) y L = nivel de bloqueo relativo al balance. Tres etapas:
      1. Hasta que M llega a a = mll - R el stop -R manda (ruina del jugador entre -R y a).
      2. Entre a y c = L + mll la barrera es M - mll: P(subir c - a antes de caer mll desde el
         máximo) = exp(-(c - a)/mll); si cae antes, el máximo extra es Exp(mll) truncada.
      3. Por encima de c el suelo está bloqueado en L: ruina del jugador entre L y el TP.
    Devuelve (pnl, floor_nuevo), donde el suelo refleja el máximo intradía alcanzado.
    """
    n = bal.shape[0]
    r = _effective_risk(bal, floor, risk, friction, None)
    tp = target + friction
    L = lock_level - bal
    a = np.minimum(np.maximum(mll - r, 0.0), tp)
    c = np.minimum(np.maximum(L + mll, a), tp)
    u1, u2, u3 = rng.random((3, n))
    if u is not None:   # la correlación entra por la etapa principal (llegar al bloqueo o al TP)
        u1 = u

    pnl_x = np.empty(n)    # P&L bruto (antes de fricción) en la salida
    peak = np.empty(n)     # máximo intradía del P&L bruto

    # Etapa 1
    win1 = u1 < r / (r + a)
    lose1 = ~win1
    pnl_x[lose1] = -r[lose1]
    peak[lose1] = _max_given_low_exit(rng.random(lose1.sum()), r[lose1], a[lose1])
    done = lose1 | (win1 & (a >= tp))
    pnl_x[win1 & (a >= tp)] = tp[win1 & (a >= tp)]
    peak[win1 & (a >= tp)] = tp[win1 & (a >= tp)]

    # Etapa 2: drawdown desde el máximo
    s2 = ~done
    gap = c - a
    reach_c = s2 & (u2 < np.exp(-gap / mll))
    dd = s2 & ~reach_c
    if dd.any():
        # máximo extra ~ Exp(media mll) truncada a [0, gap)
        g = gap[dd]
        extra = -mll * np.log(1 - rng.random(dd.sum()) * (1 - np.exp(-g / mll)))
        m = a[dd] + extra
        peak[dd] = m
        pnl_x[dd] = m - mll
    done |= dd
    at_tp = reach_c & (c >= tp)
    pnl_x[at_tp] = tp[at_tp]
    peak[at_tp] = tp[at_tp]
    done |= at_tp

    # Etapa 3: suelo bloqueado en L (o el stop, si está por encima), desde c
    s3 = ~done
    if s3.any():
        exit_low = np.maximum(L, -r)
        low, high = c[s3] - exit_low[s3], tp[s3] - c[s3]
        win3 = u3[s3] < low / (low + high)
        idx = np.flatnonzero(s3)
        pnl_x[idx[win3]] = tp[idx[win3]]
        peak[idx[win3]] = tp[idx[win3]]
        lw = idx[~win3]
        pnl_x[lw] = exit_low[lw]
        peak[lw] = c[lw] + _max_given_low_exit(rng.random(lw.size), low[~win3], high[~win3])

    pnl = np.where(pnl_x >= tp, target, pnl_x - friction)
    new_floor = np.maximum(floor, np.minimum(bal + peak - mll, lock_level))
    return pnl, new_floor


def path_trade(rng, bal, floor, risk, target, friction, mll, lock_level, resolution=20, max_steps=1_000_000):
    """Trade con drawdown intradía trailing. Devuelve (pnl, floor_nuevo).

    `lock_level`: nivel absoluto donde el suelo deja de subir (np.inf si no se bloquea).
    El paso del paseo es min(stop, TP)/resolution: error de discretización pequeño y coste ~resolution².
    """
    n = bal.shape[0]
    r = _effective_risk(bal, floor, risk, friction, None)
    tp = target + friction
    step = np.maximum(np.minimum(r, tp) / resolution, 1.0)
    x = np.zeros(n)
    peak = np.zeros(n)
    fl = floor.astype(float).copy()
    pnl = np.zeros(n)
    open_ = np.ones(n, bool)
    for _ in range(max_steps):
        idx = np.flatnonzero(open_)
        if idx.size == 0:
            break
        x[idx] += np.where(rng.random(idx.size) < 0.5, step[idx], -step[idx])
        peak[idx] = np.maximum(peak[idx], x[idx])
        fl[idx] = np.maximum(fl[idx], np.minimum(bal[idx] + peak[idx] - mll, lock_level[idx]))
        won = x[idx] >= tp[idx]
        stopped = x[idx] <= -r[idx]
        liquidated = bal[idx] + x[idx] <= fl[idx]
        pnl[idx] = np.where(won, target[idx],
                   np.where(liquidated, fl[idx] - bal[idx], -r[idx]) - friction)
        open_[idx] = ~(won | stopped | liquidated)
    else:
        raise RuntimeError("path_trade no convergió: sube `resolution` o revisa stops/targets")
    return pnl, fl
