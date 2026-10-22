"""Данные для дашборда: анкеты из бота и исторические анкеты 2024–2025 в одной таблице.

Каждая строка — кандидат. Общие столбцы:
    key            — уникальный ключ: «bot:12» или «hist:O24-001»
    label, name    — номер анкеты и ФИО (у исторических ФИО есть не везде)
    s_<пункт>      — баллы 0–3 по пунктам рубрики (пусто — вопроса не было)
    F_<фактор>     — баллы факторов 0–100
    index, grade   — индекс 0–100 и оценка 0–3 по весам из rubric.yaml (пересчитываются ползунками)
    p_success      — вероятность успеха из модели шага 3
    directions, flags, summary, interview_questions, evidence, answers — для карточки кандидата
"""
import json
import math
import os
import sqlite3
from pathlib import Path

import pandas as pd

from scorer.score import load_rubric

ROOT = Path(__file__).resolve().parent.parent
# GIM_BOT_DB — другая база бота, например демонстрационная из scripts/selftest_survey.py.
BOT_DB = Path(os.environ.get("GIM_BOT_DB") or ROOT / "data" / "bot.sqlite3")
SCORED = ROOT / "data" / "scored.xlsx"
CLEAN = ROOT / "data" / "anketa_clean.csv"
MODEL_REPORT = ROOT / "data" / "model_report.xlsx"

HISTORICAL_DIRECTIONS = {"dir_org": "Организационное", "dir_project": "Проектное",
                         "dir_fond": "Фондовое", "dir_inclusive": "Инклюзивное"}


def is_missing(value):
    return value is None or (isinstance(value, float) and math.isnan(value))


# ---------------------------------------------------------------- анкеты из бота

def load_bot():
    if not BOT_DB.exists():
        return pd.DataFrame()
    db = sqlite3.connect(BOT_DB)
    rows = db.execute("SELECT id, user_id, submitted_at, status, answers, result FROM applications").fetchall()
    sessions = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    surveys = {}
    if has_table(db, "surveys"):
        for app_id, status, answers, alert in db.execute("SELECT app_id, status, answers, alert FROM surveys"):
            surveys[app_id] = dict(status=status, answers=json.loads(answers), alert=alert)
    db.close()

    records = []
    for app_id, user_id, submitted_at, status, answers_json, result_json in rows:
        answers = json.loads(answers_json)
        result = json.loads(result_json) if result_json else {}
        if result.get("vk_summary"):
            answers["ВКонтакте (автоматически)"] = result["vk_summary"]
        record = dict(
            key=f"bot:{app_id}", source="Бот", label=f"№{app_id}", name=answers.get("fio", ""),
            vk_url=f"https://vk.com/id{user_id}", submitted_at=submitted_at, status=status,
            city=answers.get("city", ""), course=answers.get("course", "") or "не учится",
            hours_month=answers.get("hours_month", ""), channel=answers.get("source", ""),
            directions=answers.get("directions", []),
            p_success=result.get("p_success"),
            flags=result.get("yellow_flags", []) + [f for f in result.get("flags", []) if "попытка" in f],
            summary=result.get("summary", ""), recommended_direction=result.get("recommended_direction", ""),
            interview_questions=result.get("interview_questions", []),
            evidence=result.get("categories", {}), answers=answers,
            outcome_hours=None, curator_score=None, survey=surveys.get(app_id),
        )
        for item, score in (result.get("scores") or {}).items():
            record[f"s_{item}"] = score
        records.append(record)
    df = pd.DataFrame(records)
    df.attrs["sessions_started"] = sessions
    return df


def has_table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


# ---------------------------------------------------------------- опрос через четыре месяца и версии модели

SURVEY_STATUS = {"sent": "ждём ответа", "completed": "ответил(а)", "declined": "отказался(лась)",
                 "expired": "не ответил(а)", "undelivered": "не доставлен"}


def load_surveys():
    """Опросы волонтёров с именами из анкет: одна строка — один опрос, новые сверху."""
    if not BOT_DB.exists():
        return pd.DataFrame()
    db = sqlite3.connect(BOT_DB)
    if not has_table(db, "surveys"):
        db.close()
        return pd.DataFrame()
    rows = db.execute("SELECT s.app_id, s.sent_at, s.status, s.completed_at, s.answers, s.alert, a.answers, a.result "
                      "FROM surveys s JOIN applications a ON a.id = s.app_id ORDER BY s.sent_at DESC").fetchall()
    db.close()
    records = []
    for app_id, sent_at, status, completed_at, answers, alert, application, result in rows:
        application = json.loads(application)
        result = json.loads(result) if result else {}
        records.append(dict(key=f"bot:{app_id}", label=f"№{app_id}", name=application.get("fio", ""),
                            sent_at=sent_at[:10], status=status, status_text=SURVEY_STATUS.get(status, status),
                            completed_at=(completed_at or "")[:10], answers=json.loads(answers), alert=alert,
                            p_success=result.get("p_success")))
    return pd.DataFrame(records)


