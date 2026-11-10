"""Відновлення позицій із потоку виконань — і звіт про власну надійність.

НАВІЩО ЦЕ ПОТРІБНО. Біржа віддає виконання, а не угоди. Один ордер
розбивається на десятки фіксацій з однаковим часом: ми бачили дванадцять
записів із міткою 1791649264660, розміри 4.5, 6.1, 35.7 — це не дванадцять
входів, а один, виконаний частинами об різні заявки у склянці.

Чим це загрожує. Перший варіант детектора поведінки порівнював РОЗМІРИ
СУСІДНІХ ВИКОНАНЬ і оголосив нашого найкращого трейдера мартингейлом: після
«збиткової угоди» розмір «зростав» у 32% випадків. Насправді порівнювались
уламки одного ордера. Висновок був хибний і зроблений упевнено — саме так і
виглядає помилка, якої не видно.

ЩО ТУТ ГОЛОВНЕ, І ЧОМУ ФАЙЛ ПЕРЕПИСАНО ВДРУГЕ

Відновлення позицій — найнижчий рівень усього дослідження. Якщо він бреше,
брешуть і ознаки поведінки, і копійованість, і будь-яке порівняння
архітектур копіювання. Тому тут недостатньо повернути список позицій: треба
повернути ще й чесну оцінку того, наскільки цьому списку можна вірити.

Дві пастки, через які «нуль» може означати зовсім не те, що здається:

1. ПОЗИЦІЯ ІСНУВАЛА ДО ВИБІРКИ. Перше виконання в вікні може бути закриттям
   позиції, відкритої тиждень тому. Мовчки викинути його не можна: це не
   «нічого не було», а «ми не знаємо, що було». Такі виконання рахуються
   окремо, а фрагмент позначається як непридатний для порівняння.

2. ДАНІ З ДІРКОЮ. Якщо між виконаннями загубилась сторінка, наш підрахунок
   розміру розійдеться з дійсністю. Біржа дає поле startPosition — розмір
   позиції ДО виконання. Ми звіряємося з ним на кожному кроці, і щойно
   з'являється розбіжність, монета позначається ненадійною. Без цієї звірки
   «немає повних закриттів» могло б виявитись наслідком розбору, а не
   поведінки трейдера.

ПЕРЕВЕРТАННЯ. Закриття може перестрибнути нуль — тоді це вихід і одразу
новий вхід у протилежний бік. Рахується саме так: дві різні ставки.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Допуск при звірці зі startPosition. Розміри дробові, тому порівнюємо з
# відносною похибкою, а не з нулем.
TOLERANCE = 1e-6


@dataclass
class Position:
    coin: str
    side: str                 # LONG | SHORT
    opened_ms: int
    closed_ms: int | None = None
    entry_px: float = 0.0
    exit_px: float = 0.0
    size: float = 0.0         # найбільший розмір за час життя позиції
    notional: float = 0.0     # розмір × ціна входу
    pnl: float = 0.0          # закритий результат
    fees: float = 0.0
    fills: int = 0
    # Повне закриття означає вихід у нуль. Часткові закриття лишаються
    # всередині позиції й окремими угодами не стають.
    partial_closes: int = 0

    @property
    def closed(self) -> bool:
        return self.closed_ms is not None

    @property
    def minutes(self) -> float:
        if self.closed_ms is None:
            return 0.0
        return (self.closed_ms - self.opened_ms) / 60_000

    @property
    def move_frac(self) -> float:
        """Яку частку обсягу склав результат — наскільки далеко ходила ціна."""
        return abs(self.pnl) / self.notional if self.notional > 0 else 0.0


@dataclass
class CoinReport:
    """Що вдалося відновити по одній монеті й чому саме стільки."""
    coin: str
    fills: int = 0
    positions: int = 0
    # Виконання до першого моменту, коли ми достовірно знали розмір позиції.
    unknown_prefix_fills: int = 0
    # Позиція, що лишилась відкритою в кінці вікна.
    residual_size: float = 0.0
    # Розбіжність між нашим підрахунком і startPosition біржі.
    mismatches: int = 0
    reliable: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass
class Reconstruction:
    positions: list[Position] = field(default_factory=list)
    coins: dict[str, CoinReport] = field(default_factory=dict)

    @property
    def reliable_coins(self) -> list[str]:
        return [c for c, r in self.coins.items() if r.reliable]

    @property
    def reliable(self) -> bool:
        """Чи можна взагалі щось стверджувати про цього трейдера."""
        return bool(self.coins) and any(r.reliable for r in self.coins.values())

    @property
    def unknown_prefix_fills(self) -> int:
        return sum(r.unknown_prefix_fills for r in self.coins.values())

    def positions_of(self, reliable_only: bool = True) -> list[Position]:
        if not reliable_only:
            return self.positions
        good = set(self.reliable_coins)
        return [p for p in self.positions if p.coin in good]


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _close(position: Position, when: int, price: float) -> None:
    position.closed_ms = when
    position.exit_px = price


def reconstruct(fills: list[dict]) -> Reconstruction:
    """Відновлює позиції по кожній монеті й звітує, де відновлення не вдалось.

    Повертає лише ЗАВЕРШЕНІ позиції: ті, що відкрились і закрились у вікні.
    Усе інше — у звіті по монеті, а не мовчки відкинуте.
    """
    out = Reconstruction()
    by_coin: dict[str, list[dict]] = {}
    for fill in fills:
        by_coin.setdefault(str(fill.get("coin") or "?"), []).append(fill)

    for coin, rows in by_coin.items():
        rows.sort(key=lambda f: (_num(f.get("time")), _num(f.get("tid"))))
        report = CoinReport(coin=coin, fills=len(rows))
        out.coins[coin] = report

        current: Position | None = None
        held = 0.0
        entry_cost = 0.0
        # Поки не знаємо достовірного розміру позиції, нічого не збираємо.
        known = False

        for fill in rows:
            direction = str(fill.get("dir") or "")
            size = abs(_num(fill.get("sz")))
            price = _num(fill.get("px"))
            when = int(_num(fill.get("time")))
            pnl = _num(fill.get("closedPnl"))
            fee = _num(fill.get("fee"))
            if size <= 0 or price <= 0:
                continue

            raw_start = fill.get("startPosition")
            start = _num(raw_start) if raw_start is not None else None

            # --- встановлення достовірного стану ---
            if not known:
                if start is None:
                    # Поля немає — звіритись нічим. Приймаємо початок за нуль,
                    # але позначаємо, що це припущення, а не вимір. Такі
                    # записи трапляються в старому архіві.
                    known = True
                    held = 0.0
                    report.notes.append(
                        "startPosition відсутній — початковий стан прийнято "
                        "за нуль без перевірки")
                elif abs(start) <= TOLERANCE:
                    # Позиція тут порожня — з цієї миті ми знаємо все.
                    known = True
                    held = 0.0
                else:
                    # Позиція вже існувала до вікна. Це не «нічого не було».
                    report.unknown_prefix_fills += 1
                    continue

            # --- звірка з біржею ---
            if start is not None:
                scale = max(1.0, abs(start), abs(held))
                if abs(start - held) > TOLERANCE * scale:
                    report.mismatches += 1
                    report.reliable = False
                    report.notes.append(
                        f"розбіжність зі startPosition: біржа каже {start}, "
                        f"у нас {held} — у даних дірка")
                    # Довіряємо біржі й продовжуємо від її числа.
                    held = start
                    if current is not None and abs(held) <= TOLERANCE:
                        current = None

            opening = direction.startswith("Open")
            long_side = "Long" in direction
            # Напрям руху розміру, а не напрям позиції. «Close Long» містить
            # слово Long, але зменшує лонг: якщо взяти знак за словом,
            # позиція не закриється ніколи.
            signed = (size if long_side else -size) if opening else \
                     (-size if long_side else size)

            before = held
            held = before + signed

            if opening:
                if current is None or abs(before) <= TOLERANCE:
                    current = Position(coin=coin,
                                       side="LONG" if long_side else "SHORT",
                                       opened_ms=when)
                    entry_cost = 0.0
                entry_cost += size * price
                current.fills += 1
                current.fees += fee
                current.size = max(current.size, abs(held))
                current.notional = max(current.notional, abs(held) * price)
                if abs(held) > TOLERANCE:
                    current.entry_px = entry_cost / abs(held)
                continue

            # --- закриття ---
            if current is None:
                # Закриття без відкриття вже після того, як стан став
                # відомим: такого не буває, якщо дані цілі.
                report.mismatches += 1
                report.reliable = False
                report.notes.append("закриття без відкриття при відомому стані")
                continue

            current.fills += 1
            current.fees += fee
            current.pnl += pnl

            crossed = before * held < 0          # перестрибнули нуль
            if abs(held) <= TOLERANCE or crossed:
                _close(current, when, price)
                if current.entry_px > 0:
                    out.positions.append(current)
                    report.positions += 1
                current = None
                entry_cost = 0.0
                if crossed:
                    # Решта обсягу — це вже вхід у протилежний бік.
                    rest = abs(held)
                    current = Position(coin=coin,
                                       side="LONG" if held > 0 else "SHORT",
                                       opened_ms=when, entry_px=price,
                                       size=rest, notional=rest * price, fills=1)
                    entry_cost = rest * price
                else:
                    held = 0.0
            else:
                current.partial_closes += 1
                current.exit_px = price

        report.residual_size = round(held, 10)
        if current is not None:
            report.notes.append(
                "позиція лишилась відкритою в кінці вікна — у підсумок не йде")
        if report.unknown_prefix_fills:
            report.notes.append(
                f"{report.unknown_prefix_fills} виконань до першого відомого "
                "стану: позиція існувала до вибірки, цей фрагмент не рахується")

    out.positions.sort(key=lambda p: p.opened_ms)
    return out


def build(fills: list[dict]) -> list[Position]:
    """Лише завершені позиції з надійно відновлених монет.

    Коротка форма для тих, кому звіт не потрібен. Ненадійні монети сюди не
    потрапляють навмисно: краще менше даних, ніж дані невідомої якості.
    """
    return reconstruct(fills).positions_of(reliable_only=True)
