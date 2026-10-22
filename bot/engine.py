"""Диалоговый движок: ведёт кандидата по анкете.

Движок ничего не знает о ВКонтакте. Он получает текст сообщения или нажатую кнопку
и возвращает список ответов бота с кнопками. Поэтому весь сценарий можно проверить
в консольном симуляторе (scripts/simulate_bot.py), а адаптер ВК остаётся тонким (bot/vk_bot.py).

Состояние диалога — обычный словарь, который хранится в SQLite между сообщениями:
    step       — где сейчас кандидат: "intro", "consent", "q:<ключ>", "other:<ключ>", "clarify:<ключ>",
                 "inline:<ключ>", "followup", "summary", "edit", "done", "stopped"
    answers    — ответы анкеты
    history    — ключи вопросов, на которые уже ответили (для кнопки «Назад»)
    picked     — отмеченные варианты в вопросе с несколькими ответами
    inline     — уточнения GigaChat сразу после открытых вопросов: [{key, question, answer}]
    followups  — уточняющие вопросы в конце анкеты и ответы на них
"""
from dataclasses import dataclass, field

from .questionnaire import INTRO, PRIVACY_URL, QUESTION_BY_KEY, QUESTIONS, SECTIONS, is_vague, too_young

MAX_BUTTONS = 10  # ограничение ВК для inline-клавиатуры
MAX_INLINE = 3    # не больше трёх уточнений GigaChat по ходу анкеты, чтобы не утомлять кандидата


@dataclass
class Button:
    label: str
    payload: dict
    color: str = "secondary"   # primary, secondary, positive, negative


@dataclass
class Reply:
    text: str
    buttons: list = field(default_factory=list)   # список рядов, ряд — список кнопок


BACK = Button("← Назад", {"cmd": "back"})
LATER = Button("Продолжить позже", {"cmd": "later"})

# Подписи служебных кнопок: если кандидат напечатал их сам, это команда, а не ответ.
TEXT_COMMANDS = {"назад": "back", "продолжить позже": "later", "пропустить": "skip", "готово": "done",
                 "всё верно, отправить": "submit", "все верно, отправить": "submit", "исправить ответ": "edit",
                 "начать анкету": "begin"}


def new_state():
    return {"step": "intro", "answers": {}, "history": [], "picked": [], "inline": [],
            "followups": [], "followup_index": 0}


