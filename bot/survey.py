"""Опрос волонтёров через четыре месяца после того, как их взяли в команду.

Зачем он нужен:
    — куратор вовремя узнаёт, что волонтёр недоволен или собирается уйти (сигнал в беседу кураторов);
    — ответ «продолжу и уделяю время» — та самая метка «успешный волонтёр», на которой дообучается
      модель (bot/retrain.py). Раньше такие метки появлялись раз в год из таблиц часов.

Бот сам пишет волонтёру первым (bot/vk_bot.py), дальше опрос идёт в том же диалоге:
ход опроса лежит в состоянии диалога (state["survey"]), ответы — в таблице surveys.
"""
from dataclasses import dataclass

from .replies import Button, Reply


@dataclass
class SurveyQuestion:
    key: str
    text: str
    options: list = None   # None — открытый вопрос, можно пропустить


QUESTIONS = [
    SurveyQuestion("satisfaction", "Насколько вы довольны волонтёрством в музее?\n"
                                   "1 — совсем не доволен(льна), 5 — очень доволен(льна).",
                   ["1", "2", "3", "4", "5"]),
    # Текст вопроса об ожиданиях собирается из анкеты: см. question_text().
    SurveyQuestion("expectations", "Оправдались ли ваши ожидания от программы?",
                   ["Не оправдались", "Частично", "Полностью", "Даже больше"]),
    SurveyQuestion("continue", "Хотите продолжать волонтёрство в музее в ближайшие месяцы?",
                   ["Да", "Скорее да", "Пока не знаю", "Нет"]),
    SurveyQuestion("hours", "Сколько часов в месяц в среднем у вас уходило на волонтёрство?",
                   ["Меньше 5", "5–10", "10–20", "20–30", "Больше 30"]),
    SurveyQuestion("recommend", "Посоветовали бы вы программу друзьям?",
                   ["Да", "Скорее да", "Скорее нет", "Нет"]),
    SurveyQuestion("improve", "Что бы вы изменили в программе? Пара слов — или нажмите «Пропустить»."),
]
BY_KEY = {q.key: q for q in QUESTIONS}

INTRO = ("Здравствуйте! Вы волонтёр Исторического музея уже около четырёх месяцев — спасибо, что вы с нами.\n\n"
         "Ответьте, пожалуйста, на {n} коротких вопросов, это около двух минут. Ответы увидят только кураторы "
         "программы: они помогут сделать программу удобнее и точнее подбирать новых волонтёров.")


def start(state, survey_id, application_answers):
    """Записать опрос в состояние диалога и вернуть первое сообщение."""
    state["survey"] = {"id": survey_id, "step": "intro", "answers": {},
                       "expectations": short_quote(application_answers.get("expectations", ""))}
    return intro_message()


def intro_message(reminder=False):
    text = INTRO.format(n=len(QUESTIONS))
    if reminder:
        text = "Напоминаем об опросе волонтёров ГИМ. " + text.split("\n\n", 1)[1]
    return Reply(text, [[Button("Пройти опрос", {"survey": "start"}, "primary")],
                        [Button("Не сейчас", {"survey": "later"}), Button("Не хочу", {"survey": "decline"})]])


