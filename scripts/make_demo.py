"""Демонстрационная база: вымышленные кандидаты, решения кураторов, опрос волонтёров и версия модели.

Нужна, чтобы показать систему (жюри, музею) без настоящих анкет: реальные анкеты — персональные данные,
их в поставку не кладём. Баллы считаются настоящей рубрикой (config/rubric.yaml) по правилам; только
пункты, которые обычно оценивает GigaChat, здесь заданы вымышленным «уровнем» кандидата — без вызовов LLM.

    python scripts/make_demo.py                     # создаёт data/demo.sqlite3 (старая перезаписывается)
    GIM_BOT_DB=data/demo.sqlite3 streamlit run dashboard/app.py
    docker compose --profile demo up -d             # то же в Docker: дашборд на http://localhost:8502

Имена составлены случайно из частых имён и фамилий; ссылок на страницы ВКонтакте у демо-кандидатов нет.
"""
import datetime
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.application import current_model, model_features, success_probability, to_candidate, yellow_flags  # noqa: E402
from bot.retrain import retrain  # noqa: E402
from bot.storage import Storage  # noqa: E402
from scorer.score import aggregate, item_scores, load_rubric  # noqa: E402

DB = ROOT / "data" / "demo.sqlite3"
CANDIDATES = 46
SEED = 2026

FIRST_NAMES = ["Анна", "Мария", "Дарья", "Ксения", "Полина", "Елизавета", "Софья", "Алиса", "Вера", "Ульяна",
               "Илья", "Артём", "Никита", "Матвей", "Глеб", "Тимофей", "Егор", "Лев"]
LAST_NAMES = ["Соколов", "Лебедев", "Морозов", "Волков", "Зайцев", "Орлов", "Белов", "Комаров", "Киселёв",
              "Ершов", "Голубев", "Тихонов", "Фомин", "Гусев", "Мельников", "Щербаков"]
FEMALE = set(FIRST_NAMES[:10])
FACULTIES = ["Исторический факультет, музеология", "Исторический факультет, история России",
             "Факультет искусствоведения", "Филологический факультет", "Факультет журналистики",
             "Факультет психологии", "Экономический факультет", "Факультет компьютерных наук"]

# Опыт: текст ответа, категории с цитатой, фраза для саммари. Сильный опыт — в начале списка.
EXPERIENCE = [
    ("Летняя практика в Музее истории Москвы: помогала с описью фондов и проводила экскурсии для школьников",
     {"museum_practice": "практика в Музее истории Москвы", "children": "экскурсии для школьников"},
     "Музейная практика с работой в фондах и экскурсиями для школьников"),
    ("Две археологические экспедиции под Великим Новгородом, камеральная обработка находок",
     {"archaeology": "две археологические экспедиции"}, "Опыт археологических экспедиций"),
    ("Волонтёр инклюзивного центра: сопровождал(а) группы людей с нарушениями зрения на прогулках",
     {"disability": "сопровождал(а) группы людей с нарушениями зрения", "volunteering": "волонтёр инклюзивного центра"},
     "Волонтёрство с людьми с нарушениями зрения"),
    ("Организовал(а) исторический квест для первокурсников и веду телеграм-канал о московских усадьбах",
     {"own_projects": "организовал(а) исторический квест"}, "Свои проекты: квест и канал об истории"),
    ("Волонтёр на фестивале «Времена и эпохи» и на Ночи музеев",
     {"volunteering": "волонтёр на фестивале «Времена и эпохи»"}, "Волонтёрство на исторических фестивалях"),
    ("Два лета вожатым(ой) в детском лагере", {"children": "вожатым(ой) в детском лагере"}, "Работа вожатым в лагере"),
    ("Помогал(а) на студенческой конференции", {}, "Небольшой организационный опыт"),
    ("Опыта волонтёрства пока нет, но очень хочу попробовать", {}, "Опыта волонтёрства нет"),
]
WHY_GIM = [
    "Коллекция ГИМ — одна из главных для истории России, хочу увидеть, как с ней работают изнутри",
    "Пишу курсовую по XVII веку и часто бываю на выставках музея",
    "Друзья рассказали, что в программе интересно",
    "Люблю историю",
]
EXPECTATIONS = [
    "Хочу научиться работать с музейными предметами и помогать в подготовке выставок",
    "Хочу понять, как устроена работа музея, и найти единомышленников",
    "Получить опыт и строчку в резюме",
    "Пока не знаю",
]
HOBBIES = ["Фотография и монтаж коротких видео", "Историческая реконструкция", "Рисую и делаю зины",
           "Настольные игры и квизы", "Бег", "Читаю нон-фикшн"]
