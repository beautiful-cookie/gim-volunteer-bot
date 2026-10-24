"""Анкета кандидата: список вопросов в том порядке, в котором их задаёт бот.

Обязательные вопросы — из анкеты музея 2026 года («Анкета волонтера. Вопросы.docx»).
Помечены «новый» вопросы, которые мы добавили для критериев доступности.
"""
import datetime
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

PRIVACY_URL = "https://shm.ru/politika-konfidentsialnosti/"

INTRO = [
    "Привет! 👋 На связи Государственный исторический музей.\n\n"
    "Мы ищем волонтёров, чтобы вместе делать крутые проекты, организовывать события и открывать историю "
    "с новой стороны.\n\n"
    "Волонтёрство в ГИМ — это закрытые экскурсии, классное комьюнити и отличный старт для карьеры в музее. "
    "Но для нас главное, чтобы тебе самому это было по душе! Поэтому давай сначала коротко расскажем, "
    "как у нас всё устроено.",

    "Чем занимаются наши волонтёры? 🏛️\n\n"
    "У нас пять направлений. Опыт не обязателен — важно лишь то, что тебе по-настоящему интересно:\n\n"
    "🎟️ Организация — встречать гостей, координировать участников олимпиад и помогать на мероприятиях.\n"
    "🧩 Проекты — придумывать свои активности: от детских мастер-классов до игротек.\n"
    "📱 Медиа — писать посты, делать фото и снимать репортажи о жизни музея.\n"
    "🤝 Инклюзия — помогать людям с инвалидностью: встречать у метро, выдавать тактильные модели, "
    "ассистировать экскурсоводам.\n"
    "📚 Фонды — заглянуть за кулисы, работать с археологическими находками и помогать хранителям музея.",

    "Подойдёт ли тебе такой формат? Пара важных моментов перед тем, как перейти к анкете:\n\n"
    "📍 Офлайн в Москве. Мы ждём тебя в самом музее, поэтому важно иметь возможность приезжать к нам лично.\n"
    "🗓️ Наличие времени. Волонтёрство — это регулярные активности. Подумай, получится ли комфортно "
    "совмещать его с учёбой или работой.\n"
    "🔎 Специфика задач. Везде нужен разный подход: где-то много общения, где-то — тихая работа "
    "с древностями или креатив. Выбирай сердцем!\n\n"
    "Если всё сходится и ты готов(а) попробовать — переходи к анкете! Она поможет нам познакомиться "
    "поближе и подобрать для тебя идеальную роль 👇",
]

DIRECTIONS_HELP = (
    "• Организационное — помощь в проведении культурно-массовых мероприятий\n"
    "• Проектное — разработка квестов и мастер-классов\n"
    "• Фондовое — работа с музейными фондами\n"
    "• Инклюзивное — участие в инклюзивных инициативах музея\n"
    "• Медиа — тексты, фото, видео, соцсети музея"
)


@dataclass
class Question:
    key: str                     # под этим ключом ответ хранится в анкете
    section: str                 # раздел для строки «Шаг N из M»
    text: str                    # текст вопроса
    kind: str = "text"           # text — свободный ответ, choice — одна кнопка, multi — несколько кнопок
    options: list = field(default_factory=list)
    other_option: Optional[str] = None      # после этого варианта просим уточнить текстом
    exclusive: list = field(default_factory=list)  # в multi: варианты, которые нельзя сочетать с другими
    check: Optional[Callable[[str], Optional[str]]] = None  # вернёт текст ошибки или None
    ask_if: Optional[Callable[[dict], bool]] = None         # задавать ли вопрос при уже данных ответах
    clarify: Optional[str] = None           # заготовленный переспрос, если ответ слишком общий (один раз)
    llm_followup: bool = False              # после ответа GigaChat может задать своё уточнение
    label: str = ""                         # как пункт называется в сводке ответов

    def applies(self, answers):
        return self.ask_if is None or self.ask_if(answers)


# ---------------------------------------------------------------- проверки ответов

