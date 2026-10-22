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


def factors_with_data(raw, factors, min_share=0.5):
    """Факторы, по которым есть баллы хотя бы у половины анкет, — только их показываем куратору.

    «Подходит направлению» оценивает нейросеть. Без её оценки правило ставит 0 лишь тем,
    кто выбрал все направления или «не определился», у остальных балла нет — и среднее выходит нулём.
    """
    items_by_factor = {}
    for item in load_rubric()["items"]:
        items_by_factor.setdefault(item["factor"], []).append(f"s_{item['id']}")
    shown = {}
    for factor, title in factors.items():
        columns = [c for c in items_by_factor.get(factor, []) if c in raw.columns]
        if columns and raw[columns].notna().any(axis=1).mean() >= min_share:
            shown[factor] = title
    return shown


def grade_thresholds():
    """Пороги индекса для оценок 1, 2, 3 (например, 40 / 55 / 70)."""
    return load_rubric()["grade_thresholds"]
