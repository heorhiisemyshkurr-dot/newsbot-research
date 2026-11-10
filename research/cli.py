"""Запуск дослідження.

    python -m research.cli                  повний прогін
    python -m research.cli --shortlist 60   менше кандидатів, швидше
    python -m research.cli --no-fills       лише капітал, без історії угод
    python -m research.cli --addresses 0x…  перевірити конкретних
"""
from __future__ import annotations

import argparse
import sys

from .config import Config
from .source import Source
from . import pipeline, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Відбір трейдерів Hyperliquid")
    parser.add_argument("--config")
    parser.add_argument("--out", default="research-report")
    parser.add_argument("--shortlist", type=int)
    parser.add_argument("--capital", type=float)
    parser.add_argument("--fill-days", type=int, default=14)
    parser.add_argument("--no-fills", action="store_true",
                        help="пропустити найдорожчий ступінь")
    parser.add_argument("--addresses", nargs="*",
                        help="перевірити саме цих, без сканування лідерборда")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

    config = Config.load(args.config)
    if args.shortlist:
        config.universe.shortlist = args.shortlist
    if args.capital:
        config.capital = args.capital

    source = Source(config)
    scan = pipeline.Scan()
    try:
        if args.addresses:
            candidates = [{"address": a.lower(), "name": None,
                           "account_value": None, "month_turnover": None,
                           "month_roi": None, "month_pnl": None}
                          for a in args.addresses]
            scan.discovered = scan.shortlisted = len(candidates)
            print(f"перевіряю {len(candidates)} заданих адрес")
        else:
            print("ступінь 1: лідерборд…")
            candidates = pipeline.discover(source, config, scan)
            print(f"  знайдено {scan.discovered}, лишилось {scan.shortlisted}")

        print("ступінь 2: історія капіталу…")
        candidates = pipeline.study_equity(source, config, candidates, scan)
        print(f"  вивчено {scan.analysed}")

        if not args.no_fills:
            print("ступінь 3: історія угод…")
            candidates = pipeline.study_fills(source, config, candidates, scan,
                                              days=args.fill_days)
            print("  готово")

        passed, everyone = pipeline.rank(candidates, config)
        summary = report.write(args.out, config, scan, passed, everyone)
        print()
        print(report.text(summary, passed, everyone))
        print(f"\nзвіти: {args.out}/  (summary.json, candidates.json, candidates.csv)")
        print(f"запитів до біржі: {source.stats['requests']}, "
              f"з кешу: {source.stats['cached']}, повторів: {source.stats['retries']}")
        return 0
    finally:
        source.close()


if __name__ == "__main__":
    raise SystemExit(main())
