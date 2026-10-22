"""Резервная копия базы бота: анкеты, решения кураторов, опросы, версии модели.

    python scripts/backup_db.py                         # одна копия сейчас
    python scripts/backup_db.py --every-hours 24        # раз в сутки, пока не остановят (так работает в Docker)

Копии — data/backups/bot-<дата-время>.sqlite3, хранятся последние --keep штук.
Копия делается штатным способом SQLite (backup), поэтому её можно снимать, пока бот работает.
Восстановить: остановить бота и дашборд, заменить data/bot.sqlite3 нужной копией, запустить снова.
"""
import argparse
import datetime
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def backup(db_path, folder, keep):
    if not Path(db_path).exists():
        print(f"Базы {db_path} ещё нет — копировать нечего.")
        return None
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
    target = folder / f"bot-{stamp}.sqlite3"
    source = sqlite3.connect(db_path)
    copy = sqlite3.connect(target)
    source.backup(copy)
    copy.close()
    source.close()
    # Старые копии удаляем: имена с датой, поэтому сортировка по имени — это сортировка по времени.
    copies = sorted(folder.glob("bot-*.sqlite3"))
    for old in copies[:-keep]:
        old.unlink()
    print(f"Копия базы: {target.name} (всего копий: {min(len(copies), keep)})")
    return target


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(ROOT / "data" / "bot.sqlite3"))
    ap.add_argument("--to", default=str(ROOT / "data" / "backups"))
    ap.add_argument("--keep", type=int, default=14, help="сколько последних копий хранить")
    ap.add_argument("--every-hours", type=float, default=0, help="повторять с таким интервалом; 0 — один раз")
    a = ap.parse_args()

    while True:
        try:
            backup(a.db, Path(a.to), a.keep)
        except sqlite3.Error as error:
            print(f"Не удалось сделать копию: {error}")
        if not a.every_hours:
            break
        time.sleep(a.every_hours * 3600)


if __name__ == "__main__":
    main()
