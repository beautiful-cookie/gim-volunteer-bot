"""Самотест опроса через четыре месяца и самообучения модели — без ВКонтакте и без LLM.

Проверяет весь цикл: решение «Взят в команду» → опрос по расписанию → ответы в диалоге → сигнал кураторам
о недовольных → напоминание и закрытие просроченных → переобучение модели на ответах → пересчёт P(успеха).

    python scripts/selftest_survey.py

После теста остаётся демонстрационная база data/selftest_survey.sqlite3 (вымышленные волонтёры).
Дашборд на ней:  GIM_BOT_DB=data/selftest_survey.sqlite3 streamlit run dashboard/app.py
"""
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot import survey  # noqa: E402
from bot.application import current_model, model_features, success_probability  # noqa: E402
from bot.engine import Dialog  # noqa: E402
from bot.followups import make_planner  # noqa: E402
from bot.retrain import retrain  # noqa: E402
from bot.storage import Storage  # noqa: E402
from scorer.score import aggregate, load_rubric  # noqa: E402

DB = ROOT / "data" / "selftest_survey.sqlite3"
NAMES = ["Анна Смирнова", "Илья Кузнецов", "Мария Попова", "Дмитрий Васильев", "Ольга Новикова", "Павел Морозов",
         "Елена Волкова", "Артём Соколов", "Ксения Лебедева", "Никита Козлов", "Дарья Егорова", "Глеб Орлов",
         "Вера Никитина", "Тимур Захаров"]
HAPPY = {"satisfaction": "5", "expectations": "Полностью", "continue": "Да", "hours": "10–20", "recommend": "Да",
         "improve": ""}


def fresh_storage():
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB) + suffix).unlink(missing_ok=True)
    return Storage(DB)


def add_volunteers(storage, rubric):
    """Вымышленные волонтёры с оценёнными анкетами. Музейная практика есть у половины — по ней потом
    и определится успех, чтобы было видно, что модель научилась тому, чего не знал индекс."""
    rng = random.Random(7)
    for number, name in enumerate(NAMES):
        museum = number % 2 == 0
        answers = {"fio": name, "status": ["Учусь"], "course": "3 курс", "study_form": "Очная",
                   "source": "Социальные сети", "directions": ["Проектное"],
                   "expectations": "Хочу понять, как устроена работа музея изнутри, и помогать на мероприятиях"}
        scores = {item["id"]: rng.randint(1, 3) for item in rubric["items"]}
        aggregated = aggregate(scores, rubric)
        result = dict(scores=scores, factors=aggregated["factors"], index=aggregated["index"],
                      grade=aggregated["grade"], categories={"museum_practice": "практика в музее"} if museum else {},
                      flags=[], yellow_flags=[], summary="Тестовый волонтёр.", recommended_direction="Проектное",
                      interview_questions=[])
        result["p_success"] = success_probability(model_features(answers, result), current_model())
        app_id = storage.add_application(1000 + number, answers)
        storage.save_result(app_id, result)
        storage.set_decision(f"bot:{app_id}", "Взят в команду", "")


def pass_survey(dialog, user_id, answers, typed=False):
    """Пройти опрос в диалоге: кнопками или напечатав варианты."""
    replies = dialog.handle(user_id, payload={"survey": "start"})
    for question in survey.QUESTIONS:
        assert replies[-1].text.startswith(f"Вопрос {survey.QUESTIONS.index(question) + 1} из"), replies[-1].text
        value = answers[question.key]
        if question.options is None:
            replies = dialog.handle(user_id, value) if value else dialog.handle(user_id, payload={"cmd": "skip"})
        elif typed:
            replies = dialog.handle(user_id, value.lower())
        else:
            replies = dialog.handle(user_id, payload={"answer": value})
    return replies


def check_schedule(storage):
    assert storage.applications_due_for_survey(120) == [], "опрос ушёл раньше четырёх месяцев"
    assert len(storage.applications_due_for_survey(0)) == len(NAMES)
    # Решение приняли 130 дней назад, а комментарий поправили сегодня — срок опроса не сдвигается.
    storage.db.execute("UPDATE decisions SET decided_at = '2026-01-01T10:00:00' WHERE app_key = 'bot:1'")
    storage.set_decision("bot:1", "Взят в команду", "Хорошо показал себя на Ночи музеев")
    due = storage.applications_due_for_survey(120)
    assert [app_id for app_id, _, _ in due] == [1], due
    # А смена решения сдвигает: «Резерв» → снова «Взят в команду» — отсчёт заново.
    storage.set_decision("bot:2", "Резерв", "")
    storage.set_decision("bot:2", "Взят в команду", "")
    assert 2 not in [app_id for app_id, _, _ in storage.applications_due_for_survey(120)]


