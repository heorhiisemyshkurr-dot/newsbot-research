"""Ознаки поведінки, які роблять трейдера небезпечним для копіювання.

Усе тут рахується з ПОЗИЦІЙ, а не з виконань. Причина в коментарі до
positions.py: один ордер біржа розбиває на десятки виконань з однаковим
часом, і перший варіант цього файла, порівнюючи їх між собою, оголосив
нашого найкращого трейдера мартингейлом. Висновок був хибний — і зроблений
упевнено, без жодної ознаки того, що щось не так.

Жодна ознака не є вироком сама по собі — це сигнали, і названі вони саме
так. «Схоже на мартингейл» і «мартингейл» — різні твердження, і друге з
наявних даних не доводиться.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .positions import Position, build


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

# Нижче цієї кількості закритих позицій ознаки не рахуються: на десятку
# позицій будь-яка частка — шум, а флажок виглядав би як знання.
MIN_SAMPLE = 25


@dataclass
class Behavior:
    positions: int = 0
    fills: int = 0
    coins: int = 0
    concentration: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None
    max_loss: float | None = None
    # Частка прибутку, що припадає на верхні 5% позицій.
    top_trade_share: float | None = None
    # Частка випадків, коли ПІСЛЯ ЗБИТКОВОЇ ПОЗИЦІЇ наступна в тій самій
    # монеті відкривається більшою в півтора раза й більше.
    escalation_after_loss: float | None = None
    escalation_sample: int = 0
    median_move_pct: float | None = None
    median_minutes: float | None = None
    # Частка закриттів, які закрили позицію ПОВНІСТЮ. Головне число цього
    # файла: якщо воно близьке до нуля, трейдер не робить окремих угод — він
    # тримає одну безперервну позицію й лише доливає та підрізає.
    full_close_share: float | None = None
    closes: int = 0
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def from_fills(fills: list[dict], complete: bool) -> Behavior:
    out = Behavior(fills=len(fills))
    if not fills:
        out.notes.append("виконань немає")
        return out

    # Чи робить цей трейдер узагалі окремі угоди.
    #
    # ЧОМУ ЦЕ ПЕРША ПЕРЕВІРКА. Поле startPosition каже, скільки позиції було
    # ДО виконання. Якщо закриття забирає рівно стільки ж, скільки було, —
    # це вихід. Якщо менше, це підрізання, а позиція живе далі.
    #
    # Наші чотири трейдери дали 0%, 3%, 0% і 0% повних закриттів за три доби.
    # Тобто жоден із них не виходить із позицій узагалі. Копіювати їхні входи
    # як окремі угоди зі стопом означає брати на себе ризик, якого вони не
    # беруть: вони пересиджують просадку, а наш стоп спрацьовує.
    closes = [f for f in fills if str(f.get("dir") or "").startswith("Close")]
    out.closes = len(closes)
    if closes:
        full = sum(
            1 for f in closes
            if abs(_num(f.get("startPosition"))) - abs(_num(f.get("sz"))) < 1e-9)
        out.full_close_share = round(full / len(closes), 4)
        if out.full_close_share < 0.1:
            out.flags.append(
                f"позиції не закриваються: повних виходів {out.full_close_share*100:.0f}% "
                f"із {len(closes)} закриттів — трейдер тримає безперервну позицію, "
                "а не робить окремі угоди")

    positions = build(fills)
    out.positions = len(positions)
    if not positions:
        out.notes.append(
            "жодної позиції, що відкрилась і закрилась у вікні — "
            "показники нижче порахувати нема з чого")
        return out

    by_coin: dict[str, list[Position]] = defaultdict(list)
    for p in positions:
        by_coin[p.coin].append(p)
    out.coins = len(by_coin)
    top = max(len(v) for v in by_coin.values())
    out.concentration = round(top / len(positions), 3)

    moves = sorted(p.move_frac for p in positions if p.move_frac > 0)
    if moves:
        out.median_move_pct = round(moves[len(moves) // 2] * 100, 3)
    spans = sorted(p.minutes for p in positions)
    out.median_minutes = round(spans[len(spans) // 2], 1)

    wins = [p.pnl for p in positions if p.pnl > 0]
    losses = [p.pnl for p in positions if p.pnl < 0]
    if wins or losses:
        out.win_rate = round(len(wins) / len(positions), 3)
        out.max_loss = round(min(losses), 2) if losses else 0.0
        out.avg_win = round(sum(wins) / len(wins), 2) if wins else 0.0
        out.avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
        lost = abs(sum(losses))
        out.profit_factor = round(sum(wins) / lost, 3) if lost > 0 else None

    if not complete:
        out.notes.append(
            "вікно виконань обірване межею сторінок — позиції на його початку "
            "не мають своїх входів, тому ознаки нижче не рахуються")
        return out

    if len(positions) < MIN_SAMPLE:
        out.notes.append(
            f"закритих позицій {len(positions)}, для ознак треба від {MIN_SAMPLE} — "
            "менше означає гадати, а не міряти")
        return out

    if out.coins == 1:
        out.flags.append("торгує лише однією монетою")
    elif out.concentration and out.concentration > 0.8:
        out.flags.append(f"майже все в одній монеті ({out.concentration * 100:.0f}%)")

    if wins:
        ordered = sorted(wins, reverse=True)
        take = max(1, len(ordered) // 20)
        share = sum(ordered[:take]) / sum(ordered)
        out.top_trade_share = round(share, 3)
        if share > 0.6:
            out.flags.append(
                f"понад {share * 100:.0f}% прибутку з {take} позицій — результат "
                "тримається на одиничних влучаннях")

    # Нарощування після збитку — у межах однієї монети й між ПОЗИЦІЯМИ.
    grew = 0
    after_loss = 0
    for coin_positions in by_coin.values():
        ordered = sorted(coin_positions, key=lambda p: p.opened_ms)
        for prev, nxt in zip(ordered, ordered[1:]):
            if prev.pnl >= 0 or prev.notional <= 0:
                continue
            after_loss += 1
            if nxt.notional > prev.notional * 1.5:
                grew += 1
    out.escalation_sample = after_loss
    if after_loss >= 10:
        out.escalation_after_loss = round(grew / after_loss, 3)
        if out.escalation_after_loss > 0.4:
            out.flags.append(
                f"у {out.escalation_after_loss * 100:.0f}% випадків після збиткової "
                f"позиції наступна в тій самій монеті більша в півтора раза "
                f"(вибірка {after_loss}) — схоже на мартингейл")
    else:
        out.notes.append(
            f"збиткових позицій із продовженням лише {after_loss} — "
            "нарощування після збитку не оцінюється")
    return out
