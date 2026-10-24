"""¿Tiene ventaja operar en la dirección del gap de apertura del Nasdaq?

Señal: si el Nasdaq-100 abre (9:30 ET) por encima del cierre anterior -> comprar; por debajo -> vender.
Se mide el movimiento apertura -> cierre del mismo día en la dirección de la señal, y se traduce al
parámetro `edge` del motor (prob. extra de llegar al TP antes que al SL) con un movimiento browniano
con deriva: P(TP antes que SL) ≈ SL/(TP+SL) + θ·TP·SL / (2·(TP+SL)), con θ = 2μ/σ² (por punto).

Datos: ^NDX diario de Yahoo Finance (`uv run --with yfinance python analysis/05_senal_gap.py`).
"""

import numpy as np
import yfinance as yf

d = yf.download("^NDX", period="max", interval="1d", progress=False, auto_adjust=False)
d.columns = d.columns.get_level_values(0)
o, c = d["Open"].to_numpy(), d["Close"].to_numpy()
prev = np.r_[np.nan, c[:-1]]
gap = o / prev - 1
ok = np.isfinite(gap) & (np.abs(gap) > 1e-6) & (o != c)   # descarta días con apertura = cierre previo (datos viejos)
years = d.index.year.to_numpy()

print(f"Datos: {d.index[0].date()} -> {d.index[-1].date()}, {ok.sum()} días válidos\n")
print(f"{'Periodo':<11} {'días':>5} {'acierto':>8} {'μ pts':>7} {'t':>6} {'σ pts':>7} | edge en trade 50/100 pts"
      f"  edge en trade 200/50 pts")
for lo, hi in ((1985, 1999), (2000, 2009), (2010, 2019), (2020, 2026), (2021, 2026), (1985, 2026)):
    m = ok & (years >= lo) & (years <= hi)
    if m.sum() < 50:
        continue
    r = (c - o)[m]                          # apertura -> cierre, en puntos del índice
    s = np.sign(gap[m]) * r                 # en la dirección del gap
    mu, sd = s.mean(), r.std()
    t = mu / (s.std() / np.sqrt(len(s)))
    th = 2 * mu / sd**2

    def edge(tp, sl):
        return th * tp * sl / (2 * (tp + sl))

    print(f"{lo}-{hi:<6} {m.sum():>5} {(s > 0).mean():>8.1%} {mu:>7.2f} {t:>6.2f} {sd:>7.1f} | "
          f"{edge(50, 100):>+21.2%}  {edge(200, 50):>+21.2%}")

print("\nLectura: |t| < 2 = indistinguible del azar. Un edge de +1% en un trade 50/100 sube la prob. de acierto "
      "de 66,7% a 67,7%.")
