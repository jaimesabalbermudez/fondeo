# Apuntes de Notion "Cuentas de Fondeo" (Oriol Casas + Tradesfera) — leídos 2026-11-02

Fuente: [Cuentas de Fondeo](https://app.notion.com/p/Cuentas-de-Fondeo-3fe770a0d4fe80caa2e1da67be5efd9a)
(página pública de Lucas). Esto es un resumen. Al final, cómo encaja con el simulador y con
`apuntes_victor.md`.

## Oriol Casas

**Firmas recomendadas:** Lucid, Alpha, MyFundedFutures, Take Profit, Apex y Tradeify. Por condiciones,
suelen ir en este orden: Lucid > MFFU > Topstep. Las mejores son las 50K, por la relación entre
drawdown y precio de la cuenta. Hay que revisar las FAQ de cada firma.

**Plan:**
- Ser un trader *breakeven* (EV neutro, nunca negativo). Operar al azar sirve. La ventaja está en usar
  el tamaño correcto, en la fase correcta y en la firma correcta.
- En LiveSim, arriesgar todo el drawdown el primer día buscando 2R (~33% WR). Después, sumar 5 días
  verdes de $150 (~80% WR, riesgo de $600, RR de 0,25). Así salen unos 3 retiros.
- Día gordo en bloques, sin copiar: con 3 cuentas funded, ir a por el 2R en la primera; si quiebra,
  reentrar enseguida con la segunda, y así hasta 3 veces. Lo mismo vale para las evaluaciones (en D2,
  mejor varias cuentas ya en +$1.500).
- La mayoría de firmas permiten 5 cuentas como máximo. No ir contra las normas.

**Estrategias:**
1. *Pasar evaluaciones:* 57% WR con 0,75R dos días seguidos; perder la cuenta es el stop. ~33% de pase.
   Tener 3–4 cuentas compradas para el mismo día, tanto en D1 como en D2. Tamaño: 1 NQ.
2. *Día agresivo en LiveSim:* 33% WR con 2R, trade al azar desde desviaciones + stacking. Tamaño:
   1–2 NQ. Importa mucho tener muchos setups.
3. *Sumar días verdes en LiveSim:* ~90% WR con ~0,1R. NQ con 3–5 micros, órdenes en el extremo de un
   rango (sesión europea o *lunch hour*), con DLL de $600–$1.000 o sin stop.

**Dirección:** con *one-timeframing* al alza (el S&P toca el máximo anterior) → solo largos. A la baja →
solo cortos. En rango o desequilibrio → las dos direcciones. Las entradas se colocan como órdenes
limitadas en la *previous value area* (pVA) o en desviaciones, cada una con su TP y SL.

**Stacking (definición):** primera orden en una zona con sentido (pVA), con su TP y SL. Si salta el
stop, otra cuenta ya tiene una orden en ese mismo precio para reentrar, también con su TP y SL. Se
encadena así, hasta unas 3 veces. Las órdenes se pueden dejar puestas e irse de la pantalla.
- **Recomendación clave:** cada reentrada en una firma distinta (Lucid → MFFU → Lucid), nunca en la
  misma. Si todas las cuentas entran al mismo nivel en la misma firma, te banean por copy trading.

## Tradesfera — Módulos 1–5

**M1, el negocio:** las cuentas no van a mercado real y las firmas no están reguladas. Hay que montar un
sistema que siga siendo rentable aunque alguna firma no pague. Solo cuenta el retiro: el saldo funded
son fichas de póker. Hay que retirar rápido mientras una firma paga. Enfoque del granjero: cría
(evaluaciones) → dar leche (funded que retiran) → ciclo.

**M2, matemáticas:**
- Riesgo asimétrico: pierdes el precio del examen y puedes ganar un retiro mucho mayor. Las normas
  deciden si hay asimetría.
- Ratio inverso: el SL virtual es mayor que el TP (5:1 → ~90% WR). Rachas perdedoras cortas, cumple la
  consistencia.
- EV = P(retiro) × retiro medio − P(fracaso) × coste del intento.
- Riesgo de ruina: objetivo <5% (ideal <1%). La palanca principal es el número de intentos, es decir,
  el bankroll. Regla de oro: un bankroll que aguante el doble de tu peor racha.
- P(fondeo) con DD $2k, objetivo $3k y consistencia del 50%: (2/3,5)² ≈ 32,4%. P(retiros) = producto de
  las probabilidades de cada día del colchón.
- P(retiro) = P(fondeo) × P(retiros). Corrección por retiros repetidos: × 1/(1 − P(repetición)).

**M3, bankroll y escalado:** el bankroll da intentos. Unas normas mejores necesitan menos bankroll para
el mismo riesgo de ruina. Mejor escalar en horizontal (más cuentas de 50K) que en vertical. Escalar
solo con beneficios, con riesgo de ruina por debajo del 5% y con 2–3 cuentas que ya hayan retirado.
Bajar de nivel tras una mala racha o si cambian las reglas.

**M4, elegir firma:**
- Comprobar que pagan: Trustpilot, Discord/Telegram, YouTube ("prueba de pago + firma") y
  PayoutJunction.com (pagos on-chain vía Rise).
- Cuanto más drawdown respecto al objetivo, mejor. Tipos de drawdown, de mejor a peor: estático > EOD
  (suele bloquearse al llegar a +DD) > trailing intradía. Ojo al DLL: reduce el margen real de cada día.
- Trampas: fase 2 encubierta (colchón obligatorio antes del primer retiro); el drawdown pasa a
  breakeven tras el primer retiro (con $51k y retiro de $500, el margen cae de $2k a ~$400), así que
  conviene hacer colchones grandes; las financiaciones instantáneas tienen peor EV.
- Días mínimos: ideal 0. Consistencia: ideal sin ella en funded; ≥40% aceptable en evaluación; <30% es
  un desastre. Las noticias suelen estar prohibidas de ±2 a 10 min.
- Payouts: ideal semanal (3–7 días); estándar 15 días; más de 30 días es bandera roja. Split del 80–90%.
  Fijarse en el reembolso del examen y en las comisiones de cobro (Wise, Rise $5–10, banco ~$25, cripto).
- Checklist de 1 a 5 en: fiabilidad, dificultad, estructura y coste, retiros y ROI teórico (>2,5 = 5/5).
  ROI = (evals × P(fondeo) × E(retiros) × pago − coste) / coste. Caso MFFU: 100 evals a $77, 32,65% de
  fondeo, 1 retiro esperado de $800 → ROI 239%.

**M5, sistema (Vicente):**
- Ratio inverso, alta frecuencia (M1/M5 o 15 s; NQ y oro), reglas simples. Asumir que se pierden casi
  todas las cuentas. Evitar swing, dejar correr ganancias y sistemas discrecionales complejos.
- Estocástico (20,5,5) en extremos + niveles horizontales. Entra en dos "balas" **promediando en
  contra** (1 lote + 1 lote si sigue bajando) y cierra todo cuando el estocástico sale de la zona
  extrema. Sin stop por trade: la cuenta es el stop. Con DLL, cierra a mano antes de tocarlo.
- El tamaño es un % del drawdown disponible; cuanto más cerca del objetivo, más pequeño.
- Por fase: en evaluación, agresividad media-alta; en funded antes del retiro, conservador y alta
  probabilidad; tras el primer retiro, vuelta a agresividad normal.

## Contraste con el simulador y con Victor

- **Día gordo + días verdes** (Oriol) = el plan que ya optimiza el motor. Que todo el valor salga antes
  del primer retiro y que el drawdown suba a breakeven al retirar coincide con `RESUMEN.md`, punto 2.
- **Stacking por bloques en vez de copiar** coincide con `reports/evals_a_la_vez.txt`: lo recomendado es
  que cada cuenta haga su propio trade, una detrás de otra, porque copiar (ρ=1) dispara la ruina.
- ⚠️ "Tras fallar es más probable que funcione" no se sostiene con EV neutro: cada reentrada es un trade
  independiente. El stacking sirve para usar varias cuentas el mismo día sin correlación, no para
  mejorar la probabilidad.
- ⚠️ Promediar en contra sin stop (Vicente) es una forma de martingala. Alpha y Apex lo prohíben
  (`RESUMEN.md`); Tradeify lo permite. Victor hace lo contrario: **piramidar a favor**. Ninguna de las
  dos cosas está modelada todavía.
- ⚠️ El stacking en la misma firma lleva a baneos por copy trading, y Topstep prohíbe el *account
  stacking* expresamente.
- Las normas que importan (drawdown EOD, cap alto, consistencia del 40–50%) coinciden en Oriol, Vicente
  y Victor.
- Pendientes nuevos: modelar la promediación en contra y el stacking entre firmas; añadir la comprobación
  de pagos (PayoutJunction, Trustpilot) a `automation/actualizar_reglas.md`.
