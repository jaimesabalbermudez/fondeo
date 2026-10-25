"""Modelo de mercado: resultado de un trade con stop y take-profit fijos.

El precio se modela como un paseo aleatorio sin deriva (estrategia breakeven), opcionalmente con un
`edge` que suma probabilidad de acierto. La fricción (comisión + slippage, en $) se paga en cada
trade: el TP se amplía en `friction` para que un trade ganador aporte exactamente `target` neto.

Si el suelo de la cuenta está más cerca que el stop, la liquidación hace de stop: la distancia
efectiva es el margen y la probabilidad se recalcula con ella. Sin esto el modelo regala valor
esperado (la firma absorbería gratis la parte de la pérdida que cae por debajo del suelo).

Tamaño y tiempo: con `contracts` (en NQ; 1 MNQ = 0,1) el stop y el TP se pasan a puntos y el trade
tiene una sesión para resolverse. Lo que no toca ni TP ni stop se cierra a mercado al final del día
(resultado parcial, con la misma esperanza cero). Con pocos contratos un objetivo grande queda lejos en
puntos y a menudo no se resuelve en el día; es lo que limitan los scaling plans de las firmas.

Dos modos:
- `bernoulli_trade`: exacto para drawdown EOD/estático (el suelo no se mueve durante el día).
- `path_trade`: paseo aleatorio discretizado para drawdown intradía, donde el suelo sigue al máximo
  no realizado de la equity y puede liquidar la posición antes de su stop.
"""

from functools import cache

import numpy as np

NQ_POINT = 20.0   # $ por punto de un contrato NQ
# Varianza (pts²) de NQ de 9:30 a 15:50 NY con la volatilidad por franja de reports/horario.txt:
# 30 min a 18,8 pts/√min, 60 a 13,4, 180 a 9,9, 90 a 7,7 y 20 a 8,6 -> σ ≈ 214 pts por sesión.
SESSION_VAR = 30 * 18.8**2 + 60 * 13.4**2 + 180 * 9.9**2 + 90 * 7.7**2 + 20 * 8.6**2
# Dispersión (log, desv. típica) de la varianza entre días: hay días tranquilos en los que nada se mueve.
# 0,7 ≈ 2 x 0,35 de la vol diaria realizada; reproduce el backtest de reports/duracion_trades.txt.
VAR_DISPERSION = 0.7


@cache
def _session_table(n_p=49, n_tau=40, n_q=101, n_terms=600, n_z=801):
    """Movimiento browniano entre dos barreras durante una sesión, en unidades de la anchura L = stop + TP.

    Para x0 = stop / L (la probabilidad de TP sin límite de tiempo) y τ = varianza / L² devuelve
    P(TP en el día), P(sin resolver) y los cuantiles (de mejor a peor) de la posición final de los que
    no se resuelven, relativa a la entrada. Serie de autofunciones de la densidad con barreras absorbentes.
    """
    x0 = np.linspace(0.02, 0.98, n_p)
    tau = np.logspace(-3, 1, n_tau)
    n = np.arange(1, n_terms + 1)
    z = np.linspace(0, 1, n_z)
    q = np.linspace(0, 1, n_q)
    decay = np.exp(-np.outer(tau, n**2) * np.pi**2 / 2)                      # (tau, n)
    a = 2 / (n * np.pi) * np.sin(np.outer(x0, n) * np.pi)                    # (p, n)
    none = np.einsum("pn,tn->pt", a * (1 - np.cos(n * np.pi)), decay)
    mean_z = np.einsum("pn,tn->pt", 2 * np.sin(np.outer(x0, n) * np.pi) * (-1.0) ** (n + 1) / (n * np.pi), decay)
    p_tp = x0[:, None] - mean_z
    cdf = np.einsum("pn,tn,nz->ptz", a, decay, 1 - np.cos(np.outer(n, z) * np.pi))   # P(Z <= z, sin resolver)
    cdf = np.maximum.accumulate(np.clip(cdf, 0, None), axis=-1)
    quant = np.empty((n_p, n_tau, n_q))
    for i in range(n_p):
        for j in range(n_tau):
            c = cdf[i, j]
            if c[-1] < 1e-9:
                quant[i, j] = 0.0
                continue
            # cuantil de "mejor a peor": q=0 -> posición más alta
            quant[i, j] = np.interp(1 - q, c / c[-1], z) - x0[i]
    return x0, np.log(tau), np.clip(none, 0, 1), np.clip(p_tp, 0, 1), quant


