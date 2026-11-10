"""Усі числа дослідження в одному місці.

Правило: жодного порога в коді модулів. Якщо щось можна підкрутити — воно
тут, і видно, що саме підкрутили.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE.parent / "research.db"
DEFAULT_CACHE = HERE.parent / "research-cache"


@dataclass
class Limits:
    """Скільки й як часто можна питати біржу.

    Hyperliquid рахує не запити, а їхню вагу, і при перевищенні відповідає
    429. Ми вже на цьому обпікались: розрахунок метрик залпом вибивав ліміт
    так, що ЖИВЕ дзеркало переставало відкривати угоди. Тому дослідження
    навмисно повільніше, ніж могло б бути.
    """
    requests_per_minute: int = 60
    retries: int = 4
    backoff_sec: float = 2.0
    timeout_sec: float = 40.0


@dataclass
class Universe:
    """Хто взагалі розглядається."""
    # Менше — це вже не трейдер, а гаманець: одна-дві угоди на все життя.
    min_account_value: float = 10_000.0
    # Обіг за місяць до розміру рахунку. Нижче — спить, вище — маркет-мейкер
    # або бот, чиї входи скопіювати неможливо фізично.
    min_turnover: float = 1.0
    max_turnover: float = 15.0
    # Скільки кандидатів тягнути на другий, дорогий ступінь.
    shortlist: int = 300


@dataclass
class Screen:
    """Обов'язкові фільтри. Не пройшов хоч один — не потрапляє в підсумок.

    ПРО ПРОСАДКУ ЧЕСНО. Біржа віддає історію капіталу з такою щільністю:
    доба — точка на 36 хвилин, тиждень — на 2.6 години, місяць — на 15 годин,
    увесь час — одна точка на ДВАНАДЦЯТЬ ДІБ. Тому просадка рахується лише
    на вікні «місяць», а глибша історія використовується як форма кривої, а
    не як вимір. Назвати 12-денну вибірку «максимальною просадкою за рік»
    означало б видати вигадку за число.
    """
    max_drawdown_pct: float = 10.0
    min_history_days: float = 25.0
    min_equity_points: int = 20
    # Прибуток після витрат. Нуль, а не «побільше»: ми шукаємо не найкращих,
    # а тих, хто не втрачає.
    min_net_roi_pct: float = 0.0
    # Скільки грошей треба, щоб повторити цю торгівлю. Більше за наш капітал
    # — кандидат не підходить, хоч би яким прибутковим був.
    max_required_capital: float = 50.0


@dataclass
class Costs:
    """Витрати на копіювання. Беруться з фактичних, а не з реклами."""
    taker_fee_pct: float = 0.045
    # Прослизання на вході й виході, з наших власних бойових угод.
    slippage_pct: float = 0.02
    # Мінімальний ордер на Hyperliquid у доларах.
    min_notional: float = 10.0


@dataclass
class Scoring:
    """Ваги підсумкового балу. Сума має дорівнювати 100."""
    drawdown: int = 30
    evidence: int = 20
    consistency: int = 20
    feasibility: int = 15
    exposure: int = 10
    stability: int = 5

    def total(self) -> int:
        return (self.drawdown + self.evidence + self.consistency
                + self.feasibility + self.exposure + self.stability)


@dataclass
class Config:
    capital: float = 50.0
    db_path: str = str(DEFAULT_DB)
    cache_dir: str = str(DEFAULT_CACHE)
    limits: Limits = field(default_factory=Limits)
    universe: Universe = field(default_factory=Universe)
    screen: Screen = field(default_factory=Screen)
    costs: Costs = field(default_factory=Costs)
    scoring: Scoring = field(default_factory=Scoring)

    def __post_init__(self) -> None:
        if self.scoring.total() != 100:
            raise ValueError(f"ваги балу дають {self.scoring.total()}, а мають 100")

    @classmethod
    def load(cls, path: str | None = None) -> "Config":
        """Читає json, якщо він є; інакше бере усталене.

        Шлях можна дати й через змінну RESEARCH_CONFIG — щоб запускати з
        іншими порогами, нічого не редагуючи.
        """
        where = path or os.environ.get("RESEARCH_CONFIG")
        if not where or not Path(where).exists():
            return cls()
        raw = json.loads(Path(where).read_text(encoding="utf-8"))
        return cls(
            capital=raw.get("capital", 50.0),
            db_path=raw.get("db_path", str(DEFAULT_DB)),
            cache_dir=raw.get("cache_dir", str(DEFAULT_CACHE)),
            limits=Limits(**raw.get("limits", {})),
            universe=Universe(**raw.get("universe", {})),
            screen=Screen(**raw.get("screen", {})),
            costs=Costs(**raw.get("costs", {})),
            scoring=Scoring(**raw.get("scoring", {})),
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)
