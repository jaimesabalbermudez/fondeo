# CLAUDE.md

Simulador y planificador para operar cuentas de fondeo de futuros (NQ) con una estrategia breakeven:
sin ventaja de mercado, el valor sale de elegir bien firma, fase y tamaño de cada trade. Todo el
proyecto (código, informes, conversación) está en español.

## Contexto privado

Este repo es público. El contexto personal (bankroll, correo de compras, preferencias, decisiones
pendientes) está en `OneDrive/Fondeo/contexto.md`, junto a los datos (ver abajo). Léelo al empezar si
existe. Nunca subas al repo datos personales, importes reales ni tickets.

## Dónde está cada cosa

- `plans/*.yaml`: reglas ejecutables por plan (lo que lee el motor). `research/firms/*.yaml`: reglas
  investigadas con fuentes, también de planes que aún no se simulan.
- `src/fondeos_sim/`: `engine.py` (evaluación y funded), `market.py` (trade), `optimize.py`
  (estrategia óptima por plan), `portfolio.py` (cartera día a día con bankroll), `recommended.py`
  (la forma de operar recomendada: `Config`), `dashboard.py`, `hoy.py` (plan del día y contabilidad).
- `analysis/NN_*.py` + `reports/*.txt|md`: cada análisis deja su informe.
- `research/apuntes_victor.md`, `research/apuntes_notion.md`: consejos de traders (Victor, Oriol
  Casas, Tradesfera) contrastados con el simulador, con los riesgos de reglas de cada uno.

## Comandos

```bash
uv sync
uv run pytest -q
uv run fondeos-dashboard          # http://localhost:8501
uv run fondeos-hoy                # plan del día con las cuentas reales
uv run fondeos-precalcular        # regenera .cache (lento, ~25 min)
```

La caché (`.cache/`) se invalida con cualquier cambio en `plans/` o en el paquete, salvo `dashboard.py`,
`cli.py` y `hoy.py` (excluidos en `cache.py`). Tras cambiar el motor: `rm -rf .cache`,
`uv run fondeos-precalcular` y `git add -f .cache` (Streamlit Cloud la usa para cargar al instante).

## Datos personales (fuera del repo)

`fondeos-hoy` guarda el estado (`cuentas.yaml`), la contabilidad (`contabilidad/`, con tickets por año)
y los planes (`planes/`) en `FONDEOS_DATOS` si está definida; si no, en `OneDrive/Fondeo` (sincroniza
entre ordenadores); si no, en la raíz del repo (ignorado por Git).

## Forma de operar recomendada (`recommended.py`)

- Cartera: Lucid Flex 50K (DLL) y Tradeify Select Flex 50K desde el inicio (5 evaluaciones a la vez
  cada una); MFFU Rapid EOD 50K y FundedNext Flex 50K al llegar a cierta caja libre.
- Evaluación: 1 NQ, objetivo diario recortado por la consistencia (Lucid/Tradeify: +1.200, 3 días),
  stop = DLL o todo el margen. Funded: un día gordo (prudente de +2.000 con caja < 3.000) y luego
  días verdes (+150, 5 MNQ) hasta el payout.
- Cada cuenta su trade, uno detrás de otro; con caja libre ≥ 10.000, evaluaciones a la vez (misma
  dirección, brackets distintos, ρ≈0,7). Las funded siempre de una en una. ~14 trades por día.
- Horario de Lucas, 13:00–17:00 (España): días verdes en premercado, nada abierto en el dato de las
  14:30, evaluaciones desde la apertura (15:30) y días gordos al final, con stop y TP puestos.
- Reglas que no se pueden saltar: nada de hedging entre cuentas (largo en una y corto en otra),
  Topstep prohíbe el stacking, FundedNext el all-in ("account flipping"), inactividad semanal en
  Tradeify y MFFU.

## Convenciones

- Importes en $ y relativos al balance inicial cuando son offsets; los objetivos de los trades son
  netos de comisiones (fricción $10 por NQ, $8 por 5 MNQ).
- Cualquier cifra que se dé a Lucas sale de una simulación o de un informe del repo, con sus supuestos
  (edge 0, retiros pagados) y, si importa, con el caso de estrés (20% de payouts denegados y 30%
  anual de que cada firma deje de pagar).