QUESTIONS = {
    "Фондовое": "Готовы ли вы приходить по будням днём — фондовая работа идёт в это время?",
    "Организационное": "Как вы обычно действуете, если на мероприятии что-то пошло не по плану?",
    "Проектное": "Какой квест или мастер-класс вы бы предложили для посетителей музея?",
    "Инклюзивное": "Был ли у вас опыт общения с людьми с особыми потребностями?",
    "Медиа": "Покажете пару своих фото или текстов?",
}


def make_answers(rng, level):
    """Ответы анкеты: чем выше level (0–3), тем конкретнее и полнее кандидат отвечает."""
    first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    if first in FEMALE:
        last = last + "а"
    city = rng.choices(["Москва", "Московская область", "Другой город"], [8, 3, 1])[0]
    directions = rng.sample(["Организационное", "Проектное", "Фондовое", "Инклюзивное", "Медиа"], rng.choice([1, 2, 2, 3]))
    pick = lambda pool: pool[min(len(pool) - 1, max(0, 3 - level + rng.choice([-1, 0, 0, 1])))]   # noqa: E731
    experience = EXPERIENCE[min(len(EXPERIENCE) - 1, max(0, (3 - level) * 2 + rng.choice([-1, 0, 1])))]
    answers = {
        "fio": f"{last} {first}", "city": city, "status": rng.choices([["Учусь"], ["Учусь", "Работаю"]], [5, 1])[0],
        "vuz": rng.choice(["МГУ", "РГГУ", "НИУ ВШЭ", "РУДН"]), "faculty": rng.choice(FACULTIES),
        "course": rng.choices(["1 курс бакалавриата", "2 курс", "3 курс", "4 курс", "Магистратура"], [1, 3, 3, 3, 2])[0],
        "study_form": "Очная", "sci_interests": rng.choice(["История XVIII века", "Древняя Русь", "Музейная педагогика"]),
        "experience": experience[0], "hobby": rng.choice(HOBBIES),
        "why_gim": pick(WHY_GIM), "expectations": pick(EXPECTATIONS),
        "hours_month": rng.choices(["Меньше 10", "10–20", "20–30", "30–40"], [1, 4, 3, 2])[0],
        "schedule": rng.choice(["Будни", "Выходные", "Гибко"]),
        "other_programs": rng.choices(["Нет", "Да, в одной", "Да, в нескольких"], [8, 3, 1])[0],
        "directions": directions, "source": rng.choice(["Социальные сети", "Рекомендации друзей", "Сайт Исторического музея"]),
        "followups": [],
    }
    if city == "Московская область":
        answers["commute"] = rng.choices(["До 1 часа", "1–2 часа"], [3, 1])[0]
    return answers, experience


def make_result(rng, rubric, answers, experience, level):
    """Оценка как у настоящей анкеты: правила рубрики + вымышленные «оценки GigaChat» по уровню кандидата."""
    _, categories, phrase = experience
    llm_score = lambda: max(0, min(3, level + rng.choice([-1, 0, 0, 0, 1])))   # noqa: E731
    llm = {"ok": True, "experience_ok": True, "categories": categories,
           "has_any_experience": not phrase.startswith("Опыта волонтёрства нет"),
           "scores": {"why_gim": llm_score(), "expectations": llm_score(), "direction_fit": llm_score(),
                      "form_quality": llm_score()}}
    scores = item_scores(to_candidate(answers), rubric, llm)
    aggregated = aggregate(scores, rubric)
    # Совет по направлению — по опыту, как это делает GigaChat; только из выбранных кандидатом.
    by_experience = {"museum_practice": "Фондовое", "archaeology": "Фондовое", "disability": "Инклюзивное",
                     "children": "Инклюзивное", "own_projects": "Проектное", "volunteering": "Организационное"}
    suggested = [by_experience[code] for code in categories if by_experience[code] in answers["directions"]]
    best = suggested[0] if suggested else answers["directions"][0]
    result = dict(scores=scores, factors=aggregated["factors"], index=aggregated["index"], grade=aggregated["grade"],
                  coverage=aggregated["coverage"], categories=categories, flags=[], vk_summary="", demo=True,
                  summary=f"{answers['course']}, {answers['faculty'].lower()}. {phrase}. "
                          f"Готов(а) уделять {answers['hours_month'].lower()} ч в месяц.",
                  recommended_direction=best,
                  interview_questions=[QUESTIONS[d] for d in answers["directions"]][:2]
                  + ["Что для вас будет признаком, что волонтёрство удалось?"],
                  yellow_flags=yellow_flags(answers))
    result["p_success"] = success_probability(model_features(answers, result), current_model())
    return result


