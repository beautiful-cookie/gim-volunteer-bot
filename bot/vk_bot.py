"""Бот сообщества ВКонтакте на vkbottle (Bots Long Poll — публичный адрес сервера не нужен).

Запуск из корня проекта:
    python -m bot.vk_bot

Нужно в .env:
    VK_GROUP_TOKEN       — ключ доступа сообщества (Управление → Работа с API), права: сообщения сообщества
    VK_CURATOR_PEER_ID   — peer_id беседы кураторов (2000000000 + номер беседы), сюда приходят карточки анкет
В настройках сообщества включите «Сообщения» и «Возможности ботов».
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

from bot.application import curator_card, score_application  # noqa: E402
from bot.engine import Dialog  # noqa: E402
from bot.followups import make_planner  # noqa: E402
from bot.inline_questions import make_inline_asker  # noqa: E402
from bot.vk_profile import analyze_profile  # noqa: E402
from scorer.score import load_rubric  # noqa: E402
from bot.storage import Storage  # noqa: E402
from scorer.llm import LLMError, load_env, make_provider  # noqa: E402

COLORS = {"primary": KeyboardButtonColor.PRIMARY, "secondary": KeyboardButtonColor.SECONDARY,
          "positive": KeyboardButtonColor.POSITIVE, "negative": KeyboardButtonColor.NEGATIVE}

CHECK_NEW_APPLICATIONS_EVERY = 30      # секунд
CHECK_REMINDERS_EVERY = 30 * 60        # секунд


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
    dialog = Dialog(storage, make_planner(provider), make_inline_asker(fast_provider))
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
                    result = await asyncio.to_thread(score_application, answers, provider, 3, profile)
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

    bot.loop_wrapper.add_task(process_new_applications())
    bot.loop_wrapper.add_task(send_reminders())
    print("Бот запущен. Остановить: Ctrl+C")
    bot.run_forever()


if __name__ == "__main__":
    main()
