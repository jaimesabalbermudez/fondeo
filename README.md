# fondeos-sim

Simulador y optimizador de estrategias breakeven para cuentas de fondeo de futuros.

- `research/`: reglas investigadas por firma, con fuentes (`firms/*.yaml`, `RESUMEN.md`).
- `plans/`: reglas ejecutables por plan (lo que lee el motor). Cada asunción va en `notes`.
- `src/fondeos_sim/`: `plan.py` (esquema), `market.py` (modelo de trade), `engine.py` (simulación),
  `optimize.py` (búsqueda de estrategia y métricas), `portfolio.py` (bankroll y cartera día a día, con trades independientes o copiados entre cuentas),
  `dashboard.py`, `cli.py`.
- `tutorial/`: herramientas HTML del curso (referencia, no se modifican).
- `analysis/`: auditorías puntuales.

```bash
uv run fondeos-dashboard                        # dashboard interactivo en http://localhost:8501
uv run pytest                                   # validación contra resultados analíticos
uv run fondeos-sim                              # ranking de todos los planes -> reports/ranking.md
uv run fondeos-sim --solo-eod                   # solo planes sin drawdown intradía
uv run fondeos-sim --objetivo-funded per_day    # optimiza valor por día de hueco funded
uv run fondeos-sim --denegacion 0.3             # fuerza una prob. de payout denegado en todos
uv run fondeos-sim --friccion 10 10 8           # $ por trade: evaluación, día gordo, días verdes
```

Modelo: paseo aleatorio sin deriva (edge configurable), un trade por día con stop/TP fijos,
liquidación en el suelo como stop efectivo, drawdown EOD exacto (Bernoulli) e intradía exacto
(muestreo browniano en tres etapas). Con edge 0 el valor esperado de una cuenta funded nunca supera
el MLL: todo el valor sale de las pérdidas que absorbe la firma.

Precios: `eval_price` es el de lista; `code_price` el del mejor código conocido y `code_reusable`
indica si está verificado que sirve para compras ilimitadas. El dashboard usa por defecto solo los
códigos reutilizables verificados (TPT NOFEE40 y el cupón de FundedNext).
