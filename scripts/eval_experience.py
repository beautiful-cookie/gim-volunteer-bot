"""Сравнение способов определять категории опыта с ручной разметкой data/experience_labels.xlsx.

Способы:
    «Прежний: только модель»          — категории из общего запроса, без фильтра ключевых слов;
    «Прежний: фильтр ключевых слов»   — цитата без слов категории выбрасывается (как было сначала);
    «Прежний: фильтр + перенос»       — неподходящая цитата переносится в категорию по словам (вчерашняя правка);
    «Новый: два шага»                 — выписать эпизоды, затем проверить категории по определениям.
Три «прежних» считаются из одних и тех же ответов модели, поэтому сравниваются честно.

Метрики по каждой категории: точность (сколько найденного верно) и полнота (сколько настоящего найдено).
Плюс совпадение итогового балла опыта 0–3 с баллом по разметке.

    python scripts/eval_experience.py              # все анкеты
    python scripts/eval_experience.py --limit 20   # пробно
Ответы GigaChat кэшируются: повторный запуск бесплатный.
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from scorer.experience import classify_experience  # noqa: E402
from scorer.extract import one_run  # noqa: E402
from scorer.llm import LLMError, make_provider  # noqa: E402
from scorer.quotes import normalize, quote_found  # noqa: E402
from scorer.rules import experience_from_categories  # noqa: E402
from scorer.score import candidate_from_clean, load_rubric  # noqa: E402
from scripts.score_anketa import write_xlsx  # noqa: E402

CATEGORIES = ["volunteering", "disability", "children", "archaeology", "museum_practice", "own_projects"]
METHODS = ["Прежний: только модель", "Прежний: фильтр ключевых слов", "Прежний: фильтр + перенос", "Новый: два шага"]


def single_prompt_rubric():
    rubric = load_rubric()
    for item in rubric["items"]:
        if item["id"] == "experience":
            item["classifier"] = "single_prompt"
    return rubric


def old_methods(c, rubric, provider, runs=3):
    """Три варианта прежнего способа из одних и тех же ответов общего запроса."""
    item = next(i for i in rubric["items"] if i["id"] == "experience")
    keywords = item["category_keywords"]
    exp_text = normalize(" ".join([c.get("experience") or "", c.get("hobby") or "", c.get("superpower") or ""]))
    votes = {method: {} for method in METHODS[:3]}
    has_any, done = [], 0
    for run in range(runs):
        answer = one_run(c, rubric, provider, 0.3, run)
        if answer is None:
            continue
        done += 1
        has_any.append(answer.experience.has_any_experience)
        for cat, quote in answer.experience.categories.items():
            if cat not in CATEGORIES or not quote or not quote_found(quote, exp_text):
                continue
            lowered = quote.lower()
            votes[METHODS[0]][cat] = votes[METHODS[0]].get(cat, 0) + 1
            if re.search(keywords[cat], lowered):
                hits = {cat} | {s for s in item["strong"] if re.search(keywords[s], lowered)}
                moved = hits
            else:
                hits = set()
                moved = {k for k, pattern in keywords.items() if re.search(pattern, lowered)}
            for h in hits:
                votes[METHODS[1]][h] = votes[METHODS[1]].get(h, 0) + 1
            for h in moved:
                votes[METHODS[2]][h] = votes[METHODS[2]].get(h, 0) + 1
    any_experience = sum(has_any) > done / 2
    return {method: ({k for k, n in v.items() if n > done / 2}, any_experience) for method, v in votes.items()}


def metrics(rows, method):
    out = []
    for cat in CATEGORIES + ["все категории"]:
        cats = CATEGORIES if cat == "все категории" else [cat]
        tp = sum(1 for r in rows for k in cats if k in r["gold"] and k in r[method])
        fp = sum(1 for r in rows for k in cats if k not in r["gold"] and k in r[method])
        fn = sum(1 for r in rows for k in cats if k in r["gold"] and k not in r[method])
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        out.append({"способ": method, "категория": cat, "найдено верно": tp, "лишнее": fp, "пропущено": fn,
                    "точность": None if precision is None else round(precision, 2),
                    "полнота": None if recall is None else round(recall, 2)})
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default=str(ROOT / "data" / "experience_labels.xlsx"))
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default=str(ROOT / "data" / "experience_eval.xlsx"))
    a = ap.parse_args()

    labels = pd.read_excel(a.labels).set_index("id")
    reviewed = labels["проверено"].notna() & (labels["проверено"].astype(str).str.strip() != "")
    print(f"Разметка: {len(labels)} анкет, проверено человеком: {int(reviewed.sum())}"
          + ("" if reviewed.any() else " — пока сравниваем с черновой разметкой Claude"))
    clean = pd.read_csv(ROOT / "data" / "anketa_clean.csv")
    if a.limit:
        clean = clean.head(a.limit)

    provider = make_provider("auto")
    old_rubric, new_rubric = single_prompt_rubric(), load_rubric()
    item = next(i for i in new_rubric["items"] if i["id"] == "experience")
    rows = []
    for n, (_, record) in enumerate(clean.iterrows(), 1):
        c = candidate_from_clean(record.to_dict())
        gold_row = labels.loc[c["id"]]
        row = {"id": c["id"], "опыт": c["experience"], "gold": {k for k in CATEGORIES if gold_row[k] == 1},
               "gold_any": bool(gold_row["has_any_experience"]), "комментарий": gold_row["комментарий"]}
        try:
            for method, (cats, any_exp) in old_methods(c, old_rubric, provider).items():
                row[method], row[method + " · есть опыт"] = cats, any_exp
            new = classify_experience(c, provider, new_rubric)
        except LLMError as error:
            print(f"  {c['id']}: LLM недоступна ({error}) — пропускаем")
            continue
        row[METHODS[3]] = set(new.get("categories", {}))
        row[METHODS[3] + " · есть опыт"] = new.get("has_any_experience", False)
        rows.append(row)
        print(f"  {n}/{len(clean)} {c['id']}: разметка {sorted(row['gold'])} · новый {sorted(row[METHODS[3]])}"
              f" · прежний+фильтр {sorted(row[METHODS[1]])}", flush=True)

    summary, per_category, differences = [], [], []
    for method in METHODS:
        per_category += metrics(rows, method)
        gold_scores = [experience_from_categories(r["gold"], item, r["gold_any"]) for r in rows]
        scores = [experience_from_categories(r[method], item, r[method + " · есть опыт"]) for r in rows]
        exact = sum(g == s for g, s in zip(gold_scores, scores)) / len(rows)
        close = sum(abs(g - s) <= 1 for g, s in zip(gold_scores, scores)) / len(rows)
        total = next(m for m in metrics(rows, method) if m["категория"] == "все категории")
        summary.append({"способ": method, "точность категорий": total["точность"], "полнота категорий": total["полнота"],
                        "балл опыта совпал": round(exact, 2), "балл опыта ±1": round(close, 2),
                        "лишних категорий": total["лишнее"], "пропущено категорий": total["пропущено"]})
    for r in rows:
        if any(r[m] != r["gold"] for m in METHODS):
            differences.append({"id": r["id"], "опыт": r["опыт"], "разметка": ", ".join(sorted(r["gold"])),
                                **{m: ", ".join(sorted(r[m])) for m in METHODS}, "комментарий разметки": r["комментарий"]})

    summary = pd.DataFrame(summary)
    write_xlsx(a.out, {"Сводка": summary, "По категориям": pd.DataFrame(per_category),
                       "Расхождения": pd.DataFrame(differences)})
    print(f"\nАнкет в сравнении: {len(rows)}\n" + summary.to_string(index=False))
    print(f"LLM: новых вызовов {provider.calls}, из кэша {provider.hits}\nФайл: {a.out}")


if __name__ == "__main__":
    main()
