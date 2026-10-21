"""Обработка отправленной анкеты: баллы по рубрике, вероятность успеха, карточка для кураторов."""
import json
import math
import re
from pathlib import Path

from scorer.extract import assess
from scorer.score import aggregate, item_scores, load_rubric
from scripts.clean_anketa import PROFILE, field_group

ROOT = Path(__file__).resolve().parent.parent
OFFERED_DIRECTIONS = ["Организационное", "Проектное", "Фондовое", "Инклюзивное", "Медиа"]

# Кнопки «часов в месяц» → число для правила рубрики (нижняя граница диапазона).
HOURS = {"Меньше 10": 5, "10–20": 10, "20–30": 20, "30–40": 30, "Больше 40": 40}
GEOGRAPHY = {"Москва": "moscow", "Другой город": "other_city"}
COMMUTE = {"До 1 часа": "region_near", "1–2 часа": "region_far", "Больше 2 часов": "region_far"}
STATUS = {"Учусь": "study", "Работаю": "work", "Не учусь и не работаю": "none"}
SOURCE = {"Социальные сети": "Социальные сети", "Рекомендации друзей": "Рекомендации друзей",
          "Сайт Исторического музея": "Сайт ГИМ"}


def edu_level(course):
    if course == "1 курс бакалавриата":
        return "бакалавриат", True
    if course in ("2 курс", "3 курс", "4 курс", "5–6 курс"):
        return "бакалавриат", False
    if course in ("Магистратура", "Аспирантура"):
        return "магистратура", False
    return "высшее (окончено)", False


def to_candidate(answers):
    """Ответы бота → кандидат в формате scorer (тот же, что для исторических анкет)."""
    studying = "Учусь" in answers.get("status", [])
    level, first_year = edu_level(answers.get("course")) if studying else ("высшее (окончено)", False)
    faculty = answers.get("faculty") or answers.get("education", "")
    group = field_group(faculty, "")
    if group == "не указано":
        profile = "не указано"
    else:
        profile = PROFILE.get(group, "непрофильное")

    city = answers.get("city", "")
    if city == "Московская область":
        geography = COMMUTE.get(answers.get("commute"), "region_far")
    else:
        geography = GEOGRAPHY.get(city, "")

    directions = answers.get("directions", [])
    undecided = "Пока не определился" in directions
    source = answers.get("source", "")
    study_parts = [", ".join(answers.get("status", [])), answers.get("course", ""), answers.get("study_form", ""),
                   answers.get("vuz", ""), answers.get("education", "")]

    return dict(
        id=None,
        study_text=", ".join(p for p in study_parts if p),
        status_set={STATUS[s] for s in answers.get("status", [])},
        hours_month=HOURS.get(answers.get("hours_month")),
        geography=geography,
        why_gim=answers.get("why_gim", ""),
        expectations=answers.get("expectations", ""),
        experience=answers.get("experience", ""),
        hobby=answers.get("hobby", ""),
        superpower=None,
        sci_interests=answers.get("sci_interests", ""),
        edu_level=level, first_year_bach=first_year,
        faculty=faculty, department="", profile_match=profile,
        directions=[d for d in directions if d in OFFERED_DIRECTIONS],
        directions_offered=OFFERED_DIRECTIONS, undecided=undecided, directions_note="",
        source=SOURCE.get(source, "Другое" if source else ""),
        friend_is_volunteer=answers.get("friend_volunteer") == "Да, сейчас",
        followups=[(q, a) for q, a in answers.get("followups", [])],
    )


def success_probability(scores, aggregated, llm, candidate, model_path=ROOT / "config" / "model.json"):
    """P(успеха) по коэффициентам из шага 3. Пропущенный признак = среднее (вклад 0)."""
    if not Path(model_path).exists() or aggregated["index"] is None:
        return None
    model = json.loads(Path(model_path).read_text(encoding="utf-8"))
    features = {
        "index": aggregated["index"],
        "first_year_bach": int(candidate["first_year_bach"]),
        "cat_museum_practice": int(bool(llm and llm.get("ok") and "museum_practice" in llm["categories"])),
        "friend": int(candidate["source"] == "Рекомендации друзей"),
    }
    for factor, value in aggregated["factors"].items():
        features[f"F_{factor}"] = value

    logit = model["coefficients"]["intercept"]
    for name in model["features"]:
        value = features.get(name)
        if value is None:
            continue
        standardized = (value - model["mean"][name]) / (model["std"][name] or 1)
        logit += model["coefficients"][name] * standardized
    return round(1 / (1 + math.exp(-logit)), 2)


