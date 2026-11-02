# Apuntes de la conversación con Victor (trader que aplica esta estrategia) — 2026-11-02

Lo que dijo Victor, tal cual lo apuntó Lucas, y al lado cómo encaja con lo que ya sabemos del
simulador (`reports/`) y de las reglas investigadas (`RESUMEN.md`, `firms/*.yaml`).

## 1. Fase de evaluación

**Victor:** ir a muerte con todas las cuentas que puedas; cuantas más a la vez, mejor.

**Contraste con el simulador** (`reports/evals_a_la_vez.txt`, 12 meses, hasta 12 trades/día):

| Bankroll | Una detrás de otra (ruina) | Todas a la vez, mismo trade ρ=1 (ruina) | A la vez, brackets distintos ρ=0,7 (ruina) |
|---|---|---|---|
| $1.000 | 30% | 58% | 46% |
| $2.000 | 8% | 42% | 27% |
| $5.000 | 0,7% | 19% | 6,5% |

- Con bankroll grande, ir a la vez sube la mediana (sobre todo con brackets distintos), que es lo que
  ve Victor. Con bankroll pequeño, multiplica la ruina: el consejo depende del colchón de dinero.
- Si se hace, mejor con brackets distintos entre cuentas (ρ<1) que copiando el mismo trade.

## 2. Fase de retiro (días de hacer colchón)

Objetivo: **diluir la varianza**.

- **Piramidar a favor:** no entra con tamaño máximo de golpe. Empieza con 1 lote y va añadiendo si el
  trade va con momentum, hasta el máximo de lotes permitido.
  - *No modelado aún.* El motor usa un trade con stop/TP fijos y tamaño constante. Con edge 0 piramidar
    no cambia el valor esperado, pero sí la forma de la distribución: pérdidas pequeñas si falla pronto,
    y el día gordo solo se completa si el precio recorre mucho. Pendiente: simularlo en `market.py`.
- **Hedging entre cuentas de distintas empresas** para reducir varianza.
  - ⚠️ Lucid Flex prohíbe expresamente el hedging entre cuentas (`RESUMEN.md`). Revisar en cada firma
    antes de hacerlo: suele ser causa de baneo y de denegar payouts.
- **Stacking:** explicado en los apuntes de Notion de Lucas, resumidos en `apuntes_notion.md`. Consiste
  en reentrar con otra cuenta (de otra firma) justo en el precio donde saltó el stop de la anterior.
  - ⚠️ Topstep prohíbe expresamente el *account stacking*.
- **Cobertura con broker de dinero real:** tras una mala racha, abre en un broker real la posición
  contraria al trade de la cuenta fondeada, dimensionada para recuperar lo gastado en evaluaciones sin
  cobrar.
  - Si el trade funded falla → el broker recupera los costes.
  - Si funciona → día gordo con mucho colchón y muchos retiros de esa cuenta.
  - Lucas aún no tiene claro en qué situación compensa. Con edge 0 la cobertura no crea valor esperado
    (pierde lo mismo que gana la funded, más comisiones). Lo que hace es convertir el resultado binario
    en uno más suave. Compensaría cuando la ruina del bankroll es la restricción que manda. Pendiente:
    modelarlo como opción en `portfolio.py`.

## 3. Otros apuntes

- No sirve de mucho conseguir colchón en todas las cuentas. Compensa en las firmas que, con colchón,
  dejan retirar más veces un máximo concreto.
- Lo óptimo en NQ es buscar **150–200 puntos en un día**. Con 1 NQ ($20/punto) son $3.000–$4.000: el
  objetivo de una 50K o el día gordo entero. Con MNQ ($2/punto), 10 MNQ = 1 NQ.
- Para operar dos cuentas distintas (la suya y la de su mujer) usa una VPS y nunca opera las dos el
  mismo día.
  - ⚠️ Casi todas las firmas exigen que cada cuenta la opere su titular. Operar la de otra persona
    viola los términos aunque se use otra IP.
- Exprimir los retiros al máximo. Cuando te banean, pasas a otras empresas y luego intentas volver. Las
  reglas cambian, así que lo óptimo es ir rotando a las mejores cuentas de cada momento (ver
  `automation/actualizar_reglas.md`).
- Descuentos: los de la academia de Vicente o los de las propias firmas (ver `code_price` /
  `code_reusable` en `plans/`).
- Guardar automáticamente todos los tickets de compra de evaluaciones en un archivo, para desgravar el
  gasto. Pendiente de montar.
- **Normas más importantes:** drawdown **EOD**, el **payout cap más alto** posible y **consistencia del
  40–50%**.
- **Mejores empresas según Victor:** Lucid, Tradeify ("TradeFi" en los apuntes), MyFundedFutures,
  FundedNext y Topstep.
  - Encaja con `RESUMEN.md`: todas tienen drawdown EOD y consistencia del 40–55%. El cap más alto es
    Tradeify ($2.500). Ojo: Topstep prohíbe el stacking, y el plan Flex de MFFU ya no se vende (en
    `plans/` está MFFU Rapid).

## Pendientes derivados

1. Simular piramidar (entrada de 1 lote y añadidos con momentum) frente a tamaño fijo, en el día gordo.
2. Simular la cobertura con broker real tras una racha de evaluaciones perdidas.
3. Automatizar el registro de tickets de compra de evaluaciones, para Hacienda.
