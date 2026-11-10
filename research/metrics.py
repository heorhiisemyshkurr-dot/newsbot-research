"""Метрики ризику з історії вартості рахунку.

ГОЛОВНЕ ПРАВИЛО ЦЬОГО ФАЙЛА: щільність даних визначає, що взагалі можна
порахувати. Hyperliquid віддає історію капіталу так:

    вікно      глибина     одна точка на
    day        1 доба      36 хвилин
    week       7 діб       2.6 години
    month      31 доба     15 годин
    allTime    825 діб     12 ДІБ

Просадка — це найглибше падіння від піку. Виміряти її можна лише там, де
точки частіші за саме падіння. На вікні allTime одна точка на дванадцять
діб: просадка, що сталась і відновилась усередині цього проміжку, у даних
не існує. Тому максимальна просадка береться з вікна `month` і чесно
називається місячною, а не річною.

Нічого не домальовуємо: якщо точок замало — метрика недоступна, і так і
написано. Прочерк чесніший за правдоподібне число.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

DAY_MS = 86_400_000


@dataclass
class EquityMetrics:
    """Усе, що вдалось порахувати з кривої капіталу, і чого не вдалось."""
    points: int = 0
    days: float = 0.0
    start: float = 0.0
    end: float = 0.0
    peak: float = 0.0
    trough: float = 0.0
    roi_pct: float | None = None
    max_drawdown_pct: float | None = None
    drawdown_days: float | None = None
    recovered: bool | None = None
    volatility_pct: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    # Проміжок між точками. Потрібен, щоб знати, наскільки грубий вимір.
    sample_hours: float | None = None
    window: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def measurable(self) -> bool:
        return self.max_drawdown_pct is not None


def _series(portfolio: dict, window: str) -> list[tuple[int, float]]:
    data = (portfolio or {}).get(window) or {}
    out = []
    for item in data.get("accountValueHistory") or []:
        try:
            out.append((int(item[0]), float(item[1])))
        except (TypeError, ValueError, IndexError):
            continue
    out.sort(key=lambda p: p[0])
    return out


def drawdown(values: list[float]) -> tuple[float, int, int]:
    """Найглибше падіння від піку. Повертає (частка, індекс піку, індекс дна)."""
    peak = values[0]
    peak_at = 0
    worst = 0.0
    worst_peak = 0
    worst_at = 0
    for i, v in enumerate(values):
        if v > peak:
            peak, peak_at = v, i
        if peak > 0:
            fall = (peak - v) / peak
            if fall > worst:
                worst, worst_peak, worst_at = fall, peak_at, i
    return worst, worst_peak, worst_at


def analyse(portfolio: dict, window: str = "month",
            min_points: int = 20) -> EquityMetrics:
    """Рахує метрики по одному вікну історії капіталу."""
    series = _series(portfolio, window)
    out = EquityMetrics(window=window, points=len(series))
    if len(series) < 2:
        out.notes.append("історії капіталу немає")
        return out

    times = [t for t, _ in series]
    values = [v for _, v in series]
    out.days = (times[-1] - times[0]) / DAY_MS
    out.start, out.end = values[0], values[-1]
    out.peak, out.trough = max(values), min(values)
    out.sample_hours = round(out.days * 24 / max(1, len(series) - 1), 2)

    if out.start > 0:
        out.roi_pct = round((out.end - out.start) / out.start * 100, 3)

    if len(series) < min_points:
        out.notes.append(
            f"точок {len(series)}, треба щонайменше {min_points} — "
            "просадка не рахується")
        return out

    worst, peak_at, trough_at = drawdown(values)
    out.max_drawdown_pct = round(worst * 100, 3)
    out.drawdown_days = round((times[trough_at] - times[peak_at]) / DAY_MS, 2)
    # Відновлення: чи повернувся капітал до піку після дна.
    after = values[trough_at:]
    out.recovered = bool(after) and max(after) >= values[peak_at]

    # Дохідності між сусідніми точками. Крок нерівномірний, тому це НЕ денні
    # дохідності — і річні коефіцієнти з них не робляться.
    rets = [(b - a) / a for a, b in zip(values, values[1:]) if a > 0]
    if len(rets) >= 3:
        sd = statistics.stdev(rets)
        mean = statistics.fmean(rets)
        out.volatility_pct = round(sd * 100, 4)
        if sd > 0:
            out.sharpe = round(mean / sd, 4)
        downside = [r for r in rets if r < 0]
        if len(downside) >= 2:
            dsd = statistics.stdev(downside)
            if dsd > 0:
                out.sortino = round(mean / dsd, 4)
        out.notes.append(
            "Sharpe і Sortino пораховані на кроці "
            f"{out.sample_hours} год і НЕ приведені до року: крок нерівномірний, "
            "а приведення множило б шум")
    return out


def long_term_shape(portfolio: dict) -> dict:
    """Форма кривої за весь час — як орієнтир, а не як вимір.

    На цьому вікні одна точка на дванадцять діб. Просадку тут рахувати не
    можна, але видно головне: рахунок загалом росте чи загалом падає, і чи
    був він колись набагато більшим, ніж зараз.
    """
    series = _series(portfolio, "allTime")
    if len(series) < 3:
        return {"available": False, "reason": "історії за весь час немає"}
    values = [v for _, v in series]
    times = [t for t, _ in series]
    peak = max(values)
    return {
        "available": True,
        "days": round((times[-1] - times[0]) / DAY_MS, 1),
        "points": len(series),
        "sample_days": round((times[-1] - times[0]) / DAY_MS / max(1, len(series) - 1), 1),
        "start": round(values[0], 2),
        "end": round(values[-1], 2),
        "peak": round(peak, 2),
        # Наскільки рахунок нижчий за свій історичний пік. Це не просадка —
        # це відстань до піку на грубій сітці.
        "below_peak_pct": round((peak - values[-1]) / peak * 100, 2) if peak > 0 else None,
        "warning": "одна точка на 12 діб: просадка між точками не видна",
    }
