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

## Plan del día (`fondeos-hoy`)

Aplica la forma de operar recomendada a tus cuentas reales. El estado (`cuentas.yaml`), la contabilidad
(`contabilidad/`) y los planes guardados (`planes/`) son personales y no se suben al repo: viven en la
carpeta `FONDEOS_DATOS` si está definida o, si no, en `OneDrive/Fondeo` (así se comparten entre
ordenadores). El estado se actualiza con las mismas reglas que el motor:

```bash
uv run fondeos-hoy caja 5000                  # caja libre inicial
uv run fondeos-hoy compra lucid 5             # añade evaluaciones (y guarda la compra para los tickets)
uv run fondeos-hoy                            # qué hacer hoy: franjas, TP y stop en puntos, compras, retiros
uv run fondeos-hoy resultado lucid-1 1210     # al terminar: P&L neto de cada cuenta operada
uv run fondeos-hoy retiro lucid-1             # payout pedido (por defecto el máximo permitido)
uv run fondeos-hoy cobro 1800                 # ha llegado el dinero
```

`--fecha AAAA-MM-DD` cambia el día; `--guardar` deja el plan en `planes/`. La contabilidad se lleva con
`compra --eur --ticket`, `gasto`, `cobro`, `ticket` y `resumen AÑO` (gastado frente a cobrado).

Modelo: paseo aleatorio sin deriva (edge configurable), un trade por día con stop/TP fijos,
liquidación en el suelo como stop efectivo, drawdown EOD exacto (Bernoulli) e intradía exacto
(muestreo browniano en tres etapas). Con edge 0 el valor esperado de una cuenta funded nunca supera
el MLL: todo el valor sale de las pérdidas que absorbe la firma.

Precios: `eval_price` es el de lista; `code_price` el del mejor código conocido y `code_reusable`
indica si está verificado que sirve para compras ilimitadas. El dashboard usa por defecto solo los
códigos reutilizables verificados (TPT NOFEE40 y el cupón de FundedNext).

## Despliegue (Streamlit Community Cloud)

- Punto de entrada: `streamlit_app.py`; dependencias: `requirements.txt`; Python 3.12.
- `.cache/` se sube al repo con los cálculos precalculados para que la app cargue al instante.
  Si cambias planes o motor, regenera y vuelve a subirla:
  `rm -rf .cache && uv run fondeos-precalcular && git add -f .cache`
