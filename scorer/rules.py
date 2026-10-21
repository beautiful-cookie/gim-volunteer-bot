"""Пункты рубрики, которые считаются правилами по структурированным полям анкеты.

Кандидат — словарь с полями, описанными в scorer.candidate. None в поле означает, что вопрос
не задавался: пункт пропускается. Пустая строка — вопрос задан, ответа нет: пункт = 0.
"""
import re

NO_HOBBY = re.compile(r"^(нет|не знаю|отсутству\w*|нету)\.?$", re.I)


def source(c, item):
    p = item["points"]
    if c.get("source") is None:
        return None
    if c["source"] == "Рекомендации друзей":
        return p["friend_volunteer"] if c.get("friend_is_volunteer") else p["friends"]
    return p["empty"] if c["source"] in ("", "не указано") else p["other"]


def status(c, item):
    s = c.get("status_set")
    if s is None:
        return None
    p = item["points"]
    if not s:
        return p["empty"]
    return p["study_and_work"] if {"study", "work"} <= s else p["single"]


def course(c, item):
    p = item["points"]
    level = c.get("edu_level")
    if level is None:
        return None
    if c.get("first_year_bach"):
        return p["first_year_bach"]
    if level in ("бакалавриат", "магистратура", "специалитет", "высшее (окончено)"):
        return p["senior_or_graduate"]
    if level in ("СПО", "ДПО / переподготовка"):
        return p["spo_or_dpo"]
    return p["empty"]


def hours_month(c, item):
    h = c.get("hours_month")
    if h is None:
        return None
    return next(points for threshold, points in item["steps"] if h >= threshold)


def geography(c, item):
    g = c.get("geography")
    if g is None:
        return None
    return item["points"].get(g or "empty", 0)


def faculty(c, item):
    m = c.get("profile_match")
    if m is None:
        return None
    return item["points"][{"профильное": "profile", "смежное": "related", "непрофильное": "other"}.get(m, "empty")]


def hobby(c, item):
    h = c.get("hobby")
    if h is None:
        return None
    return item["points"]["none" if not h.strip() or NO_HOBBY.match(h.strip()) else "any"]


def direction_gate(c):
    """0 по правилу представителя: «пока не определился» или выбраны все направления разом; иначе None → LLM."""
    chosen, offered = c.get("directions") or [], c.get("directions_offered") or []
    if c.get("directions") is None:
        return None
    if c.get("undecided") or not chosen or (offered and set(chosen) >= set(offered)):
        return 0
    return None


def experience_from_categories(found, item, has_any):
    """Балл опыта по найденным категориям: сильные (музей, раскопки) или 2+ → 3, одна → 2, вне списка → 1."""
    if any(k in found for k in item["strong"]) or len(found) >= 2:
        return 3
    if len(found) == 1:
        return 2
    return 1 if has_any else 0


RULES = {"source": source, "status": status, "course": course, "hours_month": hours_month,
         "geography": geography, "faculty": faculty, "hobby": hobby}
