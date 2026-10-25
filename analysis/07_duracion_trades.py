"""¿Cuánto dura un trade con su TP y SL, cuántos no cierran antes del final de la sesión, y qué pasa si se
abre un trade nuevo cada X minutos sin esperar a que cierre el anterior?

Backtest sobre NQ real en velas de 1 minuto (últimas 4 semanas de Yahoo Finance). Cada trade empieza a una
hora fija (cada 15 min de 9:31 a 15:00, hora de Nueva York), en las dos direcciones, y se sigue vela a vela
hasta tocar TP o SL; si ambos caen en la misma vela se decide 50/50. A las 15:50 se cierra a mercado.

`uv run --with yfinance python analysis/07_duracion_trades.py`
"""

import datetime as dt

import numpy as np
import pandas as pd
import yfinance as yf

END = dt.datetime(2026, 10, 24)
parts = [yf.download("NQ=F", start=END - dt.timedelta(days=7 * (i + 1)), end=END - dt.timedelta(days=7 * i),
                     interval="1m", progress=False) for i in range(4)]
d = pd.concat(parts).sort_index()
d = d[~d.index.duplicated()]
d.columns = d.columns.get_level_values(0)
d = d.tz_convert("America/New_York")

# (nombre, TP pts, SL pts): mismo trade en $ con distinto tamaño -> distinta distancia en puntos
SPECS = [("Eval ±$1.200 con 1 NQ", 60, 60), ("Eval ±$1.200 con 2 NQ", 30, 30), ("Eval ±$1.200 con 4 NQ", 15, 15),
         ("Eval MFFU +$900/−$2.000, 1 NQ", 45, 100), ("Gordo +$8.000/−$2.000, 2 NQ", 200, 50),
         ("Gordo +$8.000/−$2.000, 4 NQ", 100, 25), ("Gordo prudente ±$2.000, 2 NQ", 50, 50),
         ("Verde +$150/−$600, 5 MNQ", 15, 60)]
STARTS = [f"{h:02d}:{m:02d}" for h in range(9, 15) for m in (1, 16, 31, 46) if (h, m) >= (9, 31)] + ["15:01"]
CLOSE = "15:50"
rng = np.random.default_rng(0)

sessions = []
for day, g in d.groupby(d.index.date):
    g = g.between_time("09:30", CLOSE)
    if len(g) > 300:
        sessions.append(g)


def run(g, start, tp, sl, side):
    """Devuelve (minutos, resultado en pts, cerrado por TP/SL)."""
    g = g[g.index.strftime("%H:%M") >= start]
    entry = g["Open"].iloc[0]
    hi, lo = (g["High"] - entry) * side, (g["Low"] - entry) * side
    if side < 0:
        hi, lo = lo, hi
    hit_tp, hit_sl = (hi >= tp).to_numpy(), (lo <= -sl).to_numpy()
    for i, (a, b) in enumerate(zip(hit_tp, hit_sl)):
        if a or b:
            win = a if a != b else rng.random() < 0.5
            return i + 1, tp if win else -sl, True
    return len(g), (g["Close"].iloc[-1] - entry) * side, False


rows = []
for name, tp, sl in SPECS:
    for si, g in enumerate(sessions):
        for start in STARTS:
            for side in (1, -1):
                mins, pnl, closed = run(g, start, tp, sl, side)
                rows.append((name, si, start, side, mins, pnl, closed))
res = pd.DataFrame(rows, columns=["spec", "session", "start", "side", "mins", "pnl", "closed"])

print(f"NQ 1 min, {len(sessions)} sesiones ({sessions[0].index[0].date()} -> {sessions[-1].index[0].date()}), "
      f"cierre forzoso {CLOSE} NY\n")
print("Duración (min) según la hora de entrada; mediana / p90 / % que no cierra antes de las 15:50")
blocks = {"9:31-10:00": STARTS[:2], "10:01-11:30": STARTS[2:8], "11:31-13:00": STARTS[8:14], "13:01-15:00": STARTS[14:]}
print(f"{'':32}" + "".join(f"{b:>22}" for b in blocks))
for name, *_ in SPECS:
    r = res[res.spec == name]
    cells = []
    for starts in blocks.values():
        x = r[r.start.isin(starts)]
        cells.append(f"{x.mins.median():4.0f} / {x.mins.quantile(.9):4.0f} / {1 - x.closed.mean():4.0%}")
    print(f"{name:32}" + "".join(f"{c:>22}" for c in cells))

print("\nSi se abre un trade nuevo cada X minutos en la MISMA dirección sin esperar al anterior:")
print("correlación entre los resultados de dos trades seguidos (0 = independientes, 1 = el mismo trade)")
for name, tp, sl in SPECS:
    r = res[res.spec == name].set_index(["session", "side", "start"])["pnl"]
    out = []
    for lag in (1, 2, 4):   # 15, 30, 60 min
        a, b = [], []
        for (s, side), grp in r.groupby(level=[0, 1]):
            v = grp.droplevel([0, 1]).reindex(STARTS).to_numpy()
            a += list(v[:-lag])
            b += list(v[lag:])
        a, b = np.array(a), np.array(b)
        ok = np.isfinite(a) & np.isfinite(b)
        out.append(np.corrcoef(a[ok], b[ok])[0, 1])
    print(f"  {name:32} cada 15 min {out[0]:+.2f}   cada 30 min {out[1]:+.2f}   cada 60 min {out[2]:+.2f}")