def _interp2(grid_x, grid_y, table, x, y):
    """Interpolación bilineal (con recorte a la rejilla) de table[i, j, ...] en los puntos (x, y)."""
    def idx(g, v):
        v = np.clip(v, g[0], g[-1])
        i = np.clip(np.searchsorted(g, v) - 1, 0, g.size - 2)
        return i, (v - g[i]) / (g[i + 1] - g[i])
    i, fx = idx(grid_x, x)
    j, fy = idx(grid_y, y)
    if table.ndim == 3:
        fx, fy = fx[:, None], fy[:, None]
    return ((1 - fx) * (1 - fy) * table[i, j] + fx * (1 - fy) * table[i + 1, j]
            + (1 - fx) * fy * table[i, j + 1] + fx * fy * table[i + 1, j + 1])


def session_outcome(win_p, width_pts, u, var):
    """Resultado de un trade con una sesión de varianza `var` (pts²) para resolverse.

    `win_p`: P(TP) sin límite de tiempo (= stop / (stop + TP)); `width_pts`: stop + TP en puntos;
    `u`: uniformes (pequeñas = mejor resultado). Devuelve (código, y): código 1 = TP, -1 = stop,
    0 = cerrado a mercado con P&L y (en unidades de la anchura, relativo a la entrada).
    """
    x0, ltau, none, p_tp, quant = _session_table()
    lt = np.log(var / width_pts**2)
    fast = lt > ltau[-1]          # sesión muy larga para el trade: siempre se resuelve
    pt = np.where(fast, win_p, _interp2(x0, ltau, p_tp, win_p, lt))
    pn = np.where(fast, 0.0, _interp2(x0, ltau, none, win_p, lt))
    # P(TP en el día) proporcional dentro de lo que se resuelve, para que con la sesión infinita cuadre
    pt = np.minimum(pt, 1 - pn)
    code = np.where(u < pt, 1, np.where(u < pt + pn, 0, -1))
    y = np.zeros(u.shape)
    part = code == 0
    if part.any():
        v = (u[part] - pt[part]) / np.maximum(pn[part], 1e-12)
        qs = _interp2(x0, ltau, quant, win_p[part], lt[part])
        k = v * (qs.shape[1] - 1)
        lo = np.minimum(k.astype(int), qs.shape[1] - 2)
        f = k - lo
        rows = np.arange(qs.shape[0])
        y[part] = (1 - f) * qs[rows, lo] + f * qs[rows, lo + 1]
    return code, y


def session_var(rng, shape):
    """Varianza disponible para un trade abierto en la apertura (con días más y menos movidos)."""
    return SESSION_VAR * np.exp(VAR_DISPERSION * rng.standard_normal(shape) - VAR_DISPERSION**2 / 2)


def _effective_risk(bal, floor, risk, friction, dll):
    margin = bal - floor - friction
    r = np.minimum(risk, margin)
    if dll is not None:
        r = np.minimum(r, dll - friction)
    return np.maximum(r, 1e-6)


def bernoulli_trade(rng, bal, floor, risk, target, friction=0.0, edge=0.0, dll=None, u=None, contracts=None):
    """`u`: uniformes propias (p.ej. correlacionadas entre cuentas que copian el mismo trade).
    `contracts`: tamaño en NQ; None = el trade siempre se resuelve (sin límite de tiempo)."""
    r = _effective_risk(bal, floor, risk, friction, dll)
    tp = target + friction
    p = np.clip(r / (r + tp), 0.0, 1.0)
    u = rng.random(bal.shape) if u is None else u
    if contracts is None:
        return np.where(u < np.clip(p + edge, 0.0, 1.0), target, -(r + friction))
    width = (r + tp) / (np.asarray(contracts, float) * NQ_POINT)
    code, y = session_outcome(p, width, np.clip(u - edge, 0.0, 1.0), session_var(rng, bal.shape))
    partial = np.clip(y * (r + tp), -r, tp) - friction
    return np.where(code > 0, target, np.where(code < 0, -(r + friction), partial))


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