def short_quote(text, limit=160):
    """Ответ из анкеты для вопроса об ожиданиях: целиком или обрезанный по слову."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def question_text(survey, question):
    number = [q.key for q in QUESTIONS].index(question.key) + 1
    text = question.text
    # Вопрос об ожиданиях — словами самого волонтёра из анкеты, так он точнее, чем абстрактное «ожидания».
    if question.key == "expectations" and survey.get("expectations"):
        text = f"В анкете вы писали, чего ждёте от программы: «{survey['expectations']}»\nОправдались ли ожидания?"
    return f"Вопрос {number} из {len(QUESTIONS)}\n\n{text}"


def ask(survey):
    question = BY_KEY[survey["step"]]
    if question.options is None:
        return Reply(question_text(survey, question), [[Button("Пропустить", {"cmd": "skip"})]])
    buttons = [Button(option, {"answer": option}) for option in question.options]
    if len(buttons) <= 4:
        rows = [[b] for b in buttons]
    else:   # в inline-клавиатуре ВК не больше шести рядов
        rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    return Reply(question_text(survey, question), rows)


def current_message(state, reminder=False):
    """Что повторить волонтёру: приглашение к опросу или вопрос, на котором он остановился."""
    survey = state["survey"]
    if survey["step"] == "intro":
        return intro_message(reminder)
    reply = ask(survey)
    if reminder:
        reply.text = "Вы начали опрос волонтёров ГИМ — давайте закончим.\n\n" + reply.text
    return reply


def handle(storage, state, text, payload):
    """Сообщение волонтёра, пока идёт опрос. Возвращает ответы бота."""
    survey = state["survey"]
    if survey["step"] == "intro":
        choice = payload.get("survey") or {"пройти опрос": "start", "не сейчас": "later",
                                           "не хочу": "decline"}.get(text.lower())
        if choice == "start":
            survey["step"] = QUESTIONS[0].key
            return [ask(survey)]
        if choice == "later":
            return [Reply("Хорошо! Напишите что угодно, когда будет удобно, — и начнём.")]
        if choice == "decline":
            storage.finish_survey(survey["id"], {}, status="declined")
            del state["survey"]
            return [Reply("Понимаем, спасибо! Если захотите поделиться впечатлениями, напишите куратору программы.")]
        return [intro_message()]

    question = BY_KEY[survey["step"]]
    if question.options is None:
        if payload.get("cmd") == "skip":
            value = ""
        elif len(text) < 2:
            return [Reply("Напишите ответ текстом или нажмите «Пропустить».")]
        else:
            value = text
    else:
        value = payload.get("answer")
        if value not in question.options:
            value = next((o for o in question.options if o.lower() == text.lower()), None)
        if value is None:
            return [Reply("Выберите, пожалуйста, вариант на кнопках."), ask(survey)]
    survey["answers"][question.key] = value

    keys = [q.key for q in QUESTIONS]
    position = keys.index(question.key) + 1
    if position < len(keys):
        survey["step"] = keys[position]
        return [ask(survey)]
    return finish(storage, state)


def finish(storage, state):
    survey = state.pop("survey")
    reasons = alert_reasons(survey["answers"])
    storage.finish_survey(survey["id"], survey["answers"], status="completed", alert="; ".join(reasons))
    if reasons:
        return [Reply("Спасибо за честные ответы! Мы передали их куратору программы — он может написать вам, "
                      "чтобы обсудить, что можно изменить.")]
    return [Reply("Спасибо! Ответы сохранены. Рады, что вы в команде музея.")]


def alert_reasons(answers):
    """Почему волонтёр, похоже, недоволен — для сигнала кураторам. Пустой список — всё в порядке."""
    reasons = []
    if answers.get("satisfaction") in ("1", "2"):
        reasons.append(f"доволен(льна) на {answers['satisfaction']} из 5")
    if answers.get("expectations") == "Не оправдались":
        reasons.append("ожидания не оправдались")
    if answers.get("continue") == "Нет":
        reasons.append("не хочет продолжать")
    elif answers.get("continue") == "Пока не знаю":
        reasons.append("не уверен(а), что продолжит")
    if answers.get("recommend") in ("Скорее нет", "Нет"):
        reasons.append("не посоветовал(а) бы друзьям")
    return reasons


def is_success(answers, rule):
    """Метка для дообучения модели: успешный ли волонтёр по опросу (правило — в rubric.yaml, checkin_survey)."""
    if not answers.get("continue") or not answers.get("hours"):
        return None
    return answers["continue"] in rule["continue"] and answers["hours"] in rule["hours"]


def curator_alert(item):
    """Сообщение в беседу кураторов о недовольном волонтёре. item — строка из storage.surveys_to_notify()."""
    application, answers = item["application"], item["answers"]
    lines = [f"⚠ Опрос через 4 месяца: {application.get('fio', '')} (анкета №{item['app_id']}, "
             f"vk.com/id{item['user_id']})",
             "Почему сигнал: " + item["alert"],
             f"Доволен(льна): {answers.get('satisfaction', '—')} из 5 · ожидания: {answers.get('expectations', '—')} · "
             f"продолжит: {answers.get('continue', '—')} · часов в месяц: {answers.get('hours', '—')}"]
    if answers.get("improve"):
        lines.append(f"Что изменить: {answers['improve']}")
    return "\n".join(lines)
