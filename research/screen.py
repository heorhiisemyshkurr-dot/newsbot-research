"""Обов'язкові фільтри й підсумковий бал.

ПОРЯДОК ВАЖЛИВИЙ: спершу фільтри, потім бал. Кандидат, що не пройшов хоч
один обов'язковий фільтр, у підсумок не потрапляє взагалі — хоч би який
високий бал він мав. Інакше бал починає виправдовувати ризик.

І ще одне правило, записане тут навмисно: якщо не пройшов ніхто, підсумок
порожній. Послабити поріг, щоб список не був порожнім, означає підігнати
критерій під відповідь.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Verdict:
    passed: bool
    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append((name, ok, detail))
        if not ok:
            self.passed = False

    @property
    def failures(self) -> list[str]:
        return [f"{name}: {detail}" for name, ok, detail in self.checks if not ok]


def apply(candidate, config) -> Verdict:
    """candidate — словник із метриками, поведінкою й копійованістю."""
    rules = config.screen
    equity = candidate.get("equity") or {}
    copy = candidate.get("copyability") or {}
    behavior = candidate.get("behavior") or {}
    verdict = Verdict(passed=True)

    dd = equity.get("max_drawdown_pct")
    verdict.add(
        "просадка вимірна", dd is not None,
        "історії капіталу замало, щоб порахувати просадку — "
        "це не «добре», це «невідомо»")
    if dd is not None:
        verdict.add("просадка в межах", dd <= rules.max_drawdown_pct,
                    f"{dd:.1f}% при межі {rules.max_drawdown_pct:.0f}%")

    days = equity.get("days") or 0
    verdict.add("історії достатньо", days >= rules.min_history_days,
                f"{days:.0f} діб при потрібних {rules.min_history_days:.0f}")

    points = equity.get("points") or 0
    verdict.add("точок достатньо", points >= rules.min_equity_points,
                f"{points} точок при потрібних {rules.min_equity_points}")

    roi = equity.get("roi_pct")
    verdict.add("не втрачає", roi is not None and roi >= rules.min_net_roi_pct,
                f"{roi}% за вікно" if roi is not None else "дохідність невідома")

    need = copy.get("required_capital")
    verdict.add(
        "вистачає нашого капіталу",
        need is not None and need <= rules.max_required_capital,
        f"потрібно близько {need}$ при наших {rules.max_required_capital:.0f}$"
        if need is not None else "оцінити неможливо")

    flags = behavior.get("flags") or []
    verdict.add("без тривожних ознак", not flags, "; ".join(flags))
    return verdict


def score(candidate, config) -> dict:
    """Прозорий бал 0–100. Кожна складова видна окремо.

    Бал не замінює фільтри: він лише впорядковує тих, хто їх пройшов.
    """
    w = config.scoring
    equity = candidate.get("equity") or {}
    copy = candidate.get("copyability") or {}
    behavior = candidate.get("behavior") or {}
    parts: dict[str, float] = {}

    # Просадка: 0% дає повний бал, межа і глибше — нуль.
    dd = equity.get("max_drawdown_pct")
    limit = config.screen.max_drawdown_pct
    parts["drawdown"] = 0.0 if dd is None else max(0.0, 1 - dd / limit) * w.drawdown

    # Доказовість: скільки історії та скільки точок.
    days = min(1.0, (equity.get("days") or 0) / 30)
    points = min(1.0, (equity.get("points") or 0) / 40)
    parts["evidence"] = (days * 0.5 + points * 0.5) * w.evidence

    # Сталість: дохідність поділена на коливання. Без вікон порівняння
    # нічого складнішого тут чесно не порахувати.
    sharpe = equity.get("sharpe")
    parts["consistency"] = (0.0 if sharpe is None
                            else max(0.0, min(1.0, sharpe / 0.5)) * w.consistency)

    share = copy.get("passable_share") or 0.0
    parts["feasibility"] = share * w.feasibility

    # Ризик вкладення: концентрація в одній монеті й нарощування після збитку.
    conc = behavior.get("concentration")
    esc = behavior.get("escalation_after_loss") or 0.0
    risk = 1.0
    if conc is not None:
        risk -= max(0.0, conc - 0.5)
    risk -= min(0.5, esc)
    parts["exposure"] = max(0.0, risk) * w.exposure

    # Стабільність: відновився після просадки чи ні.
    parts["stability"] = (w.stability if equity.get("recovered") else 0.0)

    total = round(sum(parts.values()), 2)
    return {
        "total": total,
        "parts": {k: round(v, 2) for k, v in parts.items()},
        "max_parts": {
            "drawdown": w.drawdown, "evidence": w.evidence,
            "consistency": w.consistency, "feasibility": w.feasibility,
            "exposure": w.exposure, "stability": w.stability,
        },
    }


def confidence(candidate) -> str:
    """Наскільки взагалі можна вірити цьому рядку.

    Залежить від даних, а не від результату: трейдер із чудовими числами на
    десяти точках заслуговує менше довіри, ніж посередній на сорока.
    """
    equity = candidate.get("equity") or {}
    points = equity.get("points") or 0
    days = equity.get("days") or 0
    complete = (candidate.get("behavior") or {}).get("trades", 0) > 0
    if points >= 40 and days >= 28 and complete:
        return "висока"
    if points >= 25 and days >= 20:
        return "середня"
    return "низька"