class Dialog:
    def __init__(self, storage, plan_followups, ask_inline=None):
        """storage — bot.storage.Storage;
        plan_followups(answers) → список уточняющих вопросов для конца анкеты;
        ask_inline(key, question, answer, answers, asked) → уточнение GigaChat или None (bot.inline_questions).
        """
        self.storage = storage
        self.plan_followups = plan_followups
        self.ask_inline = ask_inline

    # ------------------------------------------------------------ вход

    def handle(self, user_id, text="", payload=None):
        payload = payload or {}
        text = (text or "").strip()
        state = self.storage.load_state(user_id)
        command = payload.get("cmd") or payload.get("command")   # «command: start» шлёт кнопка «Начать» в ВК
        if not command:
            # Иногда ВК присылает нажатие кнопки без payload — тогда узнаём команду по тексту.
            command = TEXT_COMMANDS.get(text.lower().replace("←", "").strip())
            if command:
                payload = {"cmd": command}

        wants_restart = text.lower() in ("начать заново", "/start")
        if state is None or wants_restart:
            state = new_state()
            replies = self.show_intro()
        elif command == "start":
            replies = self.repeat_current(state) or self.show_intro()
        elif command == "later":
            state["paused"] = True
            replies = [Reply("Хорошо, ответы сохранены. Напишите что угодно, когда будете готовы продолжить.")]
        elif state.get("paused"):
            # Первое сообщение после паузы — это «я вернулся», а не ответ на вопрос.
            state["paused"] = False
            replies = [Reply("С возвращением! Продолжаем с того же места."), *self.repeat_current(state)]
        elif command == "back":
            replies = self.go_back(state)
        else:
            replies = self.answer(state, text, payload)

        state["user_id"] = user_id
        self.storage.save_state(user_id, state)
        return replies

    def answer(self, state, text, payload):
        step = state["step"]
        if step == "intro":
            if payload.get("cmd") == "begin" or text.lower() in ("начать", "начать анкету"):
                state["step"] = "consent"
                return [self.consent_message()]
            return self.show_intro()
        if step == "consent":
            return self.on_consent(state, payload, text)
        if step.startswith("q:"):
            return self.on_question(state, QUESTION_BY_KEY[step[2:]], text, payload)
        if step.startswith("other:"):
            return self.on_other_text(state, QUESTION_BY_KEY[step[6:]], text)
        if step.startswith("clarify:"):
            return self.on_clarification(state, step[8:], text)
        if step.startswith("inline:"):
            return self.on_inline_answer(state, step[7:], text, payload)
        if step == "followup":
            return self.on_followup(state, text, payload)
        if step == "summary":
            return self.on_summary(state, payload)
        if step == "edit":
            return self.on_edit_choice(state, text)
        if step == "done":
            return [Reply("Ваша анкета уже отправлена — спасибо! Куратор свяжется с вами после рассмотрения.")]
        return [Reply("Спасибо за интерес к программе! Если захотите начать заново, напишите «Начать заново».")]

    # ------------------------------------------------------------ знакомство и согласие

    def show_intro(self):
        replies = [Reply(text) for text in INTRO]
        replies[-1].buttons = [[Button("Начать анкету", {"cmd": "begin"}, "primary")]]
        return replies

    def consent_message(self):
        text = ("Для участия нужно согласие на обработку персональных данных. "
                f"Политика конфиденциальности музея: {PRIVACY_URL}\n\n"
                "Мы также посмотрим открытые данные вашей страницы ВКонтакте: город, подписки на музейные "
                "сообщества и общих друзей с волонтёрами программы.")
        return Reply(text, [[Button("Даю согласие", {"answer": "yes"}, "positive"),
                             Button("Не согласен(на)", {"answer": "no"}, "negative")]])

    def on_consent(self, state, payload, text):
        choice = payload.get("answer") or ("yes" if text.lower().startswith("даю") else "")
        if choice == "yes":
            state["answers"]["consent"] = True
            return self.go_to_next(state, after=None)
        if choice == "no":
            state["step"] = "stopped"
            return [Reply("Понимаем. Без согласия мы не можем принять анкету. "
                          "Если передумаете, напишите «Начать заново».")]
        return [self.consent_message()]

    # ------------------------------------------------------------ вопросы анкеты

    def ask(self, state, question):
        state["step"] = "q:" + question.key
        number = SECTIONS.index(question.section) + 1
        header = f"Шаг {number} из {len(SECTIONS)} · {question.section}\n\n"

        option_buttons = []
        if question.kind == "choice":
            for option in question.options:
                option_buttons.append(Button(option, {"answer": option}))
        elif question.kind == "multi":
            for option in question.options:
                mark = "✓ " if option in state["picked"] else ""
                option_buttons.append(Button(mark + option, {"toggle": option}))

        rows = pack_rows(option_buttons)
        if question.kind == "multi":
            rows.append([Button("Готово", {"cmd": "done"}, "primary")])
        rows.append([BACK, LATER] if state["history"] else [LATER])
        return Reply(header + question.text, rows)

    def on_question(self, state, question, text, payload):
        if question.kind == "text":
            error = question.check(text) if question.check else None
            if error:
                return [Reply(error)]
            return self.save_answer(state, question, text)

        if question.kind == "choice":
            option = payload.get("answer") or match_option(text, question.options)
            if option is None:
                return [Reply("Выберите, пожалуйста, один из вариантов на кнопках."), self.ask(state, question)]
            if option == question.other_option:
                state["answers"][question.key] = option
                state["step"] = "other:" + question.key
                return [Reply("Уточните, пожалуйста, текстом:")]
            return self.save_answer(state, question, option)

        # Несколько вариантов: кнопки работают как переключатели, «Готово» сохраняет выбор.
        option = payload.get("toggle") or match_option(text, question.options)
        if option:
            self.toggle(state, question, option)
            return [self.ask(state, question)]
        if payload.get("cmd") == "done" or text.lower() == "готово":
            if not state["picked"]:
                return [Reply("Отметьте хотя бы один вариант."), self.ask(state, question)]
            picked = [o for o in question.options if o in state["picked"]]
            state["picked"] = []
            return self.save_answer(state, question, picked)
        return [Reply("Нажимайте на варианты, чтобы отметить их, а потом — «Готово»."), self.ask(state, question)]

    def toggle(self, state, question, option):
        picked = state["picked"]
        if option in picked:
            picked.remove(option)
        elif option in question.exclusive:
            picked[:] = [option]
        else:
            picked[:] = [o for o in picked if o not in question.exclusive] + [option]

    def on_other_text(self, state, question, text):
        if len(text) < 2:
            return [Reply("Уточните, пожалуйста, текстом:")]
        return self.save_answer(state, question, f"{question.other_option}: {text}")

    def save_answer(self, state, question, value):
        state["answers"][question.key] = value
        if question.key not in state["history"]:
            state["history"].append(question.key)

        stop_reason = too_young(state["answers"])
        if stop_reason:
            state["step"] = "stopped"
            return [Reply(stop_reason)]

        # Сначала пробуем уточнение от GigaChat: оно привязано к тому, что кандидат написал.
        inline = self.inline_question(state, question, value)
        if inline:
            return [inline]

        # Если GigaChat промолчал или недоступна — один раз переспрашиваем слишком общий ответ заготовкой.
        clarified = state["answers"].setdefault("_clarified", [])
        if question.clarify and question.key not in clarified and is_vague(value):
            clarified.append(question.key)
            state["step"] = "clarify:" + question.key
            return [Reply(question.clarify)]
        return self.go_to_next(state, after=question.key)

    def inline_question(self, state, question, value):
        """Уточнение GigaChat сразу после ответа или None (нет LLM, исчерпан лимит, вопрос не прошёл проверку)."""
        inline = state.setdefault("inline", [])
        if self.ask_inline is None or not question.llm_followup or len(inline) >= MAX_INLINE:
            return None
        if any(item["key"] == question.key for item in inline):
            return None
        asked = [item["question"] for item in inline]
        text = self.ask_inline(question.key, question.text, value, public_answers(state), asked)
        if not text:
            return None
        inline.append({"key": question.key, "question": text, "answer": None})
        state["answers"].setdefault("_clarified", []).append(question.key)   # заготовку уже не задаём
        state["step"] = "inline:" + question.key
        return self.inline_message(text)

    def inline_message(self, text):
        return Reply(text, [[Button("Пропустить", {"cmd": "skip"})], [BACK, LATER]])

    def on_inline_answer(self, state, key, text, payload):
        current = next(item for item in state["inline"] if item["key"] == key)
        if payload.get("cmd") == "skip":
            current["answer"] = ""
        elif len(text) < 2:
            return [Reply("Напишите ответ текстом или нажмите «Пропустить».")]
        else:
            current["answer"] = text
        return self.go_to_next(state, after=key)

    def on_clarification(self, state, key, text):
        if text:
            first = state["answers"][key].rstrip()
            separator = " " if first.endswith((".", "!", "?")) else ". "
            state["answers"][key] = first + separator + text
        return self.go_to_next(state, after=key)

    def go_to_next(self, state, after):
        """Следующий вопрос, который ещё не отвечен и подходит по условиям. Нет такого — к уточнениям."""
        start = 0 if after is None else [q.key for q in QUESTIONS].index(after) + 1
        for question in QUESTIONS[start:]:
            if question.applies(state["answers"]) and question.key not in state["answers"]:
                return [self.ask(state, question)]
        # При исправлении ответа вопросы выше могли стать нужными (например, сменили город на область).
        for question in QUESTIONS:
            if question.applies(state["answers"]) and question.key not in state["answers"]:
                return [self.ask(state, question)]
        return self.start_followups(state)

    def go_back(self, state):
        if not state["history"] or not state["step"].startswith(("q:", "other:", "clarify:", "inline:")):
            return [Reply("Назад вернуться нельзя."), *self.repeat_current(state)]
        previous_key = state["history"].pop()
        state["answers"].pop(previous_key, None)
        forget_inline(state, previous_key)
        state["picked"] = []
        return [self.ask(state, QUESTION_BY_KEY[previous_key])]

    def repeat_current(self, state):
        """Повторить то, на что кандидат сейчас должен ответить (после паузы, «Начать», неверного «Назад»)."""
        step = state["step"]
        if step == "consent":
            return [self.consent_message()]
        if step.startswith("q:"):
            return [self.ask(state, QUESTION_BY_KEY[step[2:]])]
        if step.startswith("other:"):
            return [Reply("Уточните, пожалуйста, текстом:")]
        if step.startswith("clarify:"):
            return [Reply(QUESTION_BY_KEY[step[8:]].clarify)]
        if step.startswith("inline:"):
            current = next(item for item in state["inline"] if item["key"] == step[7:])
            return [self.inline_message(current["question"])]
        if step == "followup":
            return [self.followup_message(state)]
        if step == "summary":
            return [self.summary_message(state)]
        if step == "edit":
            return [Reply("Напишите номер пункта, который хотите исправить.")]
        return []

    # ------------------------------------------------------------ уточняющие вопросы

    def start_followups(self, state):
        if not state["followups"]:
            questions = self.plan_followups(public_answers(state))
            state["followups"] = [{"question": q, "answer": None} for q in questions]
            state["followup_index"] = 0
        if state["followup_index"] >= len(state["followups"]):
            return self.show_summary(state)
        state["step"] = "followup"
        intro = Reply("Почти готово! Несколько уточняющих вопросов по вашим ответам — они помогут куратору "
                      "лучше понять ваш опыт.") if state["followup_index"] == 0 else None
        return [r for r in (intro, self.followup_message(state)) if r]

    def followup_message(self, state):
        index = state["followup_index"]
        total = len(state["followups"])
        text = (f"Шаг {len(SECTIONS)} из {len(SECTIONS)} · Уточнения ({index + 1}/{total})\n\n"
                + state["followups"][index]["question"])
        return Reply(text, [[Button("Пропустить", {"cmd": "skip"})], [LATER]])

    def on_followup(self, state, text, payload):
        current = state["followups"][state["followup_index"]]
        if payload.get("cmd") == "skip":
            current["answer"] = ""
        elif len(text) < 2:
            return [Reply("Напишите ответ текстом или нажмите «Пропустить».")]
        else:
            current["answer"] = text
        state["followup_index"] += 1
        return self.start_followups(state)

    # ------------------------------------------------------------ сводка, исправление, отправка

    def show_summary(self, state):
        state["step"] = "summary"
        return [self.summary_message(state)]

    def summary_message(self, state):
        lines = ["Проверьте, пожалуйста, ответы:\n"]
        for number, (question, value) in enumerate(answered_questions(state), 1):
            lines.append(f"{number}. {question.label}: {format_value(value)}")
        return Reply("\n".join(lines), [[Button("Всё верно, отправить", {"cmd": "submit"}, "positive")],
                                        [Button("Исправить ответ", {"cmd": "edit"})]])

    def on_summary(self, state, payload):
        if payload.get("cmd") == "submit":
            self.storage.add_application(state["user_id"], public_answers(state))
            state["step"] = "done"
            return [Reply("Спасибо! Анкета отправлена. Куратор программы рассмотрит её и свяжется с вами "
                          "во ВКонтакте. Обычно это занимает до двух недель.")]
        if payload.get("cmd") == "edit":
            state["step"] = "edit"
            return [Reply("Напишите номер пункта, который хотите исправить.")]
        return [self.summary_message(state)]

    def on_edit_choice(self, state, text):
        answered = answered_questions(state)
        if not text.isdigit() or not 1 <= int(text) <= len(answered):
            return [Reply(f"Напишите число от 1 до {len(answered)}.")]
        question = answered[int(text) - 1][0]
        state["answers"].pop(question.key, None)
        forget_inline(state, question.key)
        return [self.ask(state, question)]


