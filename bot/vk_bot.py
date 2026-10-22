"""Бот сообщества ВКонтакте на vkbottle (Bots Long Poll — публичный адрес сервера не нужен).

Запуск из корня проекта:
    python -m bot.vk_bot

Нужно в .env:
    VK_GROUP_TOKEN       — ключ доступа сообщества (Управление → Работа с API), права: сообщения сообщества
    VK_CURATOR_PEER_ID   — peer_id беседы кураторов (2000000000 + номер беседы), сюда приходят карточки анкет
    SURVEY_AFTER_DAYS    — необязательно: через сколько дней после «Взят в команду» прислать опрос
                           (по умолчанию из rubric.yaml, 120; 0 — сразу, для показа)
    SURVEY_CHECK_EVERY   — необязательно: как часто проверять опросы, в секундах (по умолчанию 600)
В настройках сообщества включите «Сообщения» и «Возможности ботов».

Кроме диалога, бот в фоне: оценивает новые анкеты, напоминает о брошенных, рассылает опрос через
четыре месяца, сообщает кураторам о недовольных волонтёрах и дообучает модель на ответах опроса.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import certifi  # noqa: E402

# Сертификат api.vk.ru выпущен центром HARICA, которого может не быть в хранилище Windows.
# Берём корневые сертификаты из пакета certifi (так же делает httpx для GigaChat).
# Строка должна стоять до импорта vkbottle: aiohttp создаёт SSL-контекст при импорте.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from vkbottle import API, Keyboard, KeyboardButtonColor, Text  # noqa: E402
from vkbottle.bot import Bot, Message  # noqa: E402

from bot import survey  # noqa: E402
from bot.application import current_model, curator_card, score_application  # noqa: E402
from bot.engine import Dialog  # noqa: E402
from bot.followups import make_planner  # noqa: E402
from bot.fit_hint import make_fit_hint  # noqa: E402
from bot.inline_questions import make_inline_asker  # noqa: E402
from bot.retrain import retrain  # noqa: E402
from bot.vk_profile import analyze_profile  # noqa: E402
from scorer.score import load_rubric  # noqa: E402
from bot.storage import Storage  # noqa: E402
from scorer.llm import LLMError, load_env, make_provider  # noqa: E402

COLORS = {"primary": KeyboardButtonColor.PRIMARY, "secondary": KeyboardButtonColor.SECONDARY,
          "positive": KeyboardButtonColor.POSITIVE, "negative": KeyboardButtonColor.NEGATIVE}

CHECK_NEW_APPLICATIONS_EVERY = 30      # секунд
CHECK_REMINDERS_EVERY = 30 * 60        # секунд
CHECK_SURVEYS_EVERY = 10 * 60          # секунд
CHECK_RETRAIN_EVERY = 6 * 60 * 60      # секунд


def to_keyboard(rows):
    """Ряды кнопок движка → inline-клавиатура ВК (JSON-строка) или None."""
    if not rows:
        return None
    keyboard = Keyboard(inline=True)
    for i, row in enumerate(rows):
        if i > 0:
            keyboard.row()
        for button in row:
            # ВК ждёт payload строкой JSON не длиннее 255 символов; подпись кнопки — до 40 символов.
            payload = json.dumps(button.payload, ensure_ascii=False)
            keyboard.add(Text(button.label[:40], payload=payload), color=COLORS[button.color])
    return keyboard.get_json()


def main():
    load_env()
    token = os.environ.get("VK_GROUP_TOKEN")
    if not token:
        sys.exit("Не задан VK_GROUP_TOKEN в .env")
    curator_peer = int(os.environ.get("VK_CURATOR_PEER_ID") or 0)

    try:
        provider = make_provider("auto")
        # Для уточнений прямо в диалоге берём быструю модель: кандидат ждёт ответа в чате.
        fast_provider = make_provider("auto", gigachat_model=os.environ.get("GIGACHAT_FAST_MODEL", "GigaChat-2"))
    except LLMError as error:
        print(f"LLM не подключена ({error}) — бот работает на правилах.")
        provider = fast_provider = None

    storage = Storage(ROOT / "data" / "bot.sqlite3")
    dialog = Dialog(storage, make_planner(provider), make_inline_asker(fast_provider), make_fit_hint(fast_provider))
    bot = Bot(token=token)

    @bot.on.private_message()
    async def on_message(message: Message):
        payload = message.get_payload_json() or {}
        # Пока GigaChat думает над уточнением, кандидат видит «печатает…».
        try:
            await bot.api.messages.set_activity(peer_id=message.peer_id, type="typing")
        except Exception:
            pass
        # Движок может ждать ответа LLM (уточняющие вопросы), поэтому вызываем его в отдельном потоке.
        replies = await asyncio.to_thread(dialog.handle, message.from_id, message.text, payload)
        for reply in replies:
            await message.answer(reply.text, keyboard=to_keyboard(reply.buttons))

    @bot.on.chat_message()
    async def on_chat_message(message: Message):
        """В беседе бот отвечает только на «/id» — так куратор узнаёт peer_id беседы для VK_CURATOR_PEER_ID."""
        if (message.text or "").strip().lower().endswith("/id"):
            await message.answer(f"Номер этой беседы для настройки бота: VK_CURATOR_PEER_ID={message.peer_id}")

    # Сервисный ключ приложения ВК открывает подписки и друзей кандидата. Без него — только профиль и музеи.
    service_token = os.environ.get("VK_SERVICE_TOKEN")
    service_api = API(service_token) if service_token else None
    vk_config = load_rubric()["vk_analysis"]

    async def process_new_applications():
        """Каждые полминуты берём отправленные анкеты, смотрим страницу ВК, считаем баллы и шлём карточку кураторам."""
        while True:
            for app_id, user_id, answers in storage.new_applications():
                try:
                    profile = await analyze_profile(bot.api, user_id, vk_config, service_api)
                    result = await asyncio.to_thread(score_application, answers, provider, 3, profile,
                                                     current_model(storage))
                    storage.save_result(app_id, result)
                    print(f"Анкета {app_id}: оценка {result['grade']}, индекс {result['index']}")
                    if curator_peer:
                        await bot.api.messages.send(peer_id=curator_peer, random_id=0,
                                                    message=curator_card(app_id, user_id, answers, result))
                        print(f"Анкета {app_id}: карточка отправлена кураторам")
                except Exception as error:  # анкета не должна потеряться из-за сбоя скоринга
                    storage.save_result(app_id, {"error": str(error)}, status="error")
                    print(f"Анкета {app_id}: ошибка обработки — {error}")
            await asyncio.sleep(CHECK_NEW_APPLICATIONS_EVERY)

    async def send_reminders():
        """Одно напоминание тем, кто бросил анкету больше суток назад."""
        while True:
            for user_id in storage.sessions_to_remind(hours=24):
                await bot.api.messages.send(peer_id=user_id, random_id=0,
                                            message="Вы начали заполнять анкету волонтёра ГИМ. Продолжим? "
                                                    "Напишите что угодно — бот вернёт вас к нужному вопросу.")
                storage.mark_reminded(user_id)
            await asyncio.sleep(CHECK_REMINDERS_EVERY)

    survey_config = load_rubric()["checkin_survey"]
    survey_after_days = float(os.environ.get("SURVEY_AFTER_DAYS") or survey_config["after_days"])
    check_surveys_every = int(os.environ.get("SURVEY_CHECK_EVERY") or CHECK_SURVEYS_EVERY)

    async def send(peer_id, reply):
        await bot.api.messages.send(peer_id=peer_id, random_id=0, message=reply.text,
                                    keyboard=to_keyboard(reply.buttons))

    async def run_surveys():
        """Опрос через четыре месяца: разослать, напомнить, закрыть просроченные, сообщить кураторам о недовольных."""
        while True:
            try:
                for app_id, user_id, answers in storage.applications_due_for_survey(survey_after_days):
                    # У человека может быть несколько анкет (подавал повторно) — не больше одного опроса за раз.
                    if dialog.survey_reminder(user_id):
                        continue
                    survey_id = storage.create_survey(app_id, user_id)
                    try:
                        await send(user_id, dialog.start_survey(user_id, survey_id, answers))
                        print(f"Анкета {app_id}: отправлен опрос через 4 месяца")
                    except Exception as error:   # например, волонтёр запретил сообщения от сообщества
                        storage.finish_survey(survey_id, {}, status="undelivered")
                        dialog.close_survey(user_id)
                        print(f"Анкета {app_id}: опрос не доставлен — {error}")
                for survey_id, user_id in storage.surveys_to_remind(survey_config["remind_after_days"]):
                    reply = dialog.survey_reminder(user_id)
                    if reply:
                        await send(user_id, reply)
                    storage.mark_survey_reminded(survey_id)
                for user_id in storage.expire_surveys(survey_config["expire_after_days"]):
                    dialog.close_survey(user_id)
                for item in storage.surveys_to_notify():
                    if curator_peer:
                        await bot.api.messages.send(peer_id=curator_peer, random_id=0,
                                                    message=survey.curator_alert(item))
                    storage.mark_survey_notified(item["id"])
            except Exception as error:
                print(f"Опрос волонтёров: ошибка — {error}")
            await asyncio.sleep(check_surveys_every)

    async def retrain_model():
        """Раз в несколько часов: если опросов с прошлой попытки прибавилось, модель переобучается."""
        while True:
            try:
                report = await asyncio.to_thread(retrain, storage)
                if report:
                    print(f"Модель успеха: {report['note']}")
                    if curator_peer and report["accepted"]:
                        await bot.api.messages.send(
                            peer_id=curator_peer, random_id=0,
                            message=f"Модель прогноза обновлена на ответах опроса волонтёров ({report['n_survey']}) "
                                    f"и прошлых наборах ({report['n_history']}): {report['note']}. "
                                    f"P(успеха) пересчитана у анкет: {report.get('updated', 0)}.")
            except Exception as error:
                print(f"Модель успеха: ошибка переобучения — {error}")
            await asyncio.sleep(CHECK_RETRAIN_EVERY)

    bot.loop_wrapper.add_task(process_new_applications())
    bot.loop_wrapper.add_task(send_reminders())
    bot.loop_wrapper.add_task(run_surveys())
    bot.loop_wrapper.add_task(retrain_model())
    print("Бот запущен. Остановить: Ctrl+C")
    bot.run_forever()


if __name__ == "__main__":
    main()
