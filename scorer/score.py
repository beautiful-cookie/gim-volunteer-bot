"""Сборка баллов: пункты рубрики (правила + LLM) → факторы → индекс 0–100 → общая оценка 0–3."""
import math
from pathlib import Path

import yaml

from . import rules

ROOT = Path(__file__).resolve().parent.parent
HISTORICAL_DIRECTIONS = ["Организационное", "Проектное", "Фондовое", "Инклюзивное"]


def load_rubric(path=ROOT / "config" / "rubric.yaml"):
    rubric = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not rubric.get("use_proposed", True):
        rubric["items"] = [i for i in rubric["items"] if not i.get("proposed")]
    return rubric


def item_scores(c, rubric, llm=None):
    """Балл 0–3 по каждому пункту; None — вопрос не задавался или LLM не отработала."""
    out = {}
    for item in rubric["items"]:
        iid = item["id"]
        if item["method"] == "rule":
            out[iid] = rules.RULES[iid](c, item)
        elif iid == "experience":
            # Опыт не разобран (LLM не ответила на шаге классификации) — пункт пропускаем, а не ставим 0.
            if llm and llm.get("ok") and llm.get("experience_ok", True):
                out[iid] = rules.experience_from_categories(llm["categories"], item, llm["has_any_experience"])
            else:
                out[iid] = None
        elif iid == "direction_fit":
            gate = rules.direction_gate(c)
            out[iid] = gate if gate is not None else (llm["scores"].get(iid) if llm and llm.get("ok") else None)
        else:
            out[iid] = llm["scores"].get(iid) if llm and llm.get("ok") else None
    return out


def aggregate(scores, rubric):
    smax = rubric["scale_max"]
    items = rubric["items"]
    total_w = sum(i["weight"] for i in items)

    def wmean(subset):
        pairs = [(i["weight"], scores[i["id"]]) for i in subset if scores.get(i["id"]) is not None]
        w = sum(p[0] for p in pairs)
        return (round(sum(a * b for a, b in pairs) / w * 100 / smax, 1), w) if w else (None, 0)

    factors = {f: wmean([i for i in items if i["factor"] == f])[0] for f in rubric["factors"]}
    index, w = wmean(items)
    grade = None if index is None else sum(index >= t for t in rubric["grade_thresholds"])
    return dict(factors=factors, index=index, coverage=round(w / total_w, 2), grade=grade)


def _s(v):
    """NaN и None из таблицы → None, остальное → строка без пробелов по краям."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return str(v).strip()


def candidate_from_clean(row):
    """Кандидат из строки data/anketa_clean.csv (анкеты 2024–2025 гг.).

    В этих формах не было вопросов о статусе, часах в месяц, месте жительства и «Почему ГИМ» —
    такие поля остаются None и в индекс не входят.
    """
    get = lambda k: _s(row.get(k))
    course = get("course_num")
    study = ", ".join(x for x in [get("status"), f"{int(float(course))} курс" if course else None,
                                   get("edu_level"), get("vuz")] if x and x != "не указано")
    directions = [name for key, name in zip(["dir_org", "dir_project", "dir_fond", "dir_inclusive"],
                                            HISTORICAL_DIRECTIONS) if get(key) in ("1", "1.0")]
    return dict(
        id=get("id"),
        study_text=study or "",
        status_set=None, hours_month=None, geography=None, why_gim=None, friend_is_volunteer=None,
        edu_level=get("edu_level") or "",
        first_year_bach=get("first_year_bach") in ("1", "1.0"),
        faculty=get("faculty") or "", department=get("department") or "",
        profile_match=get("profile_match") or "не указано",
        sci_interests=get("sci_interests") or "",
        experience=get("experience") or "",
        expectations=get("expectations") or "",
        hobby=get("hobby") or "",
        superpower=get("superpower") or "",
        directions=directions, directions_offered=HISTORICAL_DIRECTIONS, undecided=False,
        directions_note=get("directions_note") or "",
        source=get("source") or "",
    )
