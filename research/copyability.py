"""Чи можна повторити цю торгівлю на наших грошах.

Трейдер може бути прибутковим і при цьому непридатним для копіювання. На
Hyperliquid мінімальний ордер — 10$. Якщо наш ризик на угоду 1$, а стоп
трейдера 20%, то потрібний обсяг 5$ — і угода просто не проходить.

Ці числа ми вже заплатили власним досвідом: при 51$ депозиту проходило 38%
угод, решту відсіяв мінімум. Тому copyability рахується не теоретично, а за
тією самою формулою, якою живе бойове дзеркало.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Copyability:
    capital: float
    risk_pct: float
    # Яку частку угод трейдера ми фізично змогли б відкрити.
    passable_share: float | None = None
    # Скільки грошей треба, щоб проходило хоча б три чверті угод.
    required_capital: float | None = None
    median_stop_pct: float | None = None
    round_trip_cost_pct: float = 0.0
    # Скільки з'їдають витрати від середнього руху угоди.
    cost_share_of_move: float | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return bool(self.passable_share and self.passable_share >= 0.5)


def notional_for(capital: float, risk_pct: float, stop_frac: float,
                 cost_frac: float) -> float:
    """Обсяг позиції при постійному ризику.

    Та сама формула, що в дзеркалі: 1R = стоп + витрати, тому обсяг — це
    ризик, поділений на суму обох. Інакше стоп коштував би більше за 1R.
    """
    denominator = stop_frac + cost_frac
    return capital * risk_pct / 100 / denominator if denominator > 0 else 0.0


def assess(stops: list[float], capital: float, risk_pct: float,
           costs) -> Copyability:
    """stops — частки (0.12 = стоп на 12%), по кожній угоді трейдера."""
    cost_frac = (costs.taker_fee_pct * 2 + costs.slippage_pct * 2) / 100
    out = Copyability(capital=capital, risk_pct=risk_pct,
                      round_trip_cost_pct=round(cost_frac * 100, 4))
    if not stops:
        out.notes.append("стопів не видно — оцінити неможливо")
        return out

    ordered = sorted(stops)
    out.median_stop_pct = round(ordered[len(ordered) // 2] * 100, 2)

    passed = sum(
        1 for s in stops
        if notional_for(capital, risk_pct, s, cost_frac) >= costs.min_notional
    )
    out.passable_share = round(passed / len(stops), 4)

    # Скільки треба, щоб проходило 75% угод: беремо стоп на цьому рівні й
    # рахуємо капітал назад із мінімального обсягу.
    index = min(len(ordered) - 1, int(len(ordered) * 0.75))
    wide = ordered[index]
    out.required_capital = round(
        costs.min_notional * (wide + cost_frac) * 100 / risk_pct, 2)

    median = ordered[len(ordered) // 2]
    if median > 0:
        out.cost_share_of_move = round(cost_frac / median * 100, 2)
        if out.cost_share_of_move > 20:
            out.notes.append(
                f"витрати з'їдають {out.cost_share_of_move}% типового руху — "
                "перевага мала б бути дуже великою, щоб це окупити")
    if out.passable_share is not None and out.passable_share < 0.5:
        out.notes.append(
            f"на {capital:.0f}$ проходить лише {out.passable_share*100:.0f}% угод: "
            f"для трьох чвертей потрібно близько {out.required_capital:.0f}$")
    return out
