# Resumen de reglas (cuentas 50K) — investigado 2026-10-24

Detalle completo y fuentes en `firms/*.yaml`. Verificado a mano contra la fuente oficial: Lucid Flex
(payouts, drawdown), Topstep (payout policy), Alpha (prohibited practices).

## Compatibilidad con el plan "arriesgar todo el MLL en un trade"

| Firma / plan | Precio 50K | Eval | Funded | Payout | ¿Plan permitido? |
|---|---|---|---|---|---|
| **Lucid Flex** | $115 (DLL on) / $165 (off), códigos 30–50% (precios de terceros) | T $3k, MLL $2k EOD, lock $50.100; **consistencia 40%** (50% pagando extra) | Sin DLL (opcional), sin consistencia | 5 días ≥$150; 50% del profit hasta $2k; mín $500; 90%; 5 payouts → live | **Sí.** Sin límite por trade; solo prohíbe hedging entre cuentas |
| **Tradeify Select Flex** | $165 (reset $109) | T $3k, MLL $2k EOD, consistencia 40%, 3 días | Sin DLL ni consistencia | 5 días ≥$150; 50% hasta **$2.500**; 90% | **Sí.** Martingala permitida explícitamente |
| **MFFU Flex** | ya no se vende (legacy) | — | — | 50% hasta $2k, **80%** | — |
| **Topstep** | $49/mes + $149 activación (o $95/mes) | T $3k, MLL $2k EOD, mejor día ≤55% | Sin DLL (opcional) | 5 días ≥$150; 50% hasta $2k; 90% | **No.** Prohíbe expresamente el *account stacking* |
| **Alpha Standard/Zero** | $129–139/mes | T $3k, MLL $2k | DLL $1k + consistencia 40% | 5 días ≥$200; 90% | **No.** Prohíbe "todo o nada" y apalancamiento máximo en una posición |
| **Apex EOD** | $590 de lista (hasta −90%) + $129 activación | T $3k, MLL $2k | DLL $1k, consistencia 50%, colchón $52.100 | 5 días ≥$250; $1,5k→$3k; 100%; 6 payouts y se cierra | **No.** Prohíbe usar el umbral completo como stop |
| **FundedNext Flex** | $142 ($75 con cupón) | T $2,5k, **MLL $1,5k**, consistencia 40% | Sin DLL ni consistencia | 5 días ≥$200; 50% hasta $1,5k; **95%**; cierra tras 5 | **Dudoso.** "Account flipping" pone de ejemplo un trade all-in |
| **Take Profit Trader** | $170/mes + $130 activación (promo: −40% y sin activación) | T $3k, MLL $2k EOD, 50%, 3 días | **Drawdown intradía**, colchón $52k | Diario, 100% de lo que pase del colchón; **80%** | Sin restricción explícita; el drawdown intradía penaliza |

## Cambios respecto al comparador y el plan del curso

1. **Lucid Flex, consistencia del 40% en la evaluación** (antes 50%). El plan de 2 días × $1.500 ya no cumple
   salvo que pagues el extra del 50%. Con 40% hacen falta ≥3 días (p. ej. $1.200 + $1.200 + $600).
2. **El suelo salta al balance inicial (+$100) en el primer payout** en Lucid Flex, Tradeify, FundedNext,
   MFFU y Topstep, aunque todavía no se hubiera bloqueado. A partir de ese momento la firma ya no absorbe
   pérdidas. Todo el valor esperado se genera antes del primer payout, lo que refuerza el día gordo.
3. **El suelo también se bloquea en la evaluación** (Lucid: EOD > $52.100 → suelo $50.100), y eso ayuda
   en el 3er día.
4. Precios: el $91 del curso es Lucid con código; los precios de lista actuales son $115/$165.
