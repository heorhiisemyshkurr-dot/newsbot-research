"""Єдина двері до Hyperliquid: ліміт, повтори, кеш, відновлюваність.

ЧОМУ ВСЕ ЧЕРЕЗ ОДИН КЛАС. Біржа рахує вагу запитів і при перевищенні
відповідає 429. Коли звертань кілька місць, ніхто не знає загального темпу,
і ліміт вибивається раптово. Тут темп один на весь процес.

КЕШ НА ДИСКУ. Скан 47 тисяч трейдерів переривається — через ліміт, мережу,
Ctrl+C. Без кешу кожен повтор починався б спочатку й бив по біржі вдруге за
тим самим. З кешем повтор майже безкоштовний.

ТІЛЬКИ ЧИТАННЯ. Жодного підпису, жодного ключа, жодної точки, що змінює
стан. Це закріплено тестом, який шукає заборонені слова в цьому пакеті —
тому тут їх немає навіть у коментарях.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

INFO = "https://api.hyperliquid.xyz/info"
LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"

# Скільки виконань віддає одна сторінка. Не наш вибір — межа біржі.
PAGE = 2000


class RateLimited(RuntimeError):
    """Біржа попросила зачекати, і чекати вже нікуди."""


class Source:
    def __init__(self, config, client: httpx.Client | None = None) -> None:
        self.config = config
        self.limits = config.limits
        self.cache = Path(config.cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self._client = client or httpx.Client(timeout=self.limits.timeout_sec)
        self._gap = 60.0 / max(1, self.limits.requests_per_minute)
        self._last = 0.0
        self.stats = {"requests": 0, "cached": 0, "retries": 0, "errors": 0}

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # нижній рівень
    # ------------------------------------------------------------------

    def _wait(self) -> None:
        delay = self._gap - (time.monotonic() - self._last)
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()

    def _path(self, key: str) -> Path:
        return self.cache / f"{hashlib.sha256(key.encode()).hexdigest()[:24]}.json"

    def _cached(self, key: str, max_age_sec: float) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        if max_age_sec > 0 and time.time() - path.stat().st_mtime > max_age_sec:
            return None
        try:
            self.stats["cached"] += 1
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _store(self, key: str, value: Any) -> None:
        try:
            self._path(key).write_text(json.dumps(value), encoding="utf-8")
        except OSError:
            pass    # кеш не критичний: без нього просто повільніше

    def post(self, body: dict, cache_key: str | None = None,
             max_age_sec: float = 0.0) -> Any:
        """Запит до /info з повторами. Кеш — лише якщо дали ключ."""
        if cache_key:
            hit = self._cached(cache_key, max_age_sec)
            if hit is not None:
                return hit

        last_error: Exception | None = None
        for attempt in range(self.limits.retries):
            self._wait()
            try:
                self.stats["requests"] += 1
                response = self._client.post(INFO, json=body)
                if response.status_code == 429:
                    raise RateLimited("429")
                response.raise_for_status()
                data = response.json()
                if cache_key:
                    self._store(cache_key, data)
                return data
            except (RateLimited, httpx.HTTPError) as error:
                last_error = error
                self.stats["retries"] += 1
                # Зростаюча пауза: при 429 наполягати означає отримати ще 429.
                time.sleep(self.limits.backoff_sec * (2 ** attempt))
        self.stats["errors"] += 1
        raise RateLimited(f"не вдалося після {self.limits.retries} спроб: {last_error}")

    # ------------------------------------------------------------------
    # дані
    # ------------------------------------------------------------------

    def leaderboard(self, max_age_sec: float = 6 * 3600) -> list[dict]:
        """Усі трейдери лідерборда. Один запит на всіх, 37 МБ.

        Кеш на шість годин: таблиця змінюється повільно, а качати 37 МБ при
        кожному запуску безглуздо.
        """
        hit = self._cached("leaderboard", max_age_sec)
        if hit is not None:
            return hit
        self._wait()
        self.stats["requests"] += 1
        response = self._client.get(LEADERBOARD, timeout=300.0)
        response.raise_for_status()
        rows = response.json().get("leaderboardRows") or []
        self._store("leaderboard", rows)
        return rows

    def portfolio(self, address: str, max_age_sec: float = 3600) -> dict[str, dict]:
        """Історія вартості рахунку за вікнами.

        Повертає {вікно: {accountValueHistory, pnlHistory, vlm}}. Саме
        вартість рахунку, а не накопичений PnL: друге не враховує ні
        поповнень, ні виведень, ні нереалізованого збитку.
        """
        raw = self.post({"type": "portfolio", "user": address.lower()},
                        cache_key=f"portfolio:{address.lower()}", max_age_sec=max_age_sec)
        return {window: data for window, data in (raw or [])}

    def state(self, address: str, max_age_sec: float = 300) -> dict:
        """Відкриті позиції й маржа просто зараз."""
        return self.post({"type": "clearinghouseState", "user": address.lower()},
                         cache_key=f"state:{address.lower()}", max_age_sec=max_age_sec) or {}

    def fills(self, address: str, since_ms: int, pages: int = 30
              ) -> tuple[list[dict], bool]:
        """Виконання з моменту since_ms. Повертає (виконання, чи повне вікно).

        ПРАПОРЕЦЬ ПОВНОТИ ВАЖЛИВІШИЙ ЗА САМІ ДАНІ. Сторінка віддає 2000
        записів від найстаріших. Якщо сторінки скінчились раніше, ніж ми
        дійшли до сьогодні, у вибірці лежить ПОЧАТОК вікна без кінця — тобто
        відкриття без своїх закриттів. Метрики з такого вікна занижують і
        кількість угод, і збитки. Неповне вікно не рятується, воно
        позначається, і рахувати по ньому не можна.
        """
        out: list[dict] = []
        cursor = int(since_ms)
        complete = False
        for _ in range(pages):
            chunk = self.post({"type": "userFillsByTime", "user": address.lower(),
                               "startTime": cursor})
            if not isinstance(chunk, list):
                break
            out.extend(chunk)
            if len(chunk) < PAGE:
                complete = True
                break
            last = chunk[-1].get("time")
            if last is None or last <= cursor:
                break
            cursor = int(last) + 1
        # Прибираємо дублі на межах сторінок: межа ловить однакові мілісекунди.
        seen: set[tuple] = set()
        unique: list[dict] = []
        for fill in out:
            key = (fill.get("time"), fill.get("oid"), fill.get("tid"), fill.get("sz"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(fill)
        unique.sort(key=lambda f: f.get("time", 0))
        return unique, complete
