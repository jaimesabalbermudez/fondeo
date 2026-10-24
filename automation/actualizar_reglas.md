# Rutina: actualizar las reglas de las firmas

Instrucciones para el agente que se ejecuta cada 3 días. Trabajas sobre el repositorio `fondeo`
(simulador de estrategias para cuentas de fondeo de futuros). Escribe en español.

## Objetivo

Comprobar online si han cambiado las condiciones de las firmas y, si es así, actualizar los datos con
su fuente y abrir un pull request. Si nada ha cambiado, no abras PR.

## Ficheros

- `research/firms/<firma>.yaml`: investigación completa por firma, con `sources`, `notes` y `unknowns`.
  Formato en `research/SCHEMA.md`. Las URLs de `sources` son el punto de partida.
- `plans/<plan>.yaml`: los parámetros que usa el motor (un plan de 50K por fichero). Son los que importan.
- Valores a vigilar en cada plan: precio de lista, precio con código y si el código es reutilizable,
  reset, activación, objetivo, MLL y tipo de drawdown (EOD/intradía), DLL, consistencia, días mínimos,
  requisitos de payout (días verdes, mínimo/máximo, % del profit, colchón, split, nº de payouts),
  límites de cuentas (funded por plan y por firma, abiertas, compras/activaciones por 30 días) y
  reglas que afecten a la estrategia (`p_payout_denial`: prohibiciones del "todo o nada", gambling, etc.).

## Reglas

1. Fuentes oficiales primero (help center, página de precios, términos). Un dato de terceros solo
   cuenta si lo confirman dos fuentes independientes recientes; márcalo como "terceros" en las notas.
2. No cambies un valor por una sospecha. Si algo es dudoso, déjalo como está y explícalo en el PR.
3. Cada cambio lleva su URL y la fecha de consulta (en `sources` / `notes` del YAML de research y en
   `notes` del plan). Actualiza `as_of` en los ficheros de research que hayas revisado.
4. No toques el motor (`src/`) ni los tests, salvo que una regla nueva no se pueda representar; en ese
   caso no la implementes: descríbela en el PR como pendiente.
5. Las firmas recomendadas (Lucid DLL, Tradeify, MFFU Rapid EOD, FundedNext) tienen prioridad. Si una
   firma pasa a prohibir la estrategia o a drawdown intradía, dilo al principio del PR en negrita.

## Si hay cambios

```bash
uv sync
uv run python -c "from fondeos_sim.recommended import all_plans_ranked as r; [print(x.plan.id, round(x.ev_attempt), f'{x.roi:+.0%}') for x in r()]"  # antes (en main)
# ... editar YAMLs ...
uv run pytest -q                                   # deben pasar todos
rm -rf .cache && uv run fondeos-precalcular        # regenera la caché que usa la app desplegada
git checkout -b reglas/$(date +%Y-%m-%d)
git add -A && git add -f .cache
git commit -m "Actualizar reglas de las firmas ($(date +%Y-%m-%d))"
git push -u origin HEAD
```

Abre un PR contra `main` titulado `Reglas de las firmas: <fecha>` con:
- Tabla de cambios: firma · plan · campo · antes → después · fuente.
- Impacto: EV por intento y ROI de cada plan antes y después (salida de `fondeos-precalcular`).
- Dudas y reglas no representables.

Termina con un resumen breve de lo revisado (también si no había cambios).
