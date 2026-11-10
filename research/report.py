"""Звіт: JSON для машини, CSV для таблиці, текст для людини."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path


def write(out_dir: str, config, scan, passed: list[dict], everyone: list[dict]) -> dict:
    where = Path(out_dir)
    where.mkdir(parents=True, exist_ok=True)

    summary = {
        "capital": config.capital,
        "discovered": scan.discovered,
        "shortlisted": scan.shortlisted,
        "analysed": scan.analysed,
        "passed": len(passed),
        "errors": scan.errors,
        "seconds": scan.seconds,
        "excluded": scan.excluded,
        "limits": {
            "просадка вимірюється лише на вікні «місяць»":
                "глибша історія має одну точку на 12 діб — просадка між "
                "точками не видна",
            "історія угод обмежена":
                "сторінка віддає 2000 виконань; для активного трейдера це дві "
                "доби, тому вікно поведінки — 14 діб, а не 180",
            "стоп трейдера невидимий":
                "біржа не каже, де він його ставив; копійованість оцінюється "
                "за фактичним рухом ціни в закритих угодах",
        },
    }
    (where / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (where / "candidates.json").write_text(
        json.dumps(everyone, ensure_ascii=False, indent=2), encoding="utf-8")
    (where / "config.json").write_text(config.to_json(), encoding="utf-8")

    with (where / "candidates.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "адреса", "бал", "довіра", "пройшов", "просадка_%", "днів_історії",
            "точок", "ROI_%", "рахунок", "оборот", "частка_угод_проходить",
            "потрібен_капітал", "ознаки", "чому_не_пройшов",
        ])
        for c in everyone:
            e = c.get("equity") or {}
            k = c.get("copyability") or {}
            b = c.get("behavior") or {}
            writer.writerow([
                c["address"], c["score"]["total"], c["confidence"],
                "так" if c["screen"]["passed"] else "ні",
                e.get("max_drawdown_pct"), round(e.get("days") or 0, 1),
                e.get("points"), e.get("roi_pct"), c.get("account_value"),
                c.get("month_turnover"), k.get("passable_share"),
                k.get("required_capital"), "; ".join(b.get("flags") or []),
                "; ".join(c["screen"]["failures"]),
            ])
    return summary


def text(summary: dict, passed: list[dict], everyone: list[dict]) -> str:
    lines = [
        "=" * 72,
        "ДОСЛІДЖЕННЯ ТРЕЙДЕРІВ HYPERLIQUID",
        "=" * 72,
        f"капітал, під який шукаємо: {summary['capital']:.0f}$",
        "",
        f"знайдено в лідерборді:  {summary['discovered']:,}".replace(",", " "),
        f"пройшли перший відсів:  {summary['shortlisted']}",
        f"вивчено детально:       {summary['analysed']}",
        f"пройшли ВСІ фільтри:    {summary['passed']}",
        f"помилок запитів:        {summary['errors']}",
        f"часу:                   {summary['seconds']} с",
        "",
        "чому відсіяно:",
    ]
    for reason, count in sorted(summary["excluded"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {count:>6}  {reason}")

    lines += ["", "-" * 72]
    if not passed:
        lines += [
            "ЖОДЕН КАНДИДАТ НЕ ПРОЙШОВ УСІ ФІЛЬТРИ.",
            "",
            "Це результат, а не збій. Пороги навмисно не послаблюються заради",
            "непорожнього списку: підлаштувати критерій під відповідь означає",
            "перестати мати критерій.",
            "",
            "Найближчі до проходження:",
        ]
        for c in everyone[:5]:
            lines.append(f"  {c['address'][:14]}…  бал {c['score']['total']:>5}  "
                         f"довіра {c['confidence']}")
            for failure in c["screen"]["failures"]:
                lines.append(f"       не пройшов — {failure}")
    else:
        lines.append(f"ПРОЙШЛИ ВСІ ФІЛЬТРИ: {len(passed)}")
        lines.append("")
        for c in passed[:15]:
            e = c.get("equity") or {}
            k = c.get("copyability") or {}
            lines += [
                f"  {c['address']}",
                f"     бал {c['score']['total']} ({c['score']['parts']}), довіра {c['confidence']}",
                f"     просадка {e.get('max_drawdown_pct')}% за {round(e.get('days') or 0)} діб, "
                f"ROI {e.get('roi_pct')}%",
                f"     проходить {(k.get('passable_share') or 0)*100:.0f}% угод, "
                f"потрібен капітал {k.get('required_capital')}$",
                "",
            ]

    lines += ["-" * 72, "ЧОГО ЦЕЙ ЗВІТ НЕ ДОВОДИТЬ:", ""]
    for name, why in summary["limits"].items():
        lines.append(f"  • {name}")
        lines.append(f"    {why}")
    lines += [
        "",
        "  • минулий результат не переноситься на майбутнє: усе вище —",
        "    опис історії, а не прогноз;",
        "  • фільтри пройдені не означають «можна копіювати» — означають",
        "    «варто перевірити на папері».",
        "=" * 72,
    ]
    return "\n".join(lines)
