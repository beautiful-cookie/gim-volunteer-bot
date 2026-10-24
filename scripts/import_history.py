"""Загрузить таблицы музея с прошлыми наборами — одной командой.

    python scripts/import_history.py                 # очистка + оценка GigaChat + обучение модели
    python scripts/import_history.py --no-llm        # без GigaChat: только пункты, которые считаются правилами
    docker compose run --rm bot python scripts/import_history.py

Перед запуском: таблицы Excel лежат в data/history/, каждый лист перечислен в config/history.yaml.
Повторять после каждого обновления таблиц — например, когда раз в полгода вписали часы активности.
Анкеты, которые GigaChat уже оценивал, повторно не оцениваются (ответы сохранены в data/llm_cache).

Три шага по очереди:
    1. scripts/clean_anketa.py   — сводит листы в одну таблицу и исправляет опечатки и форматы
    2. scripts/score_anketa.py   — оценивает анкеты по рубрике (config/rubric.yaml)
    3. scripts/model_success.py  — учит модель, кто становится активным волонтёром (config/model.json)
После этого в дашборде появляется набор «Прошлые наборы», а бот считает прогноз по новой модели.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(step, script, *args):
    print(f"\n=== Шаг {step} из 3: {script}")
    result = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], cwd=ROOT)
    if result.returncode != 0:
        sys.exit(f"Шаг {step} не выполнен — см. сообщение выше. Подсказки: docs/user-manual.md, «Если что-то не так».")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-llm", action="store_true", help="не обращаться к GigaChat")
    a = ap.parse_args()

    run(1, "clean_anketa.py")
    run(2, "score_anketa.py", "--provider", "none" if a.no_llm else "auto")
    run(3, "model_success.py")
    print("\nГотово. Обновите страницу дашборда: прошлые наборы — в боковой панели, «Набор».")


if __name__ == "__main__":
    main()
