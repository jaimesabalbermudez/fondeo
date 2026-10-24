# Esquema de reglas por firma (research/firms/<firma>.yaml)

Un fichero por firma. Una entrada por plan/modelo de cuenta (p.ej. Flex, Pro). Dentro de cada plan,
datos por tamaño de cuenta (25K/50K/100K/150K) cuando difieren. Prioridad: 50K.

Cada valor numérico o regla debe ir acompañado de su fuente (URL) en `sources` y, si es dudoso,
de una nota en `notes`. Si algo no se encuentra, poner `null` y explicarlo en `unknowns` — NO inventar.

```yaml
firm: Lucid Trading
as_of: 2026-10-24
sources:            # URLs consultadas (help center / FAQ / pricing oficiales primero)
  - https://...
plans:
  - plan: Flex
    sizes:
      50K:
        eval:
          price_usd: 149            # precio de lista
          price_notes: "códigos habituales -XX%"
          billing: one_time         # one_time | monthly
          reset_fee_usd: null
          activation_fee_usd: 0     # al pasar a funded
          profit_target_usd: 3000
          mll:
            amount_usd: 2000
            type: eod_trailing      # eod_trailing | intraday_trailing | static
            lock_balance_usd: 50000 # balance al que el suelo deja de subir (null si no se bloquea)
            breach: realtime        # realtime (intradía) | eod (solo al cierre)
          dll: {amount_usd: null, kind: null}   # kind: breach (pierdes cuenta) | pause (se para el día)
          consistency_pct: 50       # mejor día / profit total máx.; null si no hay
          min_trading_days: 2
          max_days: null
          max_contracts: "4 mini / 40 micro"
        funded:
          mll: {amount_usd: 2000, type: eod_trailing, lock_balance_usd: 50100, breach: realtime}
          mll_after_payout: "qué pasa con el suelo tras cada payout"
          dll: {amount_usd: null, kind: null}
          consistency_pct: null
          payout:
            cycle_requirement: "5 días con >= $150 de profit neto"
            min_profit_to_request_usd: 500
            min_payout_usd: null
            max_payout_per_cycle_usd: 2000   # o lista por nº de payout si es escalonado
            max_pct_of_profit: 50
            buffer_usd: null                 # colchón que debe quedar
            split_pct: 90                    # y escalones si los hay
            frequency: "cada 5 días de trading"
          payouts_before_live: 5
          lifetime_payout_cap_usd: 100000
          scaling_plan: "contratos según profit"
          inactivity_days: 30
        account_limits:
          max_funded_accounts: 5
          max_eval_accounts: null
        strategy_restrictions:       # MUY importante para el plan "arriesgar todo el MLL en 1 trade"
          max_loss_per_trade: null   # p.ej. Apex 30% negative P&L rule
          min_rr_or_profit_rules: null
          min_hold_time / microscalping: null
          news_trading: allowed
          hedging_stacking: "texto exacto o resumen de la norma de account stacking / cross-account hedging"
          copy_trading: allowed
          other: []
    notes: []
    unknowns: []
```
