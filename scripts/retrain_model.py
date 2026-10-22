"""Переобучить модель успеха на ответах опроса через четыре месяца (обычно это делает сам бот).

    python scripts/retrain_model.py            # если накопилось достаточно новых меток
    python scripts/retrain_model.py --force    # переобучить сейчас
    python scripts/retrain_model.py --db data/sim.sqlite3

Подробности — в bot/retrain.py. Версии модели — в таблице model_versions базы бота и в дашборде.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.retrain import retrain  # noqa: E402
from bot.storage import Storage  # noqa: E402


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "data" / "bot.sqlite3"))
    ap.add_argument("--force", action="store_true", help="не ждать новых меток")
    ap.add_argument("--no-history", action="store_true", help="учить только на опросах, без прошлых наборов")
    a = ap.parse_args()

    report = retrain(Storage(a.db), force=a.force, with_history=not a.no_history)
    if report is None:
        print("Новых меток пока мало — модель не переобучалась (порог: checkin_survey.min_new_labels).")
        return
    print(f"Прошлые наборы: {report['n_history']}, опросы: {report['n_survey']}")
    print(report["note"])
    if report.get("updated") is not None:
        print(f"P(успеха) пересчитана у анкет: {report['updated']}")


if __name__ == "__main__":
    main()
