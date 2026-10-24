"""Reglas de un plan de fondeo, cargadas desde plans/*.yaml.

Todos los importes son en $ y relativos al balance inicial cuando son "offsets" (p.ej. lock_offset=100
significa que el suelo deja de subir en start+100).
"""

from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

DRAWDOWN_TYPES = ("eod", "intraday", "static")


@dataclass(frozen=True)
class PhaseRules:
    mll: float
    drawdown: str = "eod"              # eod | intraday | static
    lock_offset: float | None = None   # el suelo trailing se detiene en start + lock_offset
    dll: float | None = None           # pérdida diaria máxima (pausa el día, no quema la cuenta)
    dll_scale_pct: float | None = None  # por encima del trail inicial (start + mll + lock_offset) el DLL pasa
                                        # a ser este % del mayor profit EOD (LucidScale DLL de Lucid)

    def __post_init__(self):
        if self.drawdown not in DRAWDOWN_TYPES:
            raise ValueError(f"drawdown debe ser uno de {DRAWDOWN_TYPES}: {self.drawdown}")


@dataclass(frozen=True)
class EvalRules(PhaseRules):
    profit_target: float = 3000
    consistency: float | None = None   # mejor día / profit total máximo al pasar
    min_days: int = 1
    max_days: int | None = None


@dataclass(frozen=True)
class PayoutRules:
    split: float = 0.9
    min_green_days: int = 0            # días con P&L >= green_min en el ciclo
    green_min: float = 0
    min_trading_days: int = 0          # días operados en el ciclo
    min_cycle_profit: float = 0        # profit desde el último payout
    consistency: float | None = None   # mejor día del ciclo / profit del ciclo
    buffer: float = 0                  # solo se retira lo que supera start + buffer
    min_amount: float = 0
    max_amount: tuple[float, ...] = (float("inf"),)   # por nº de payout; el último se repite
    pct_of_profit: float | None = None # p.ej. 0.5 = máx. 50% del profit acumulado
    max_payouts: int | None = None     # tras este nº la cuenta pasa a live / se cierra

    def cap(self, k: int) -> float:
        return self.max_amount[min(k, len(self.max_amount) - 1)]


@dataclass(frozen=True)
class FundedRules(PhaseRules):
    floor_after_payout: float | None = None   # offset al que salta el suelo tras un payout (None = no cambia)
    payout: PayoutRules = field(default_factory=PayoutRules)


@dataclass(frozen=True)
class Costs:
    eval_price: float                  # precio de lista (sin códigos)
    billing: str = "one_time"          # one_time | monthly
    reset_price: float | None = None   # si existe y es más barato, los reintentos lo usan
    activation_fee: float = 0
    code_price: float | None = None    # precio con el mejor código conocido
    code_reusable: bool = False        # el código se puede usar en compras ilimitadas (verificado)
    discount: str = ""                 # de dónde sale el código y qué se sabe de él

    def attempt_price(self) -> float:
        return min(self.eval_price, self.reset_price) if self.reset_price else self.eval_price

    def with_price_mode(self, mode: str) -> "Costs":
        """mode: 'lista' | 'verificados' (solo códigos reutilizables verificados) | 'todos'."""
        use = self.code_price is not None and (mode == "todos" or (mode == "verificados" and self.code_reusable))
        return replace(self, eval_price=self.code_price) if use else self


@dataclass(frozen=True)
class Plan:
    id: str
    firm: str
    name: str
    start_balance: float
    costs: Costs
    eval: EvalRules | None             # None = directo a funded
    funded: FundedRules
    max_funded_accounts: int | None = None   # cuentas funded a la vez en este plan
    firm_max_funded: int | None = None       # cuentas funded a la vez en toda la firma (None = el del plan)
    firm_max_open: int | None = None         # evaluaciones + funded a la vez en toda la firma
    firm_max_evals: int | None = None        # evaluaciones a la vez en toda la firma
    firm_max_purchases_30d: int | None = None    # evaluaciones compradas por 30 días naturales
    firm_max_activations_30d: int | None = None  # cuentas funded activadas por 30 días naturales
    hold_passed: bool | None = None          # ¿se puede aparcar una evaluación aprobada? (None = desconocido)
    p_payout_denial: float = 0.0       # prob. de que la firma anule los payouts (reglas anti-estrategia)
    notes: tuple[str, ...] = ()

    @property
    def all_eod(self) -> bool:
        """Condición deseada: ningún drawdown intradía (el suelo no persigue el P&L no realizado)."""
        phases = [p for p in (self.eval, self.funded) if p is not None]
        return all(p.drawdown != "intraday" for p in phases)

    def with_price_mode(self, mode: str) -> "Plan":
        return replace(self, costs=self.costs.with_price_mode(mode))


def _payout(d: dict) -> PayoutRules:
    d = dict(d)
    if "max_amount" in d:
        m = d["max_amount"]
        d["max_amount"] = tuple(float("inf") if x is None else float(x) for x in (m if isinstance(m, list) else [m]))
    return PayoutRules(**d)


def load_plan(path: str | Path) -> Plan:
    d = yaml.safe_load(Path(path).read_text())
    funded = dict(d["funded"])
    funded["payout"] = _payout(funded.get("payout", {}))
    return Plan(
        id=d["id"],
        firm=d["firm"],
        name=d["name"],
        start_balance=float(d.get("start_balance", 50_000)),
        costs=Costs(**d["costs"]),
        eval=EvalRules(**d["eval"]) if d.get("eval") else None,
        funded=FundedRules(**funded),
        max_funded_accounts=d.get("max_funded_accounts"),
        firm_max_funded=d.get("firm_max_funded"),
        firm_max_open=d.get("firm_max_open"),
        firm_max_evals=d.get("firm_max_evals"),
        firm_max_purchases_30d=d.get("firm_max_purchases_30d"),
        firm_max_activations_30d=d.get("firm_max_activations_30d"),
        hold_passed=d.get("hold_passed"),
        p_payout_denial=float(d.get("p_payout_denial", 0.0)),
        notes=tuple(d.get("notes", [])),
    )


def load_plans(directory: str | Path) -> list[Plan]:
    return [load_plan(p) for p in sorted(Path(directory).glob("*.yaml"))]