def check_fio(text):
    words = text.split()
    if len(words) < 2 or len(words) > 4:
        return "Напишите, пожалуйста, фамилию, имя и отчество (если есть) — два-три слова."
    if re.search(r"[^А-Яа-яЁёA-Za-z\s\-]", text):
        return "В ФИО должны быть только буквы. Попробуйте ещё раз."
    lowered = [w.lower() for w in words]
    if len(set(lowered)) < len(lowered) or any(len(w) < 2 for w in words):
        return "Похоже, это не ФИО. Напишите, пожалуйста, настоящие фамилию, имя и отчество."
    return None


def check_email(text):
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-zА-Яа-я]{2,}", text.strip()):
        return "Похоже, в адресе ошибка. Пример: ivanova@example.ru"
    return None


def parse_birth_date(text):
    """«05.03.2004» → date или None."""
    match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text.strip())
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def age_on(birth, today=None):
    today = today or datetime.date.today()
    had_birthday = (today.month, today.day) >= (birth.month, birth.day)
    return today.year - birth.year - (0 if had_birthday else 1)


def check_birth_date(text):
    birth = parse_birth_date(text)
    if birth is None:
        return "Напишите дату в формате ДД.ММ.ГГГГ, например 05.03.2004."
    if not 10 <= age_on(birth) <= 100:
        return "Проверьте, пожалуйста, год рождения."
    return None


def check_not_empty(text):
    if len(text.strip()) < 2:
        return "Напишите, пожалуйста, хотя бы пару слов. Если ответа нет — так и напишите: «нет»."
    return None


def too_young(answers):
    """Причина остановить анкету или None. Программа принимает участников с 18 лет."""
    birth = parse_birth_date(answers.get("birth_date", ""))
    if birth and age_on(birth) < 18:
        return ("Спасибо за интерес к программе! К сожалению, волонтёрами ГИМ можно стать с 18 лет. "
                "Будем рады видеть вас в следующих наборах.")
    return None


# ---------------------------------------------------------------- условия

def studies(answers):
    return "Учусь" in answers.get("status", [])


def lives_in_region(answers):
    return answers.get("city") == "Московская область"


def came_from_friends(answers):
    return answers.get("source") == "Рекомендации друзей"


# ---------------------------------------------------------------- вопросы