def normalize_name(text):
    return text.lower().replace("ё", "е").strip()


def fio_matches_vk(fio, vk_name):
    """Совпадает ли имя или фамилия из анкеты с профилем ВК. None — профиль не получили."""
    if not vk_name:
        return None
    fio_words = {normalize_name(w) for w in fio.split()}
    vk_words = {normalize_name(w) for w in vk_name.split()}
    return bool(fio_words & vk_words)


def score_application(answers, provider, runs=3, vk_name=None):
    """vk_name — «Имя Фамилия» из профиля ВК: по нему проверяем, что ФИО настоящее."""
    rubric = load_rubric()
    candidate = to_candidate(answers)
    # Само ФИО в LLM не передаём (персональные данные) — только итог проверки.
    match = fio_matches_vk(answers.get("fio", ""), vk_name)
    if match is True:
        candidate["fio_note"] = "ФИО совпадает с профилем ВКонтакте"
    elif match is False:
        candidate["fio_note"] = "ФИО НЕ совпадает с именем в профиле ВКонтакте — возможно, выдуманное"
    llm = assess(candidate, rubric, provider, runs=runs) if provider else None
    scores = item_scores(candidate, rubric, llm)
    aggregated = aggregate(scores, rubric)
    result = dict(scores=scores, factors=aggregated["factors"], index=aggregated["index"],
                  grade=aggregated["grade"], coverage=aggregated["coverage"],
                  p_success=success_probability(scores, aggregated, llm, candidate),
                  flags=[], summary="", recommended_direction="", interview_questions=[], categories={})
    if llm:
        result["flags"] = llm["flags"]
    if llm and llm.get("ok"):
        result.update(summary=llm["summary"], recommended_direction=llm["recommended_direction"],
                      interview_questions=llm["interview_questions"], categories=llm["categories"])
    result["yellow_flags"] = yellow_flags(answers)
    if match is False:
        result["yellow_flags"].insert(0, "ФИО не совпадает с профилем ВК")
    return result


def yellow_flags(answers):
    """Флаги из заметок встречи: показываются куратору отдельно от индекса."""
    flags = []
    if answers.get("course") == "1 курс бакалавриата" and answers.get("study_form") == "Очная":
        flags.append("1 курс, очно")
    if answers.get("city") == "Другой город":
        flags.append("другой город")
    if answers.get("commute") in ("1–2 часа", "Больше 2 часов"):
        flags.append("дорога больше часа")
    if answers.get("directions") == ["Фондовое"]:
        flags.append("только фонды")
    if answers.get("other_programs") == "Да, в нескольких":
        flags.append("несколько других программ")
    if answers.get("hours_month") == "Меньше 10":
        flags.append("меньше 10 ч в месяц")
    if set(answers.get("status", [])) >= {"Учусь", "Работаю"}:
        flags.append("учится и работает")
    return flags


FACTOR_NAMES = {"engagement": "Вовлечённость", "availability": "Доступность", "experience": "Опыт",
                "direction_fit": "Направление", "quality": "Качество анкеты"}


def curator_card(app_id, user_id, answers, result):
    """Короткое сообщение в беседу кураторов."""
    def fmt(value):
        return "—" if value is None else f"{value:g}"

    factors = " · ".join(f"{FACTOR_NAMES[k]} {fmt(v)}" for k, v in result["factors"].items())
    lines = [
        f"Новая анкета №{app_id}: {answers.get('fio', '')} — vk.com/id{user_id}",
        f"Оценка {fmt(result['grade'])} из 3 · индекс {fmt(result['index'])}"
        + (f" · P(успеха) {result['p_success']:.0%}" if result["p_success"] is not None else ""),
        factors,
    ]
    if result["yellow_flags"]:
        lines.append("Флаги: " + ", ".join(result["yellow_flags"]))
    if result["summary"]:
        lines.append("\n" + result["summary"])
    if result["recommended_direction"]:
        lines.append(f"Рекомендуемое направление: {result['recommended_direction']}")
    if result["interview_questions"]:
        lines.append("\nВопросы для собеседования:")
        lines.extend(f"{i}. {q}" for i, q in enumerate(result["interview_questions"], 1))
    problems = [f for f in result["flags"] if re.search(r"попытка|ошибка LLM|не дала", f)]
    if problems:
        lines.append("\n⚠ " + "; ".join(problems))
    return "\n".join(lines)
