"""Volatilidad del NQ por franja horaria y tiempo medio que tarda cada tipo de trade en resolverse.

Sin ventaja (movimiento browniano sin deriva), P(TP antes que SL) no depende de la volatilidad; el tiempo
medio hasta tocar TP o SL sí: E[T] = TP·SL / σ² (puntos y minutos). Datos: NQ=F en velas de 5 min,
últimos 60 días (`uv run --with yfinance python analysis/06_horario.py`).
"""

import numpy as np
import yfinance as yf

d = yf.download("NQ=F", period="60d", interval="5m", progress=False)
d.columns = d.columns.get_level_values(0)
d = d.tz_convert("America/New_York")
r = d["Close"].diff()
r = r[(d.index.to_series().diff() == np.timedelta64(5, "m")).to_numpy()]
df = r.to_frame("r")
df["slot"] = df.index.strftime("%H:%M")
v = df.groupby("slot")["r"].agg(lambda x: np.sqrt((x ** 2).mean() / 5))   # puntos por √minuto

WINDOWS = [("04:00", "09:25", "Pre 4:00-9:30"), ("09:30", "09:55", "Apertura 9:30-10:00"), ("10:00", "10:55", "10:00-11:00"),
           ("11:00", "13:55", "11:00-14:00"), ("14:00", "15:25", "14:00-15:30"), ("15:30", "15:55", "Cierre 15:30-16:00"),
           ("18:00", "23:55", "Noche")]
TRADES = [("Eval Lucid +1200/-1200, 1 NQ", 60, 60), ("Eval MFFU +900/-2000, 1 NQ", 45, 100),
          ("Gordo +8000/-2000, 2 NQ", 200, 50), ("Gordo prudente +2000/-2000, 2 NQ", 50, 50),
          ("Verde +150/-600, 5 MNQ", 15, 60)]

print(f"NQ {d.index[0].date()} -> {d.index[-1].date()} (último {d['Close'].iloc[-1]:.0f})\n")
sig = []
print("Volatilidad por franja (hora de Nueva York), puntos por raíz de minuto:")
for a, b, name in WINDOWS:
    s = v[(v.index >= a) & (v.index <= b)].mean()
    sig.append(s)
    print(f"  {name:<20} {s:5.1f}")
print("\nTiempo medio hasta TP o SL (minutos):")
print(" " * 36 + "".join(f"{n.split()[0]:>10}" for *_, n in WINDOWS))
for name, tp, sl in TRADES:
    print(f"  {name:<34}" + "".join(f"{tp * sl / s ** 2:10.0f}" for s in sig))
