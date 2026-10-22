"""Самотест уточнений GigaChat внутри анкеты — без сети, с подставными ответами модели.

    python scripts/selftest_inline.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bot.engine import Dialog  # noqa: E402
from bot.followups import make_planner  # noqa: E402
from bot.inline_questions import make_inline_asker  # noqa: E402
from bot.storage import Storage  # noqa: E402
from scorer.llm import LLMError  # noqa: E402

ANSWER = "Работала вожатой в детском лагере, вела фотокружок для школьников"


class FakeProvider:
    name, model = "fake", "fake-1"

    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, temperature, run=0):
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)


def ask(reply):
    asker = make_inline_asker(FakeProvider([reply]))
    return asker("experience", "Опыт работы", ANSWER, {"experience": ANSWER}, [])


def check_guard():
    good = {"ask": True, "question": "Сколько детей было в вашем отряде и что вы с ними делали?",
            "quote": "Работала вожатой в детском лагере"}
    assert ask(good) == good["question"]
    assert ask({"ask": False}) is None
    assert ask({**good, "question": "С какими аутистами вам комфортнее работать?"}) is None       # нет в программе
    assert ask({**good, "question": "Как у вас со здоровьем для работы с детьми?"}) is None        # чувствительно
    assert ask({**good, "quote": "Мечтаю работать хранителем"}) is None                           # цитаты нет
    assert ask({**good, "question": "Сколько детей было в твоём отряде?"}) is None                # на «ты»
    assert ask({**good, "question": "Что вы делали с детьми? А как долго?"}) == "Что вы делали с детьми?"  # первый из двух
    assert ask({**good, "question": "Расскажите подробнее о работе вожатой."}) is not None        # просьба — можно
    assert ask({**good, "question": "Работа вожатой интересная."}) is None                        # не вопрос
    assert ask(LLMError("нет сети")) is None
    assert ask("не JSON") is None
    # Фото упомянул сам кандидат — вопрос про фото допустим, хотя слово есть и в описании программы.
    assert ask({**good, "question": "Готовы ли вы снимать фото на мероприятиях музея?",
                "quote": "вела фотокружок"}) is not None


def check_dialog():
    db = ROOT / "data" / "selftest_inline.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    question = {"ask": True, "question": "Что именно вы делали в фотокружке?", "quote": "вела фотокружок"}
    provider = FakeProvider([question, {"ask": False}, {"ask": False}, {"ask": False}])
    dialog = Dialog(Storage(db), make_planner(None), make_inline_asker(provider))
    user = 7
    dialog.handle(user, "Привет")
    dialog.handle(user, payload={"cmd": "begin"})
    dialog.handle(user, payload={"answer": "yes"})
    for text in ["Иванова Мария Сергеевна", "ivanova@mail.ru", "05.03.2004"]:
        dialog.handle(user, text)
    dialog.handle(user, payload={"answer": "Москва"})
    dialog.handle(user, payload={"toggle": "Работаю"})
    dialog.handle(user, payload={"cmd": "done"})
    dialog.handle(user, "Окончила РГГУ, исторический факультет, 2022")
    dialog.handle(user, "История XVIII века")
    replies = dialog.handle(user, ANSWER)                         # ответ об опыте → уточнение GigaChat
    assert replies[0].text == question["question"], replies[0].text
    assert dialog.storage.load_state(user)["step"] == "inline:experience"

    replies = dialog.handle(user, payload={"cmd": "back"})        # «Назад» → снова вопрос об опыте
    assert "Опыт работы" in replies[0].text
    assert dialog.storage.load_state(user)["inline"] == []

    provider.replies.insert(0, question)
    dialog.handle(user, ANSWER)
    dialog.handle(user, "Вела съёмку и монтаж с детьми 10–12 лет")  # ответ на уточнение
    state = dialog.storage.load_state(user)
    assert state["inline"][0]["answer"].startswith("Вела съёмку")
    assert state["step"] == "q:languages", state["step"]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    check_guard()
    check_dialog()
    print("Самотест уточнений пройден.")


if __name__ == "__main__":
    main()