QUESTIONS = [
    Question("fio", "О себе", "Как вас зовут? Напишите фамилию, имя и отчество.", check=check_fio, label="ФИО"),
    Question("email", "О себе", "Ваша электронная почта:", check=check_email, label="Почта"),
    Question("birth_date", "О себе", "Дата рождения (ДД.ММ.ГГГГ):", check=check_birth_date, label="Дата рождения"),
    Question("city", "О себе", "Где вы живёте?", kind="choice",
             options=["Москва", "Московская область", "Другой город"], label="Город"),  # новый
    Question("commute", "О себе", "Сколько времени занимает дорога до центра Москвы?", kind="choice",
             options=["До 1 часа", "1–2 часа", "Больше 2 часов"], ask_if=lives_in_region, label="Дорога"),  # новый

    Question("status", "Учёба и работа", "Ваш нынешний статус? Можно выбрать несколько вариантов.", kind="multi",
             options=["Учусь", "Работаю", "Не учусь и не работаю"], exclusive=["Не учусь и не работаю"],
             label="Статус"),
    Question("vuz", "Учёба и работа", "В каком вузе вы учитесь?", kind="choice",
             options=["МГУ", "РГГУ", "НИУ ВШЭ", "РУДН", "Другой вуз"], other_option="Другой вуз",
             ask_if=studies, label="Вуз"),
    Question("faculty", "Учёба и работа", "Факультет и направление подготовки:", check=check_not_empty,
             ask_if=studies, label="Факультет"),
    Question("course", "Учёба и работа", "На каком вы курсе?", kind="choice",
             options=["1 курс бакалавриата", "2 курс", "3 курс", "4 курс", "5–6 курс", "Магистратура", "Аспирантура"],
             ask_if=studies, label="Курс"),
    Question("study_form", "Учёба и работа", "Форма обучения:", kind="choice",
             options=["Очная", "Очно-заочная", "Заочная"], ask_if=studies, label="Форма обучения"),  # новый
    Question("education", "Учёба и работа", "Расскажите об образовании: вуз, факультет, год окончания.",
             check=check_not_empty, ask_if=lambda a: not studies(a), label="Образование"),

    Question("sci_interests", "Опыт и интересы", "Сфера ваших научных интересов:", check=check_not_empty,
             label="Научные интересы"),
    Question("experience", "Опыт и интересы",
             "Опыт работы, стажировки, участие в проектах. Если опыта пока нет — так и напишите.",
             check=check_not_empty, llm_followup=True, label="Опыт"),
    Question("languages", "Опыт и интересы",
             "Какими иностранными языками вы владеете на уровне B1 и выше? Если никакими — напишите «нет».",
             check=check_not_empty, label="Языки"),
    Question("hobby", "Опыт и интересы", "Ваши хобби:", check=check_not_empty, llm_followup=True, label="Хобби"),

    Question("why_gim", "Мотивация", "Почему вы выбрали волонтёрскую программу Исторического музея?",
             check=check_not_empty, llm_followup=True, label="Почему ГИМ",
             clarify="Спасибо! Можете чуть конкретнее: что именно привлекает вас в Историческом музее — "
                     "выставки, тема, люди, формат работы?"),
    Question("expectations", "Мотивация", "Чего вы ожидаете от волонтёрства в Историческом музее?",
             check=check_not_empty, llm_followup=True, label="Ожидания",
             clarify="Спасибо! А какой результат через полгода волонтёрства был бы для вас лучшим?"),

    Question("hours_month", "Время", "Сколько часов в месяц вы готовы уделять волонтёрству?", kind="choice",
             options=["Меньше 10", "10–20", "20–30", "30–40", "Больше 40"], label="Часов в месяц"),
    Question("schedule", "Время", "Когда вам удобнее участвовать?", kind="choice",
             options=["Будни", "Выходные", "Гибко"], label="Удобное время"),  # новый
    Question("other_programs", "Время", "Вы сейчас участвуете в других волонтёрских программах?", kind="choice",
             options=["Нет", "Да, в одной", "Да, в нескольких"], label="Другие программы"),  # новый

    Question("directions", "Направления",
             "В каком направлении вы хотели бы участвовать? Можно выбрать несколько.\n\n" + DIRECTIONS_HELP,
             kind="multi",
             options=["Организационное", "Проектное", "Фондовое", "Инклюзивное", "Медиа", "Пока не определился"],
             exclusive=["Пока не определился"], label="Направления"),
    Question("source", "Направления", "Откуда вы узнали о волонтёрской программе?", kind="choice",
             options=["Социальные сети", "Рекомендации друзей", "Сайт Исторического музея", "Другое"],
             other_option="Другое", label="Источник"),
    Question("friend_volunteer", "Направления", "Ваш друг сейчас волонтёр ГИМ?", kind="choice",
             options=["Да, сейчас", "Был(а) раньше", "Нет"], ask_if=came_from_friends,
             label="Друг — волонтёр ГИМ"),  # новый
]

SECTIONS = ["О себе", "Учёба и работа", "Опыт и интересы", "Мотивация", "Время", "Направления", "Уточнения"]

QUESTION_BY_KEY = {q.key: q for q in QUESTIONS}

# Общие ответы, после которых стоит один раз мягко переспросить.
GENERIC_PHRASES = ["люблю историю", "интересно", "новый опыт", "новые знакомства", "не знаю", "хочу попробовать",
                   "получить опыт", "интересный опыт"]


def is_vague(text):
    """Слишком общий ответ: меньше шести слов или почти целиком из общих фраз."""
    words = text.split()
    if len(words) < 6:
        return True
    lowered = text.lower()
    generic_hits = sum(1 for phrase in GENERIC_PHRASES if phrase in lowered)
    return generic_hits >= 1 and len(words) < 12
