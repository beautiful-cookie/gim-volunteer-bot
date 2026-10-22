"""Важность факторов по шкале 1–5 — то, что куратор двигает ползунками.

В рубрике веса стоят у вопросов (0–5, от представителя музея), а вес фактора — сумма весов его вопросов.
Чтобы куратору не приходилось думать о каждом вопросе, ползунков пять — по одному на фактор:

    важность по умолчанию = сумма весов вопросов фактора, приведённая к шкале 1–5;
    вес вопроса           = вес из рубрики × (важность на ползунке / важность по умолчанию).

Пока ползунки стоят по умолчанию, рейтинг совпадает с весами представителя один в один.
"""
from scorer.score import load_rubric


def factor_defaults():
    """Важность факторов по умолчанию, 1–5."""
    rubric = load_rubric()
    totals = {factor: 0 for factor in rubric["factors"]}
    for item in rubric["items"]:
        totals[item["factor"]] += item["weight"]
    biggest = max(totals.values())
    return {factor: max(1, round(total / biggest * 5)) for factor, total in totals.items()}


def item_weights(factor_importance):
    """Веса вопросов для пересчёта индекса (dashboard.data.apply_weights) по важности факторов."""
    defaults = factor_defaults()
    weights = {}
    for item in load_rubric()["items"]:
        factor = item["factor"]
        weights[item["id"]] = item["weight"] * factor_importance[factor] / defaults[factor]
    return weights


def grade_thresholds():
    """Пороги индекса для оценок 1, 2, 3 (например, 40 / 55 / 70)."""
    return load_rubric()["grade_thresholds"]