def check_dialog(storage, dialog):
    due = {app_id: (user_id, answers) for app_id, user_id, answers in storage.applications_due_for_survey(0)}

    # 1. Недовольный волонтёр отвечает кнопками → сигнал кураторам.
    user, answers = due[1]
    intro = dialog.start_survey(user, storage.create_survey(1, user), answers)
    assert "четырёх месяцев" in intro.text and intro.buttons[0][0].label == "Пройти опрос"
    replies = dialog.handle(user, "Привет")                       # не нажал кнопку — приглашение ещё раз
    assert replies[0].buttons[0][0].label == "Пройти опрос"
    replies = dialog.handle(user, payload={"survey": "start"})
    assert replies[0].text.startswith("Вопрос 1 из 6")
    replies = dialog.handle(user, "семь")                         # не вариант — переспросить
    assert "вариант на кнопках" in replies[0].text
    dialog.handle(user, payload={"answer": "2"})
    state = storage.load_state(user)
    assert "как устроена работа музея изнутри" in survey.current_message(state).text   # ожидания — словами анкеты
    unhappy = {"satisfaction": "2", "expectations": "Не оправдались", "continue": "Пока не знаю", "hours": "Меньше 5",
               "recommend": "Скорее нет", "improve": "Больше задач в фондах, меньше раздачи буклетов"}
    for key in ("expectations", "continue", "hours", "recommend"):
        dialog.handle(user, payload={"answer": unhappy[key]})
    replies = dialog.handle(user, unhappy["improve"])
    assert "передали их куратору" in replies[0].text
    assert "survey" not in storage.load_state(user)
    assert "уже отправлена" in dialog.handle(user, "Привет")[0].text   # после опроса — обычный диалог

    alerts = storage.surveys_to_notify()
    assert len(alerts) == 1, alerts
    card = survey.curator_alert(alerts[0])
    assert NAMES[0] in card and "ожидания не оправдались" in card and "не уверен(а)" in card, card
    assert "Больше задач в фондах" in card
    storage.mark_survey_notified(alerts[0]["id"])
    assert storage.surveys_to_notify() == []

    # 2. Довольный волонтёр печатает ответы вместо кнопок → без сигнала.
    user, answers = due[2]
    dialog.start_survey(user, storage.create_survey(2, user), answers)
    replies = pass_survey(dialog, user, HAPPY, typed=True)
    assert "Рады, что вы в команде" in replies[0].text
    assert storage.surveys_to_notify() == []

    # 3. «Не сейчас», потом «Не хочу».
    user, answers = due[3]
    dialog.start_survey(user, storage.create_survey(3, user), answers)
    assert "когда будет удобно" in dialog.handle(user, payload={"survey": "later"})[0].text
    assert "Понимаем" in dialog.handle(user, payload={"survey": "decline"})[0].text
    assert {s["app_id"]: s["status"] for s in storage.all_surveys()}[3] == "declined"

    # 4. Молчит: через три дня напоминание, через две недели опрос закрывается.
    user, answers = due[4]
    survey_id = storage.create_survey(4, user)
    dialog.start_survey(user, survey_id, answers)
    storage.db.execute("UPDATE surveys SET sent_at = '2026-01-01T10:00:00' WHERE id = ?", (survey_id,))
    assert storage.surveys_to_remind(3) == [(survey_id, user)]
    assert dialog.survey_reminder(user).text.startswith("Напоминаем об опросе")
    storage.mark_survey_reminded(survey_id)
    assert storage.surveys_to_remind(3) == []
    assert storage.expire_surveys(14) == [user]
    dialog.close_survey(user)
    assert dialog.survey_reminder(user) is None and "survey" not in storage.load_state(user)


def check_retrain(storage, dialog):
    """Остальные волонтёры проходят опрос; успех — у тех, у кого была музейная практика."""
    assert retrain(storage, with_history=False) is None      # пока два ответа — меньше min_new_labels
    due = {app_id: (user_id, answers) for app_id, user_id, answers in storage.applications_due_for_survey(0)}
    for app_id, (user, answers) in due.items():
        museum = (app_id - 1) % 2 == 0
        outcome = HAPPY if museum else {**HAPPY, "satisfaction": "3", "continue": "Нет", "hours": "Меньше 5",
                                        "recommend": "Скорее да", "improve": "Неудобное расписание"}
        dialog.start_survey(user, storage.create_survey(app_id, user), answers)
        pass_survey(dialog, user, outcome)

    before = {a["id"]: a["result"]["p_success"] for a in storage.all_applications()}
    report = retrain(storage, with_history=False)
    assert report is not None and report["n_survey"] == len(NAMES) - 2, report   # минус отказ и молчание
    assert report["accepted"], report
    assert report["auc_new"] > report["auc_old"], report     # новая модель учла музейную практику
    assert storage.active_model() is not None
    after = {a["id"]: a["result"]["p_success"] for a in storage.all_applications()}
    assert after != before and report["updated"] == len(NAMES)
    assert retrain(storage, with_history=False) is None      # новых меток нет — не переобучаем
    return report


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    rubric = load_rubric()
    storage = fresh_storage()
    dialog = Dialog(storage, make_planner(None))
    add_volunteers(storage, rubric)
    check_schedule(storage)
    check_dialog(storage, dialog)
    report = check_retrain(storage, dialog)
    print(f"Модель: {report['note']}; P(успеха) пересчитана у {report['updated']} анкет.")
    print(f"Самотест опроса пройден. Демобаза для дашборда: {DB.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
