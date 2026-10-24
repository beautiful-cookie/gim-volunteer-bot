"""Проверка бота без ВКонтакте.

    python scripts/simulate_bot.py            # сценарий от начала до конца с проверками, без LLM
    python scripts/simulate_bot.py --llm      # тот же сценарий с GigaChat: уточнения и скоринг (тратит токены)
    python scripts/simulate_bot.py --chat     # ручной диалог в консоли: кнопки выбираются номером

База симулятора — data/sim.sqlite3, рабочая база бота не трогается.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.application import curator_card, score_application  # noqa: E402
from bot.engine import MAX_BUTTONS, Dialog  # noqa: E402
from bot.followups import make_planner  # noqa: E402
from bot.fit_hint import make_fit_hint  # noqa: E402
from bot.inline_questions import make_inline_asker  # noqa: E402
from bot.storage import Storage  # noqa: E402
from scorer.llm import make_provider  # noqa: E402

USER = 1001


class Chat:
    """Обёртка над движком: шлёт сообщения и нажатия, печатает ответы, проверяет клавиатуры."""

    def __init__(self, dialog, quiet=False, auto_inline=False):
        """auto_inline — сам отвечать на уточнения GigaChat: они появляются там, где решит модель."""
        self.dialog, self.quiet, self.auto_inline, self.last = dialog, quiet, auto_inline, []
        self.inline_seen = []

    def send(self, text="", payload=None):
        if not self.quiet:
            print(f"\n>>> {text or payload}")
        self.last = self.dialog.handle(USER, text, payload)
        for reply in self.last:
            buttons = [b for row in reply.buttons for b in row]
            assert len(buttons) <= MAX_BUTTONS, f"больше {MAX_BUTTONS} кнопок"
            assert len(reply.buttons) <= 6, "больше 6 рядов"
            if not self.quiet:
                print(reply.text)
                if buttons:
                    print("   [" + "] [".join(b.label for b in buttons) + "]")
        state = self.dialog.storage.load_state(USER)
        if self.auto_inline and state["step"].startswith("inline:"):
            self.inline_seen.append((state["step"][7:], self.last[0].text))
            return self.send("Да, расскажу подробнее: занималась этим около года, могу показать примеры.")
        return self.last

    def press(self, label):
        """Нажать кнопку последнего сообщения по подписи (без учёта «✓ »)."""
        for reply in self.last:
            for row in reply.buttons:
                for button in row:
                    if button.label.replace("✓ ", "") == label:
                        return self.send(payload=button.payload)
        raise AssertionError(f"нет кнопки «{label}»")

    def says(self, fragment):
        return any(fragment in reply.text for reply in self.last)


def scripted(dialog, storage, provider):
    chat = Chat(dialog, auto_inline=dialog.ask_inline is not None)
    chat.send("Привет")
    assert chat.says("На связи Государственный исторический музей")
    chat.press("Начать анкету")
    chat.press("Даю согласие")
    chat.send("Иванова")                                   # одно слово — ошибка
    assert chat.says("два-три слова")
    chat.send("Мяу мяу мяу")                               # повтор слов — не ФИО
    assert chat.says("это не ФИО")
    chat.send("Иванова Мария Сергеевна")
    chat.send("ivanova@example")                            # ошибка в адресе
    assert chat.says("ошибка")
    chat.send("ivanova@example.ru")
    chat.send("05.03.2004")
    chat.press("Московская область")
    assert chat.says("дорога")
    chat.press("← Назад")                                  # вернулись к городу
    assert chat.says("Где вы живёте")
    chat.press("Москва")
    assert chat.says("статус")
    chat.press("Учусь")
    chat.press("Работаю")
    chat.press("Готово")
    chat.press("РГГУ")
    chat.send("Исторический факультет, музеология")
    chat.press("3 курс")
    chat.press("Очная")
    chat.send("История России XVIII века, музейные коллекции")
    assert chat.says("Опыт работы")
    chat.press("Продолжить позже")                         # пауза на открытом вопросе
    chat.send("Привет, я вернулась")                       # это не ответ на вопрос
    assert chat.says("С возвращением") and chat.says("Опыт работы")
    chat.send("Продолжить позже")                          # кнопка пришла текстом, без payload
    assert chat.says("ответы сохранены")
    chat.send("снова тут")
    assert chat.says("Опыт работы")
    chat.send("Практика в Музее Москвы, вожатая в детском лагере, веду фотоблог")
    chat.send("Английский B2")
    chat.send("Фотография, исторические реконструкции")
    chat.send("Люблю историю")                             # общий ответ — бот переспросит один раз
    if not chat.auto_inline:                               # без LLM — заготовленный переспрос
        assert chat.says("конкретнее")
    if chat.says("конкретнее"):                            # с LLM переспросит GigaChat (ответ уже дан выше)
        chat.send("Регулярно хожу на выставки ГИМ, особенно понравилась выставка о Смутном времени")
    chat.send("Хочу понять, как устроена работа с фондами и подготовка выставки, и поработать в одном из "
              "старейших музеев страны")
    chat.press("20–30")
    chat.press("Выходные")
    chat.press("Нет")
    chat.press("Проектное")
    chat.press("Медиа")
    chat.press("Пока не определился")                      # исключает остальные
    chat.press("Фондовое")                                 # снимает «Пока не определился»
    chat.press("Проектное")
    chat.press("Готово")
    chat.press("Рекомендации друзей")
    assert chat.says("друг сейчас волонтёр")
    chat.press("Да, сейчас")
    assert chat.says("уточняющих вопросов")

    answered = 0
    while chat.says("Уточнения ("):
        answered += 1
        if answered == 2:
            chat.press("Пропустить")
        else:
            chat.send("Да, есть опыт: вела экскурсии для школьников на практике, снимаю на Sony a7")
    assert answered >= (2 if chat.inline_seen else 3), answered   # после уточнений GigaChat блок короче
    assert chat.says("Проверьте, пожалуйста, ответы")

    chat.press("Исправить ответ")
    chat.send("4")                                         # пункт 4 — город
    chat.press("Московская область")
    assert chat.says("дорога")                             # стал нужен вопрос о дороге
    chat.press("До 1 часа")
    assert chat.says("Проверьте, пожалуйста, ответы")
    chat.press("Всё верно, отправить")
    assert chat.says("Анкета отправлена")
    assert chat.says("может подойти направление «"), "нет подсказки по направлению"
    assert chat.says("В фондовом направлении мест немного")   # выбрано «Фондовое» — честное замечание
    assert chat.says("решение о приглашении принимает куратор")

    applications = storage.new_applications()
    assert len(applications) == 1
    app_id, user_id, answers = applications[0]
    assert answers["city"] == "Московская область" and answers["commute"] == "До 1 часа"
    assert answers["directions"] == ["Проектное", "Фондовое"]
    assert answers["why_gim"].startswith("Люблю историю")
    assert answers["experience"].startswith("Практика в Музее Москвы")
    questions = [q for q, _ in answers["followups"]]
    assert len(questions) == len(set(questions)), "повторяющиеся уточняющие вопросы"
    if chat.inline_seen:
        print("\n================ Уточнения GigaChat по ходу анкеты ================")
        for key, question in chat.inline_seen:
            print(f"после «{key}»: {question}")

    result = score_application(answers, provider)
    storage.save_result(app_id, result)
    print("\n================ Карточка для кураторов ================")
    print(curator_card(app_id, user_id, answers, result))
    print("\nСценарий пройден.")


def manual(dialog):
    chat = Chat(dialog)
    chat.send("Привет")
    while True:
        buttons = [b for reply in chat.last for row in reply.buttons for b in row]
        for i, b in enumerate(buttons, 1):
            print(f"  {i}) {b.label}")
        text = input("\nВы (номер кнопки или текст, пусто — выход): ").strip()
        if not text:
            break
        if text.isdigit() and 1 <= int(text) <= len(buttons):
            chat.send(payload=buttons[int(text) - 1].payload)
        else:
            chat.send(text)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--llm", action="store_true", help="подключить GigaChat из .env")
    ap.add_argument("--chat", action="store_true", help="ручной диалог в консоли")
    a = ap.parse_args()

    db = ROOT / "data" / "sim.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    storage = Storage(db)
    provider = make_provider("auto") if a.llm else None
    inline, fast = None, None
    if a.llm:
        fast = make_provider("auto", gigachat_model=os.environ.get("GIGACHAT_FAST_MODEL", "GigaChat-2"))
        inline = make_inline_asker(fast)
    dialog = Dialog(storage, make_planner(provider), inline, make_fit_hint(fast))
    if a.chat:
        manual(dialog)
    else:
        scripted(dialog, storage, provider)


if __name__ == "__main__":
    main()
