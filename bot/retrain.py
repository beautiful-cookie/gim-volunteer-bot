"""Самообучение модели успеха на ответах опроса через четыре месяца.

Каждый пройденный опрос — новая метка «успешный волонтёр» (правило в rubric.yaml, checkin_survey.success).
Когда меток с прошлой попытки накопилось достаточно (min_new_labels), модель переобучается:
    1. Выборка: прошлые наборы (часы активности из таблиц музея, если есть data/scored.xlsx)
       + волонтёры из бота с пройденным опросом. Признаки — те же, что в scripts/model_success.py.
    2. Та же модель с экспертным априором: logit P = b0 + b1·индекс + Σγ·z, штраф только на поправки γ.
    3. Проверка: AUC новой модели — leave-pair-out (каждая пара «успешный/неуспешный» оценивается моделью,
       обученной без этой пары), AUC действующей — на тех же парах. Для прошлых наборов действующая модель
       видела эти данные при обучении, так что сравнение строже к новой модели, чем к старой.
    4. Новая версия принимается, только если ранжирует не хуже действующей. Все попытки, и принятые,
       и отклонённые, записываются в таблицу model_versions — их видно в дашборде.
    5. После принятия пересчитываем P(успеха) у всех анкет бота.

Запускается сам в боте (bot/vk_bot.py) или вручную: python scripts/retrain_model.py
"""
import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from bot.application import current_model, model_features, success_probability
from bot.survey import is_success
from scorer.score import load_rubric
from scripts.model_success import (Z_COLS, Standardizer, fit_prior_logit, inner_lambda, load, pair_outcomes_lpo,
                                   pair_outcomes_raw, pairs_of)

ROOT = Path(__file__).resolve().parent.parent
FEATURES = ["index"] + Z_COLS
MAX_PAIRS = 1500   # дальше пар становится слишком много для leave-pair-out; берём случайные


def history_rows(hours_per_year, scored=ROOT / "data" / "scored.xlsx", clean=ROOT / "data" / "anketa_clean.csv"):
    """Взятые волонтёры прошлых наборов с известными часами: признаки и метка y."""
    if not Path(scored).exists() or not Path(clean).exists():
        return pd.DataFrame(columns=FEATURES + ["y"])
    d = load(scored, clean)
    d = d[(d["taken"] == 1) & d["hours_per_year"].notna() & d["index"].notna()]
    rows = d[FEATURES].copy()
    rows["y"] = (d["hours_per_year"] >= hours_per_year).astype(int)
    return rows.reset_index(drop=True)


def survey_rows(storage, rule):
    """Волонтёры из бота, прошедшие опрос: признаки из их анкеты и метка из ответов опроса."""
    applications = {a["id"]: a for a in storage.all_applications()}
    rows = []
    for survey in storage.all_surveys():
        application = applications.get(survey["app_id"])
        if survey["status"] != "completed" or not application or not application["result"]:
            continue
        label = is_success(survey["answers"], rule)
        features = model_features(application["answers"], application["result"])
        if label is None or features["index"] is None:
            continue
        rows.append({**{name: features.get(name) for name in FEATURES}, "y": int(label)})
    return pd.DataFrame(rows, columns=FEATURES + ["y"], dtype=float)


def to_model(w, sp, sz, y, lam, n_history, n_survey):
    """Коэффициенты в том же формате, что config/model.json, — их понимает bot.application.success_probability."""
    return dict(
        created=datetime.date.today().isoformat(), target="опрос через 4 месяца + часы прошлых наборов",
        n=len(y), n_history=n_history, n_survey=n_survey, active_share=round(float(y.mean()), 3), lam=lam,
        features=FEATURES, coefficients=dict(zip(["intercept"] + FEATURES, map(float, w))),
        mean={"index": float(sp.mean["index"]), **{k: float(v) for k, v in sz.mean.items()}},
        std={"index": float(sp.std["index"]), **{k: float(v) for k, v in sz.std.items()}},
    )


def retrain(storage, force=False, with_history=True, seed=2026):
    """Переобучить модель, если накопились новые метки. Возвращает отчёт или None, если обучать рано."""
    config = load_rubric()["checkin_survey"]
    survey = survey_rows(storage, config["success"])
    versions = storage.model_versions()
    seen = versions[-1]["n_survey"] if versions else 0
    if not force and len(survey) - seen < config["min_new_labels"]:
        return None

    history = history_rows(config["history_success_hours_per_year"]) if with_history else survey.iloc[:0]
    data = pd.concat([history, survey], ignore_index=True)
    y = data["y"].astype(int)
    report = dict(n_history=len(history), n_survey=len(survey), auc_new=None, auc_old=None, accepted=False)
    if len(data) < 10 or y.nunique() < 2:
        report["note"] = "мало данных: нужно хотя бы 10 волонтёров, среди них и успешные, и нет"
        storage.add_model_version(len(history), len(survey), None, None, False, {}, report["note"])
        return report

    prior, Z = data[["index"]], data[Z_COLS]
    lam = inner_lambda(prior, Z, y)
    pairs = pairs_of(y)
    if len(pairs) > MAX_PAIRS:
        chosen = np.random.default_rng(seed).choice(len(pairs), MAX_PAIRS, replace=False)
        pairs = [pairs[i] for i in chosen]
    auc_new = float(pair_outcomes_lpo(prior, Z, y, lam, pairs).mean())

    old = current_model(storage)
    if old:
        old_scores = [success_probability(row, old) for row in data[FEATURES].to_dict("records")]
        auc_old = float(pair_outcomes_raw(np.array(old_scores, dtype=float), pairs).mean())
    else:
        auc_old = None
    accepted = auc_old is None or auc_new >= auc_old

    sp, sz = Standardizer(prior), Standardizer(Z)
    w = fit_prior_logit(sp(prior).ravel(), sz(Z), y.to_numpy(), lam)
    model = to_model(w, sp, sz, y, lam, len(history), len(survey))
    if accepted:
        note = f"принята: AUC {auc_new:.2f}" + (f" против {auc_old:.2f} у прежней" if auc_old is not None else "")
    else:
        note = f"отклонена: AUC {auc_new:.2f} хуже, чем {auc_old:.2f} у действующей — оставили прежнюю"
    storage.add_model_version(len(history), len(survey), round(auc_new, 3),
                              None if auc_old is None else round(auc_old, 3), accepted, model, note)
    report.update(auc_new=round(auc_new, 3), auc_old=None if auc_old is None else round(auc_old, 3),
                  accepted=accepted, note=note, lam=lam)
    if accepted:
        report["updated"] = refresh_probabilities(storage, model)
    return report


def refresh_probabilities(storage, model):
    """Пересчитать P(успеха) у всех оценённых анкет бота по новой модели. Возвращает, сколько анкет обновлено."""
    updated = 0
    for application in storage.all_applications():
        result = application["result"]
        if application["status"] != "scored" or not result or result.get("index") is None:
            continue
        result["p_success"] = success_probability(model_features(application["answers"], result), model)
        storage.save_result(application["id"], result)
        updated += 1
    return updated