def load_model_versions():
    """История дообучения модели (таблица model_versions), старые версии сверху."""
    if not BOT_DB.exists():
        return pd.DataFrame()
    db = sqlite3.connect(BOT_DB)
    if not has_table(db, "model_versions"):
        db.close()
        return pd.DataFrame()
    table = pd.read_sql("SELECT id, created_at, n_history, n_survey, auc_new, auc_old, accepted, note "
                        "FROM model_versions ORDER BY id", db)
    db.close()
    return table


# ---------------------------------------------------------------- исторические анкеты

def historical_flags(c):
    """Флаги кандидата, которые можно восстановить по старым анкетам (как жёлтые флаги бота)."""
    flags = []
    if c["first_year_bach"] == 1:
        flags.append("1 курс бакалавриата")
    if c["only_fond"] == 1:
        flags.append("только фонды")
    if c["n_dirs"] == 4:
        flags.append("все направления разом")
    return flags


def load_historical():
    if not SCORED.exists() or not CLEAN.exists():
        return pd.DataFrame()
    scored = pd.read_excel(SCORED, sheet_name="Баллы")
    clean = pd.read_csv(CLEAN).set_index("id")
    p_success = {}
    if MODEL_REPORT.exists():
        forecast = pd.read_excel(MODEL_REPORT, sheet_name="Прогноз")
        p_success = dict(zip(forecast["id"], forecast["P_success"]))

    records = []
    for _, row in scored.iterrows():
        c = clean.loc[row["id"]]
        directions = [name for column, name in HISTORICAL_DIRECTIONS.items() if c[column] == 1]
        course = c["edu_level"] if is_missing(c["course_num"]) else f"{int(c['course_num'])} курс, {c['edu_level']}"
        answers = {"Курс": course, "Вуз": c["vuz"], "Факультет": c["faculty"], "Опыт": c["experience"],
                   "Ожидания": c["expectations"], "Хобби": c["hobby"], "Суперсила": c["superpower"],
                   "Направления": ", ".join(directions), "Источник": c["source"]}
        record = dict(
            key=f"hist:{row['id']}", source=f"История {c['cohort']}", label=row["id"],
            name="" if is_missing(c["fio"]) else c["fio"], vk_url="", submitted_at=c["cohort"], status="scored",
            city="", course=course, hours_month="", channel=c["source"], directions=directions,
            p_success=p_success.get(row["id"]),
            flags=historical_flags(c),
            summary="" if is_missing(row.get("summary")) else row["summary"],
            recommended_direction="" if is_missing(row.get("recommended_direction")) else row["recommended_direction"],
            interview_questions=[] if is_missing(row.get("interview_questions")) else str(row["interview_questions"]).split("\n"),
            evidence={}, answers={k: ("" if is_missing(v) else v) for k, v in answers.items()},
            outcome_hours=row["hours_per_year"], curator_score=row["screen_score"], stage=row["stage"],
        )
        for column in scored.columns:
            if column.startswith("s_"):
                record[column] = None if is_missing(row[column]) else row[column]
        records.append(record)
    return pd.DataFrame(records)


# ---------------------------------------------------------------- пересчёт по весам

def default_weights():
    return {item["id"]: item["weight"] for item in load_rubric()["items"]}


def apply_weights(df, weights):
    """Факторы, индекс и оценка 0–3 по весам пунктов (ползунки в дашборде меняют weights)."""
    rubric = load_rubric()
    df = df.copy()

    def weighted_mean(row, items):
        total_weight = 0
        total = 0
        for item in items:
            score = row.get(f"s_{item['id']}")
            if is_missing(score):
                continue
            total += weights[item["id"]] * score
            total_weight += weights[item["id"]]
        if total_weight == 0:
            return None
        return round(total / total_weight * 100 / rubric["scale_max"], 1)

    for factor in rubric["factors"]:
        items = [i for i in rubric["items"] if i["factor"] == factor]
        df[f"F_{factor}"] = df.apply(lambda row: weighted_mean(row, items), axis=1)
    df["index"] = df.apply(lambda row: weighted_mean(row, rubric["items"]), axis=1)

    thresholds = rubric["grade_thresholds"]
    df["grade"] = df["index"].apply(lambda i: None if is_missing(i) else sum(i >= t for t in thresholds))
    return df


def factor_titles():
    return load_rubric()["factors"]


def item_titles():
    return {item["id"]: item["question"] for item in load_rubric()["items"]}


def model_metrics():
    """Таблицы качества модели из шага 3: AUC при разных порогах успеха."""
    if not MODEL_REPORT.exists():
        return {}
    sheets = pd.read_excel(MODEL_REPORT, sheet_name=None)
    # У базовой линии (балл куратора) нет «Δ к баллу куратора» — показываем пустую ячейку, а не None.
    # Таблицы только для показа, поэтому переводим всё в строки: в одном столбце числа и пустые ячейки.
    return {name: table.fillna("").astype(str) for name, table in sheets.items() if name.startswith("AUC")}
