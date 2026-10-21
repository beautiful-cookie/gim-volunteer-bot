"""Шаг 3: факторный анализ пунктов рубрики и модель вероятности успешности волонтёра.

1. Разведочный факторный анализ: проверяем, складываются ли пункты рубрики в факторы,
   которые задал представитель. KMO, критерий Бартлетта, параллельный анализ, нагрузки после promax.
2. Модель P(успеха): логистическая регрессия с экспертным априором
       logit P = b0 + b1·I_эксперт + Σ γ_j·z_j,   штраф λ·Σγ² только на поправки γ.
   При малых данных модель держится весов представителя, с ростом данных учится поправкам.
   λ выбирается вложенной кросс-валидацией (leave-one-out), сравнение — с баллом куратора.

Запуск (после scripts/score_anketa.py):
    python scripts/model_success.py
Результат: data/model_report.xlsx и config/model.json (коэффициенты для бота и дашборда).
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import chi2, spearmanr
from sklearn.metrics import brier_score_loss, roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.score_anketa import write_xlsx  # noqa: E402

CATEGORIES = ["volunteering", "disability", "children", "archaeology", "museum_practice", "own_projects"]
FA_ITEMS = ["s_expectations", "s_form_quality", "s_direction_fit", "s_source", "s_course", "s_faculty", "s_hobby"]
LAMBDAS = [0.3, 1, 3, 10, 30, 100]
SEED = 2026


# ---------------------------------------------------------------- данные

def load(scored_path, clean_path):
    s = pd.read_excel(scored_path, sheet_name="Баллы")
    c = pd.read_csv(clean_path)[["id", "first_year_bach", "source", "profile_match", "years_in_program",
                                 "still_in_program"]]
    d = s.merge(c, on="id", how="left")
    cats = d.get("exp_categories", pd.Series("", index=d.index)).fillna("")
    for k in CATEGORIES:
        d[f"cat_{k}"] = cats.str.contains(rf"\b{k}:").astype(int)
    d["friend"] = (d["source"] == "Рекомендации друзей").astype(int)
    return d


# ---------------------------------------------------------------- факторный анализ

def kmo(r):
    inv = np.linalg.pinv(r)
    partial = -inv / np.sqrt(np.outer(np.diag(inv), np.diag(inv)))
    off = ~np.eye(len(r), dtype=bool)
    r2, p2 = (r[off] ** 2).sum(), (partial[off] ** 2).sum()
    per_item = [(r[i][off[i]] ** 2).sum() / ((r[i][off[i]] ** 2).sum() + (partial[i][off[i]] ** 2).sum())
                for i in range(len(r))]
    return r2 / (r2 + p2), per_item


def bartlett(r, n):
    p = len(r)
    stat = -(n - 1 - (2 * p + 5) / 6) * np.log(np.linalg.det(r))
    df = p * (p - 1) / 2
    return stat, chi2.sf(stat, df)


def parallel_analysis(n, p, iters=500, seed=SEED):
    rng = np.random.default_rng(seed)
    ev = [np.sort(np.linalg.eigvalsh(np.corrcoef(rng.standard_normal((n, p)), rowvar=False)))[::-1]
          for _ in range(iters)]
    return np.percentile(ev, 95, axis=0)


def paf(r, k, iters=200):
    """Метод главных осей: итеративная оценка общностей."""
    r = r.copy()
    h2 = 1 - 1 / np.diag(np.linalg.pinv(r))
    for _ in range(iters):
        rr = r.copy()
        np.fill_diagonal(rr, h2)
        w, v = np.linalg.eigh(rr)
        idx = np.argsort(w)[::-1][:k]
        load = v[:, idx] * np.sqrt(np.clip(w[idx], 1e-6, None))
        new = (load ** 2).sum(1)
        if np.max(np.abs(new - h2)) < 1e-5:
            break
        h2 = np.clip(new, 0.005, 0.995)
    return load


def varimax(a, iters=100, tol=1e-6):
    p, k = a.shape
    rot = np.eye(k)
    d = 0
    for _ in range(iters):
        lam = a @ rot
        u, s, vt = np.linalg.svd(a.T @ (lam ** 3 - lam @ np.diag((lam ** 2).sum(0)) / p))
        rot = u @ vt
        if s.sum() < d * (1 + tol):
            break
        d = s.sum()
    return a @ rot


def promax(a, power=4):
    """Косоугольное вращение: факторы могут коррелировать, как и критерии музея."""
    v = varimax(a)
    target = np.sign(v) * np.abs(v) ** power
    u = np.linalg.lstsq(v, target, rcond=None)[0]
    u = u @ np.diag(np.sqrt(np.diag(np.linalg.inv(u.T @ u))))
    return v @ u


def factor_analysis(d):
    x = pd.DataFrame({k: d[k] for k in FA_ITEMS})
    x["s_experience"] = d["s_experience"]
    for k in CATEGORIES:
        x[f"cat_{k}"] = d[f"cat_{k}"]
    # Пункт без оценок у большинства анкет (не было вопроса или LLM не отработала) в анализ не берём.
    sparse = [col for col in x if x[col].notna().mean() < 0.5]
    x = x.drop(columns=sparse).dropna()
    # Пункты почти без разброса (≥ 95 % одинаковых ответов) корреляций не дают.
    keep = [col for col in x if x[col].value_counts(normalize=True).iloc[0] < 0.95]
    dropped = sparse + [col for col in x if col not in keep]
    x = x[keep]
    r = spearmanr(x).statistic
    n, p = x.shape
    k_all, k_items = kmo(r)
    b_stat, b_p = bartlett(r, n)
    ev = np.sort(np.linalg.eigvalsh(r))[::-1]
    pa = parallel_analysis(n, p)
    n_factors = max(1, int((ev > pa).sum()))
    load = promax(paf(r, n_factors)) if n_factors > 1 else paf(r, 1)

    summary = pd.DataFrame([
        ("Анкет в анализе", n, ""), ("Пунктов", p, "исключены без разброса: " + (", ".join(dropped) or "нет")),
        ("KMO", round(k_all, 3), "≥ 0,6 — данные пригодны для факторного анализа, < 0,5 — нет"),
        ("Бартлетт χ²", round(b_stat, 1), f"p = {b_p:.2g}: корреляции отличны от нуля"),
        ("Факторов по параллельному анализу", n_factors, "собственные числа выше 95-го перцентиля случайных"),
    ], columns=["Показатель", "Значение", "Комментарий"])
    eig = pd.DataFrame({"фактор": range(1, p + 1), "собственное число": ev.round(3), "порог (случайные, 95 %)": pa.round(3)})
    loadings = pd.DataFrame(load.round(2), index=keep, columns=[f"F{i + 1}" for i in range(load.shape[1])])
    loadings["KMO пункта"] = np.round(k_items, 2)
    loadings["общность h²"] = (load ** 2).sum(1).round(2)
    return summary, eig, loadings.reset_index().rename(columns={"index": "пункт"})


# ---------------------------------------------------------------- модель

def fit_prior_logit(prior, z, y, lam):
    """b0, b1 без штрафа; поправки γ со штрафом λ·Σγ²."""
    X = np.column_stack([np.ones(len(y)), prior, z])

    def loss(w):
        eta = X @ w
        ll = np.sum(np.logaddexp(0, eta) - y * eta)
        g = X.T @ (1 / (1 + np.exp(-eta)) - y)
        pen = lam * np.sum(w[2:] ** 2)
        g[2:] += 2 * lam * w[2:]
        return ll + pen, g

    return minimize(loss, np.zeros(X.shape[1]), jac=True, method="L-BFGS-B").x


def predict(w, prior, z):
    return 1 / (1 + np.exp(-(w[0] + w[1] * prior + z @ w[2:])))


class Standardizer:
    def __init__(self, df):
        self.mean, self.std = df.mean(), df.std(ddof=0).replace(0, 1)

    def __call__(self, df):
        return ((df - self.mean) / self.std).fillna(0).to_numpy()


def logloss(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))


def loo_predict(prior, Z, y, lam_choice):
    """Leave-one-out; λ на каждом шаге выбирается внутренним LOO по log-loss (вложенная проверка)."""
    n = len(y)
    out, chosen = np.zeros(n), []
    for i in range(n):
        tr = np.arange(n) != i
        lam = lam_choice(prior[tr], Z[tr], y[tr]) if callable(lam_choice) else lam_choice
        chosen.append(lam)
        sp, sz = Standardizer(prior[tr]), Standardizer(Z[tr])
        w = fit_prior_logit(sp(prior[tr]).ravel(), sz(Z[tr]), y[tr].to_numpy(), lam)
        out[i] = predict(w, sp(prior.iloc[[i]]).ravel(), sz(Z.iloc[[i]]))[0]
    return out, chosen


def kfold_predict(prior, Z, y, lam, k=5, seed=SEED):
    folds = np.random.default_rng(seed).permutation(len(y)) % k
    out = np.zeros(len(y))
    for f in range(k):
        tr, te = folds != f, folds == f
        sp, sz = Standardizer(prior[tr]), Standardizer(Z[tr])
        w = fit_prior_logit(sp(prior[tr]).ravel(), sz(Z[tr]), y[tr].to_numpy(), lam)
        out[te] = predict(w, sp(prior[te]).ravel(), sz(Z[te]))
    return out


def inner_lambda(prior, Z, y):
    """λ по 5-кратной проверке на обучающей части (внутренний цикл вложенной проверки)."""
    scores = {lam: logloss(y.to_numpy(), kfold_predict(prior, Z, y, lam)) for lam in LAMBDAS}
    return min(scores, key=scores.get)


def pairs_of(y):
    y = np.asarray(y)
    return [(i, j) for i in np.flatnonzero(y == 1) for j in np.flatnonzero(y == 0)]


def pair_outcomes_raw(score, pairs):
    """Для готового балла: 1, если активный выше неактивного, 0,5 при равенстве."""
    s = np.asarray(score, dtype=float)
    return np.array([1.0 if s[i] > s[j] else 0.5 if s[i] == s[j] else 0.0 for i, j in pairs])


def pair_outcomes_lpo(prior, Z, y, lam, pairs):
    """Leave-pair-out: модель учится без пары (активный, неактивный) и ранжирует их.
    Несмещённая оценка AUC на малых выборках, в отличие от leave-one-out."""
    out = []
    n = len(y)
    for i, j in pairs:
        tr = np.ones(n, dtype=bool)
        tr[[i, j]] = False
        sp, sz = Standardizer(prior[tr]), Standardizer(Z[tr])
        w = fit_prior_logit(sp(prior[tr]).ravel(), sz(Z[tr]), y[tr].to_numpy(), lam)
        p = predict(w, sp(prior.iloc[[i, j]]).ravel(), sz(Z.iloc[[i, j]]))
        out.append(1.0 if p[0] > p[1] else 0.5 if p[0] == p[1] else 0.0)
    return np.array(out)


def compare(outcomes, pairs, n, n_boot=2000, seed=SEED):
    """AUC = среднее по парам. ДИ и сравнение с баллом куратора — бутстрэп кандидатов без переобучения:
    пара входит в выборку с весом (кратность i) × (кратность j)."""
    rng = np.random.default_rng(seed)
    I, J = np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs])
    names = list(outcomes)
    boot = {k: [] for k in names}
    for _ in range(n_boot):
        cnt = np.bincount(rng.integers(0, n, n), minlength=n)
        wts = cnt[I] * cnt[J]
        if wts.sum() == 0:
            continue
        for k in names:
            boot[k].append(np.average(outcomes[k], weights=wts))
    base = np.array(boot[names[0]])
    rows = []
    for k in names:
        b = np.array(boot[k])
        diff = b - base
        rows.append({"модель": k, "AUC": round(float(outcomes[k].mean()), 3),
                     "95 % ДИ": f"{np.percentile(b, 2.5):.2f}–{np.percentile(b, 97.5):.2f}",
                     "Δ к баллу куратора": "" if k == names[0] else f"{float(outcomes[k].mean() - outcomes[names[0]].mean()):+.2f}",
                     "P(Δ > 0)": "" if k == names[0] else round(float((diff > 0).mean()), 2)})
    return pd.DataFrame(rows)


Z_COLS = ["F_engagement", "F_experience", "F_direction_fit", "F_quality", "F_availability",
          "first_year_bach", "cat_museum_practice", "friend"]


def model(d, threshold):
    t = d[(d.taken == 1) & d.hours_per_year.notna() & d["index"].notna()].reset_index(drop=True)
    y = (t.hours_per_year >= threshold).astype(int)
    prior, Z = t[["index"]], t[Z_COLS]

    # λ выбирается один раз 5-кратной проверкой на всей выборке: небольшой оптимизм оценки, указан в отчёте.
    lam = inner_lambda(prior, Z, y)
    pairs = pairs_of(y)
    outcomes = {"Балл куратора 0–3": pair_outcomes_raw(t.screen_score, pairs),
                "Индекс по весам представителя": pair_outcomes_raw(t["index"], pairs),
                f"Индекс + поправки модели (LPO, λ = {lam:g})": pair_outcomes_lpo(prior, Z, y, lam, pairs)}
    auc = compare(outcomes, pairs, len(y))

    p_strong, _ = loo_predict(prior, Z, y, 1e6)       # γ ≈ 0: только индекс представителя, с калибровкой
    p_model, _ = loo_predict(prior, Z, y, lam)
    brier = pd.DataFrame([dict(модель="Индекс, откалиброванный (LOO)", Brier=round(brier_score_loss(y, p_strong), 3)),
                          dict(модель="Индекс + поправки модели (LOO)", Brier=round(brier_score_loss(y, p_model), 3)),
                          dict(модель="Константа: доля активных", Brier=round(brier_score_loss(y, np.full(len(y), y.mean())), 3))])
    lams = [lam]
    sp, sz = Standardizer(prior), Standardizer(Z)
    w = fit_prior_logit(sp(prior).ravel(), sz(Z), y.to_numpy(), lam)
    coefs = pd.DataFrame({"признак": ["intercept", "index"] + Z_COLS, "коэффициент (на 1 SD)": w.round(3),
                          "среднее": [np.nan, sp.mean["index"]] + list(sz.mean.round(3)),
                          "SD": [np.nan, sp.std["index"]] + list(sz.std.round(3))})
    meta = dict(n=len(y), active_share=round(float(y.mean()), 3), threshold=threshold, lam=lam,
                lam_counts=pd.Series(lams).value_counts().to_dict())
    return auc, brier, coefs, meta, (w, sp, sz)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scored", default=str(ROOT / "data" / "scored.xlsx"))
    ap.add_argument("--clean", default=str(ROOT / "data" / "anketa_clean.csv"))
    ap.add_argument("--threshold", type=float, default=20, help="успех = часов в год не меньше порога")
    ap.add_argument("--out", default=str(ROOT / "data" / "model_report.xlsx"))
    ap.add_argument("--model-json", default=str(ROOT / "config" / "model.json"))
    a = ap.parse_args()

    d = load(a.scored, a.clean)
    llm_share = d["s_expectations"].notna().mean()
    print(f"Анкет: {len(d)}, с LLM-оценками: {llm_share:.0%}")

    fa_summary, eig, loadings = factor_analysis(d)
    print("\n" + fa_summary.to_string(index=False))
    print("\n" + loadings.to_string(index=False))

    sheets = {"Факторный анализ": fa_summary, "Собственные числа": eig, "Нагрузки": loadings}
    for thr in sorted({a.threshold, 10, 30}):
        auc, brier, coefs, meta, fitted = model(d, thr)
        print(f"\n=== Успех: ≥ {thr:g} ч/год · n = {meta['n']}, доля активных {meta['active_share']}, λ = {meta['lam']}")
        print(auc.to_string(index=False))
        sheets[f"AUC ≥{thr:g}ч"] = auc
        if thr == a.threshold:
            print(brier.to_string(index=False))
            print(coefs.to_string(index=False))
            sheets["Brier"], sheets["Коэффициенты"] = brier, coefs
            main_meta, (w, sp, sz) = meta, fitted

    d["P_success"] = predict(w, sp(d[["index"]]).ravel(), sz(d[Z_COLS])).round(3)
    sheets["Прогноз"] = d[["id", "cohort", "screen_score", "stage", "hours_per_year", "index", "grade", "P_success"]]
    write_xlsx(a.out, sheets)

    Path(a.model_json).write_text(json.dumps(dict(
        created=dt.date.today().isoformat(), target=f"hours_per_year >= {a.threshold:g}", **main_meta,
        features=["index"] + Z_COLS, coefficients=dict(zip(["intercept", "index"] + Z_COLS, map(float, w))),
        mean={"index": float(sp.mean["index"]), **{k: float(v) for k, v in sz.mean.items()}},
        std={"index": float(sp.std["index"]), **{k: float(v) for k, v in sz.std.items()}},
        note="Признаки стандартизуются (x − mean) / std, пропуски → 0 (среднее). Обучено на малой выборке: пересобирать после каждого набора.",
    ), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\nФайлы: {a.out}, {a.model_json}")


if __name__ == "__main__":
    main()
