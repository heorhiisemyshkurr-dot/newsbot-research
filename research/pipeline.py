"""Три ступені відбору, від дешевого до дорогого.

Чому саме так. Лідерборд — один запит на 47 тисяч трейдерів. Історія
капіталу — один запит на кожного. Історія угод — десятки запитів на кожного.
Якщо не відсіювати між ступенями, ми впремося в ліміт біржі на першій сотні
й не дізнаємось нічого ні про кого.

    47 000  ->  лідерборд          один запит
       300  ->  капітал і просадка один запит на трейдера
        20  ->  угоди й поведінка  десятки запитів на трейдера
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import behavior as behavior_mod
from . import copyability as copy_mod
from . import metrics as metrics_mod
from . import positions as positions_mod
from . import screen as screen_mod

DAY_MS = 86_400_000


@dataclass
class Scan:
    """Чесний облік того, що сталося зі скануванням."""
    discovered: int = 0
    shortlisted: int = 0
    analysed: int = 0
    excluded: dict[str, int] = field(default_factory=dict)
    errors: int = 0
    started: float = field(default_factory=time.time)

    def exclude(self, reason: str) -> None:
        self.excluded[reason] = self.excluded.get(reason, 0) + 1

    @property
    def seconds(self) -> float:
        return round(time.time() - self.started, 1)


def _window(row: dict, name: str) -> dict:
    for window, data in row.get("windowPerformances") or []:
        if window == name:
            return data or {}
    return {}


def discover(source, config, scan: Scan) -> list[dict]:
    """Перший ступінь: відсів по лідерборду, без жодного зайвого запиту.

    Відсіюємо за поведінкою, а не за прибутком: оборот до розміру рахунку
    відрізняє людину від маркет-мейкера, чиї входи скопіювати неможливо
    фізично. Прибуток тут теж є, але він не критерій відбору, а межа знизу —
    інакше ми відбирали б найяскравіших, а не найспокійніших.
    """
    rows = source.leaderboard()
    scan.discovered = len(rows)
    rules = config.universe
    out = []
    for row in rows:
        address = (row.get("ethAddress") or "").lower()
        try:
            account = float(row.get("accountValue") or 0)
        except (TypeError, ValueError):
            scan.exclude("невідомий розмір рахунку")
            continue
        if not address or account < rules.min_account_value:
            scan.exclude("рахунок замалий")
            continue
        month = _window(row, "month")
        try:
            volume = float(month.get("vlm") or 0)
            pnl = float(month.get("pnl") or 0)
            roi = float(month.get("roi") or 0)
        except (TypeError, ValueError):
            scan.exclude("невідомі показники місяця")
            continue
        turnover = volume / account if account else 0.0
        if turnover < rules.min_turnover:
            scan.exclude("майже не торгує")
            continue
        if turnover > rules.max_turnover:
            scan.exclude("оборот як у маркет-мейкера")
            continue
        out.append({
            "address": address,
            "name": row.get("displayName"),
            "account_value": round(account, 2),
            "month_pnl": round(pnl, 2),
            "month_roi": round(roi, 4),
            "month_turnover": round(turnover, 2),
        })

    # Сортуємо до СЕРЕДИНИ дозволеної смуги обороту, а не до її низу.
    #
    # Перша версія брала найменший оборот — і витягувала найнеактивніших, у
    # яких за десять діб немає жодної закритої позиції. Вивчати їх неможливо:
    # дорогий ступінь повертав нулі, і це виглядало як «нічого не знайшли»,
    # хоча насправді ми самі відібрали тих, про кого нічого не дізнатись.
    middle = (rules.min_turnover + rules.max_turnover) / 2
    out.sort(key=lambda c: (-(c["month_roi"] > 0), abs(c["month_turnover"] - middle)))
    shortlist = out[: rules.shortlist]
    scan.shortlisted = len(shortlist)
    return shortlist


def study_equity(source, config, candidates: list[dict], scan: Scan) -> list[dict]:
    """Другий ступінь: історія капіталу й просадка. Один запит на трейдера."""
    out = []
    for candidate in candidates:
        try:
            portfolio = source.portfolio(candidate["address"])
        except Exception as error:                      # мережа, ліміт, що завгодно
            scan.errors += 1
            scan.exclude(f"запит капіталу не вдався: {type(error).__name__}")
            continue
        equity = metrics_mod.analyse(portfolio, "month", config.screen.min_equity_points)
        candidate["equity"] = equity.__dict__ | {"measurable": equity.measurable}
        candidate["long_term"] = metrics_mod.long_term_shape(portfolio)
        out.append(candidate)
        scan.analysed += 1
    return out


def study_fills(source, config, candidates: list[dict], scan: Scan,
                days: int = 14) -> list[dict]:
    """Третій ступінь: угоди, поведінка й копійованість. Дорогий.

    Чотирнадцять діб, а не більше: сторінка віддає 2000 виконань, і в
    активного трейдера це дві доби. Просити 180 означає сотні запитів на
    одного — ліміт біржі закінчиться раніше за наше терпіння.
    """
    since = int(time.time() * 1000) - days * DAY_MS
    for candidate in candidates:
        try:
            fills, complete = source.fills(candidate["address"], since)
        except Exception as error:
            scan.errors += 1
            candidate["behavior"] = {"flags": [], "notes": [
                f"історію угод не вдалося зібрати: {type(error).__name__}"]}
            candidate["copyability"] = {}
            continue
        behavior = behavior_mod.from_fills(fills, complete)
        candidate["behavior"] = behavior.__dict__
        candidate["fills_window_complete"] = complete

        # Стопів у чужих угодах не видно: біржа не каже, де трейдер його
        # ставив. Беремо натомість фактичний розкид ціни входу до виходу —
        # це найближче, що є до «наскільки далеко треба терпіти».
        moves = _moves(fills)
        candidate["copyability"] = copy_mod.assess(
            moves, config.capital, 2.0, config.costs).__dict__
    return candidates


def _moves(fills: list[dict]) -> list[float]:
    """Наскільки далеко ходить ціна в закритих ПОЗИЦІЯХ трейдера.

    Не з виконань: один ордер розбивається на десятки фіксацій, і рахувати
    рух по них означає рахувати уламки. Стоп трейдера нам невидимий — біржа
    не каже, де він його ставив, — тому беремо фактичний результат позиції
    відносно її обсягу. Це найближче, що є до «наскільки далеко треба
    терпіти, щоб повторити цю угоду».
    """
    return [p.move_frac for p in positions_mod.build(fills) if p.move_frac > 0]


def rank(candidates: list[dict], config) -> tuple[list[dict], list[dict]]:
    """Повертає (ті, хто пройшов усі фільтри; усі з поясненням чому ні)."""
    everyone = []
    for candidate in candidates:
        verdict = screen_mod.apply(candidate, config)
        candidate["screen"] = {
            "passed": verdict.passed,
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in verdict.checks],
            "failures": verdict.failures,
        }
        candidate["score"] = screen_mod.score(candidate, config)
        candidate["confidence"] = screen_mod.confidence(candidate)
        everyone.append(candidate)
    passed = [c for c in everyone if c["screen"]["passed"]]
    passed.sort(key=lambda c: -c["score"]["total"])
    everyone.sort(key=lambda c: -c["score"]["total"])
    return passed, everyone