def survey_answers(rng, level):
    """Ответы опроса через четыре месяца: сильные кандидаты чаще довольны и остаются."""
    happy = rng.random() < 0.25 + 0.2 * level
    if happy:
        return {"satisfaction": rng.choice(["4", "5", "5"]), "expectations": rng.choice(["Полностью", "Даже больше"]),
                "continue": rng.choice(["Да", "Скорее да"]), "hours": rng.choice(["5–10", "10–20", "20–30"]),
                "recommend": "Да", "improve": rng.choice(["", "Больше задач в фондах", "Чаще общие встречи волонтёров"])}
    return {"satisfaction": rng.choice(["2", "3"]), "expectations": rng.choice(["Не оправдались", "Частично"]),
            "continue": rng.choice(["Пока не знаю", "Нет"]), "hours": "Меньше 5",
            "recommend": rng.choice(["Скорее нет", "Скорее да"]),
            "improve": rng.choice(["Неудобное расписание смен", "Хотелось бы задач по профилю, а не раздачи буклетов"])}


def days_ago(days):
    return (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat(timespec="seconds")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from bot import survey   # здесь, чтобы не тянуть лишнее при импорте модуля
    rng = random.Random(SEED)
    rubric = load_rubric()
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB) + suffix).unlink(missing_ok=True)
    storage = Storage(DB)

    levels = {}
    for number in range(CANDIDATES):
        level = rng.choices([0, 1, 2, 3], [2, 4, 5, 3])[0]
        answers, experience = make_answers(rng, level)
        app_id = storage.add_application(100 + number, answers)
        storage.save_result(app_id, make_result(rng, rubric, answers, experience, level))
        storage.db.execute("UPDATE applications SET submitted_at = ? WHERE id = ?", (days_ago(rng.randint(1, 20)), app_id))
        levels[app_id] = level

    # Первые 14 — волонтёры прошлого набора: их взяли в команду четыре месяца назад, они прошли опрос.
    # Остальным кураторы только начали выставлять решения.
    for app_id in range(1, CANDIDATES + 1):
        if app_id <= 14:
            storage.set_decision(f"bot:{app_id}", "Взят в команду", "")
            storage.db.execute("UPDATE decisions SET decided_at = ? WHERE app_key = ?", (days_ago(125), f"bot:{app_id}"))
        elif app_id <= 22 and rng.random() < 0.6:
            storage.set_decision(f"bot:{app_id}", rng.choice(["Пригласить", "Пригласить", "Резерв", "Отказ"]), "")
    storage.db.commit()

    for app_id, user_id, _ in storage.applications_due_for_survey(120):
        survey_id = storage.create_survey(app_id, user_id)
        storage.db.execute("UPDATE surveys SET sent_at = ? WHERE id = ?", (days_ago(5), survey_id))
        if app_id == 14:
            continue                                            # ещё не ответил(а)
        answers = survey_answers(rng, levels[app_id])
        storage.finish_survey(survey_id, answers, alert="; ".join(survey.alert_reasons(answers)))
    storage.db.commit()

    report = retrain(storage, force=True, with_history=False)
    print(f"Демобаза: {DB.relative_to(ROOT)} — кандидатов {CANDIDATES}, опросов {report['n_survey']}. "
          f"Модель: {report['note']}")


if __name__ == "__main__":
    main()