# ---------------------------------------------------------------- вспомогательные функции

def match_option(text, options):
    """Кандидат может не нажать кнопку, а напечатать вариант — сравниваем без учёта регистра."""
    lowered = text.lower().strip()
    for option in options:
        if lowered == option.lower():
            return option
    return None


def pack_rows(buttons):
    """До четырёх вариантов — по одному в ряд, больше — по два: в inline-клавиатуре ВК не больше 6 рядов."""
    if len(buttons) <= 4:
        return [[b] for b in buttons]
    rows = []
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i:i + 2])
    return rows


def answered_questions(state):
    """Вопросы, которые подходят по условиям и на которые есть ответ, в порядке анкеты."""
    result = []
    for question in QUESTIONS:
        if question.applies(state["answers"]) and question.key in state["answers"]:
            result.append((question, state["answers"][question.key]))
    return result


def forget_inline(state, key):
    """Ответ на вопрос стёрт («Назад» или исправление) — уточнение к нему можно задать заново."""
    state["inline"] = [item for item in state.get("inline", []) if item["key"] != key]
    clarified = state["answers"].get("_clarified", [])
    if key in clarified:
        clarified.remove(key)


def public_answers(state):
    """Ответы без служебных полей и без ответов на вопросы, ставшие неактуальными после исправлений.

    В followups сначала идут уточнения GigaChat по ходу анкеты (на которые ответили), потом вопросы из конца анкеты.
    """
    answers = {q.key: value for q, value in answered_questions(state)}
    inline = [(item["question"], item["answer"]) for item in state.get("inline", [])
              if item["answer"] is not None and item["key"] in answers]
    answers["followups"] = inline + [(f["question"], f["answer"]) for f in state.get("followups", [])]
    return answers


def format_value(value):
    if isinstance(value, list):
        return ", ".join(value)
    return str(value)
