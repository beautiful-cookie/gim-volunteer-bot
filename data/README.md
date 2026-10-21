# Папка data

Здесь лежат рабочие данные. В git они не попадают (см. `.gitignore`): это персональные данные
кандидатов — ФИО, даты рождения, ответы анкет — и всё, что из них получено.

Передавайте исходные таблицы только напрямую, не через репозиторий и не через публичные ссылки.

| Файл | Откуда берётся |
|---|---|
| `anketa_clean.xlsx`, `anketa_clean.csv` | `python scripts/clean_anketa.py --in2024 "Анкеты 2024 осень.xlsx" --in2025 "Анкеты 2025 весна.xlsx" --out data` |
| `scored.xlsx` | `python scripts/score_anketa.py --provider auto` (нужен ключ GigaChat в `.env`) |
| `llm_cache/` | кэш ответов GigaChat: повторный прогон тех же анкет бесплатный |
| `model_report.xlsx` | `python scripts/model_success.py`; коэффициенты пишутся в `config/model.json` |
| `bot.sqlite3` | база бота: диалоги, отправленные анкеты, решения кураторов из дашборда |
| `vk_bot.log` | лог бота |
