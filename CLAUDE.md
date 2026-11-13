# CLAUDE.md

Simulador y planificador para operar cuentas de fondeo de futuros (NQ) con una estrategia breakeven:
sin ventaja de mercado, el valor sale de elegir bien firma, fase y tamaño de cada trade. Todo el
proyecto (código, informes, conversación) está en español.

## Contexto privado

Este repo es público y lo pueden usar varias personas, cada una con sus propias cuentas (a su nombre,
desde su ordenador y su conexión). El contexto de cada persona (quién es, bankroll, horario, correo de
compras, decisiones pendientes) está en `contexto.md`, dentro de su carpeta de datos (ver abajo).

Al empezar, ejecuta `uv run fondeos-hoy datos`: dice qué carpeta de datos se usa en este ordenador y si
hay `contexto.md`. Si existe, léelo. Si no existe, pregunta a la persona lo básico (nombre, bankroll,
horario, correo con el que compra, firmas que usa) y créalo ahí. Nunca mezcles los datos de dos personas
ni operes o registres por una persona en las cuentas de otra. Nunca subas al repo datos personales,
importes reales ni tickets.

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

`fondeos-hoy` guarda el contexto (`contexto.md`), el estado (`cuentas.yaml`), la contabilidad
(`contabilidad/`, con tickets por año) y los planes (`planes/`) en `FONDEOS_DATOS` si está definida;
si no, en `OneDrive/Fondeo` del usuario de ese ordenador (sincroniza entre sus ordenadores); si no, en
la raíz del repo (ignorado por Git). Si el OneDrive acaba de iniciarse, espera a que `Fondeo` termine
de sincronizar antes de registrar nada, o OneDrive creará copias en conflicto.

## Forma de operar recomendada (`recommended.py`)

- Cartera: se empieza solo con Lucid Flex 50K (DLL, consistencia 50%: 10 cuentas, el máximo por hogar);
  Tradeify Select Flex 50K (5) con caja libre ≥ 6.000 $; MFFU Rapid EOD 50K (3) y FundedNext Flex 50K
  (5) con ≥ 10.000 $. Con cuatro firmas la ruina con estrés baja de ~27% a ~10% (simulación 2026-11-04).
- Evaluación: 1 NQ, objetivo diario recortado por la consistencia (Lucid/Tradeify: +1.200, 3 días),
  stop = DLL o todo el margen. Funded: un día gordo (prudente de +2.000 con caja < 3.000) y luego
  días verdes (+150, 5 MNQ) hasta el payout.
- Cada cuenta su trade, uno detrás de otro; con caja libre ≥ 10.000, evaluaciones a la vez (misma
  dirección, brackets distintos, ρ≈0,7). Las funded siempre de una en una. ~14 trades por día.
- Horario por defecto, 13:00–17:00 (España): días verdes en premercado, nada abierto en el dato de las
  14:30, evaluaciones desde la apertura (15:30) y días gordos al final, con stop y TP puestos.
- Cierres: el "Daily Wire" de Lucid trae VARIAS cuentas en un mismo correo (el 4-nov, 5 por correo).
  Se registra entero con `fondeos-hoy daily-wire <archivo con el texto del correo>`, nunca a mano
  cuenta a cuenta (así se perdieron 8 cierres el 4-nov). El Daily Wire NO trae las cuentas que ese día
  aprueban o se pierden (11-nov: 3 aprobadas y 1 perdida faltaban): después hay que cuadrar con el panel,
  `fondeos-hoy --fecha <día> panel <archivo con el texto del panel, tipo y estado en "All">`, que marca
  las BREACHED, pasa a funded las "You've passed the evaluation!", corrige balances y asocia por orden los
  números LFF de las funded recién activadas. La consistencia del 50% tiene tolerancia: el 11-nov
  aprobaron cuentas con el mejor día al 50,2% del total.
- Panel de Lucid (https://dash.lucidtrading.com/#/account-summary, sesión iniciada por Lucas en el
  navegador integrado; nunca escribir credenciales): una tarjeta por cuenta con tipo (EVAL/FUNDED),
  número, estado ACTIVE o BREACHED (perdida: Lucid no lo avisa por correo), ACCOUNT BALANCE / suelo,
  PROFIT TARGET (con su consistencia) y "$X left". Una evaluación aprobada dice "You've passed the
  evaluation!" con el botón "Upgrade to Funded": la funded no existe hasta que Lucas lo pulsa (Claude no
  lo pulsa) y tendrá un número nuevo, que hay que asociar con `fondeos-hoy numero`.
- Límite de fondeadas (Lucid, revisado en su web el 2026-11-05): 10 cuentas por hogar sumando
  evaluaciones y fondeadas, 5 fondeadas como máximo; se pueden tener 5 evaluaciones "en reserva" con 5
  fondeadas. Lucid no dice qué pasa si apruebas con las 5 fondeadas ocupadas, así que `fondeos-hoy` deja
  esas evaluaciones en espera (no se operan) y con huecos libres solo deja hacer el trade final a tantas
  como huecos. Inactividad: un trade con al menos ±1 $ de P&L neto cada 30 días naturales (si no, la
  borran). Al pasar a live (tras retiros), Lucid cierra TODAS las cuentas simuladas, también las
  evaluaciones en reserva: con una fondeada a un retiro del máximo no se compran más evaluaciones.
  Tradeify también cierra todo al pasar a Elite Live (tras 3 retiros en una cuenta o 10 en total).
- Riesgo de payouts denegados por el patrón de la funded (aviso, la estrategia NO se cambia): en
  nov-2026 The Trading Pit denegó un payout a un trader conocido por "rotación de cuentas" (Anexo B y
  cláusulas 6.5.1/6.7 de sus T&C): día 1 con posición desproporcionada usando todo el drawdown (+3.974 $,
  el 82% del beneficio), luego un trade al día de ~+215 $ solo para cumplir los 5 días de +150 $. Anularon
  el trade ganador, denegaron el pago y avisaron de cerrar todas sus cuentas si se repite. Es exactamente
  nuestro día gordo + días verdes. Lucid y Tradeify no lo prohíben en sus normas publicadas (sin límite de
  pérdida por trade; Tradeify permite la martingala), pero ambas tienen revisión discrecional de payouts y
  no se han leído sus T&C completos. Si una firma deniega o avisa por esto: no repetir el patrón en esa
  firma y pasar sus funded a riesgo constante. Simulación del 2026-11-06 (Lucid Flex 50K, funded): actual
  1.136 $ por funded, +265 $ por evaluación; riesgo constante 1 NQ +800/−800 al día 650 $ y +113 $;
  5 MNQ +500/−500, 584 $ y +92 $; verdes simétricos +150/−150 ya no compensan (−2 $). El riesgo
  constante gana más si la probabilidad de denegación del patrón actual supera ~45%.
- Reglas que no se pueden saltar: nada de hedging entre cuentas (largo en una y corto en otra),
  Topstep prohíbe el stacking, FundedNext el all-in ("account flipping"), inactividad semanal en
  Tradeify y MFFU. Cada cuenta la opera su titular; entre personas, nada de trades coordinados
  (el mismo trade a la vez o direcciones opuestas), ni pagos ni cobros cruzados.

## Convenciones

- Al nombrar una cuenta para operarla, di su fase y los últimos 3 dígitos del número de la firma
  ("EVAL 009", "FUNDED 001"), como hace `fondeos-hoy` (`hoy.label`), no solo el id interno (lucid-9):
  es lo que se ve en la plataforma y varias cuentas acaban igual (LFE…001 evaluación y LFF…001 funded).

- Importes en $ y relativos al balance inicial cuando son offsets; los objetivos de los trades son
  netos de comisiones (fricción $10 por NQ, $8 por 5 MNQ).
- Cualquier cifra que se dé sale de una simulación o de un informe del repo, con sus supuestos
  (edge 0, retiros pagados) y, si importa, con el caso de estrés (20% de payouts denegados y 30%
  anual de que cada firma deje de pagar).
