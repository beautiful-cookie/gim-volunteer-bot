"""Проверка настроек перед запуском: всё ли заполнено в .env и работают ли ключи.

    python scripts/check_setup.py                 # с проверкой ключей ВКонтакте и GigaChat через интернет
    python scripts/check_setup.py --offline       # только файлы и заполненность .env
    docker compose run --rm bot python scripts/check_setup.py     # то же внутри Docker

✓ — всё в порядке, ! — работать будет, но стоит поправить, ✗ — без этого бот не заработает.
Значения ключей скрипт не печатает.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from scorer.llm import LLMError, load_env, make_provider  # noqa: E402
from scorer.score import load_rubric  # noqa: E402

VK_API = "https://api.vk.com/method/"
VK_VERSION = "5.199"
problems = []


def ok(text):
    print(f"  ✓ {text}")


def warn(text):
    print(f"  ! {text}")


def fail(text):
    print(f"  ✗ {text}")
    problems.append(text)


def vk(method, token, **params):
    """Вызов API ВКонтакте. Ключ передаём в теле запроса, а не в адресе — так он не попадает в логи."""
    reply = httpx.post(VK_API + method, data={"access_token": token, "v": VK_VERSION, **params}, timeout=20).json()
    if "error" in reply:
        raise RuntimeError(reply["error"].get("error_msg", "ошибка ВКонтакте"))
    return reply["response"]


def check_files():
    print("Файлы")
    if (ROOT / ".env").exists():
        ok(".env на месте")
    else:
        fail(".env не найден: скопируйте .env.example в .env и заполните")
    try:
        rubric = load_rubric()
        ok(f"рубрика config/rubric.yaml читается: {len(rubric['items'])} пунктов")
    except Exception as error:
        fail(f"config/rubric.yaml с ошибкой: {error}")
    if (ROOT / "config" / "model.json").exists():
        ok("модель прогноза config/model.json на месте")
    else:
        warn("нет config/model.json — бот будет работать, но без прогноза активности")
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    if os.access(data, os.W_OK):
        ok("в папку data можно писать (там база бота и копии)")
    else:
        fail("в папку data нельзя писать — проверьте права доступа")
    if (data / "scored.xlsx").exists():
        ok("прошлые наборы есть: в дашборде будет «Прошлые наборы», модель учится и на них")
    else:
        warn("прошлых наборов нет (data/scored.xlsx) — дашборд покажет только анкеты из бота")


def check_vk(online):
    print("ВКонтакте")
    token = os.environ.get("VK_GROUP_TOKEN")
    peer = os.environ.get("VK_CURATOR_PEER_ID", "")
    if not token:
        fail("не задан VK_GROUP_TOKEN — ключ сообщества: Управление → Работа с API → Ключи доступа")
        return
    if not peer:
        warn("не задан VK_CURATOR_PEER_ID — карточки анкет кураторам приходить не будут. "
             "Добавьте сообщество в беседу кураторов и напишите в ней /id")
    elif not peer.isdigit() or int(peer) <= 2_000_000_000:
        warn("VK_CURATOR_PEER_ID — не беседа, а личные сообщения одного человека: карточки увидит только он "
             "(у бесед номер больше 2000000000)")
    if not online:
        return
    try:
        groups = vk("groups.getById", token)
        group = (groups.get("groups") or [{}])[0] if isinstance(groups, dict) else groups[0]
        ok(f"ключ сообщества работает: «{group.get('name', '?')}»")
        settings = vk("groups.getLongPollSettings", token, group_id=group["id"])
        if settings.get("is_enabled"):
            ok("Long Poll включён — бот будет получать сообщения")
        else:
            fail("Long Poll выключен: Управление → Работа с API → Long Poll API → Включён, "
                 "типы событий — «Входящее сообщение»")
    except Exception as error:
        fail(f"ключ сообщества не работает: {error}")
        return
    if peer.isdigit():
        try:
            if vk("messages.getConversationsById", token, peer_ids=peer).get("count"):
                ok("бот состоит в беседе кураторов")
            else:
                fail("бот не видит беседу кураторов: добавьте сообщество в беседу и проверьте номер")
        except Exception as error:
            fail(f"беседу кураторов проверить не удалось: {error}")


def check_llm(online):
    print("GigaChat")
    if not os.environ.get("GIGACHAT_CREDENTIALS"):
        warn("не задан GIGACHAT_CREDENTIALS — бот будет работать на правилах: без уточнений, саммари "
             "и оценки открытых ответов")
        return
    if os.environ.get("GIGACHAT_VERIFY_SSL", "true").lower() == "false" and not os.environ.get("GIGACHAT_CA_BUNDLE"):
        warn("проверка сертификата GigaChat выключена — укажите GIGACHAT_CA_BUNDLE "
             "(в Docker это уже сделано)")
    if not online:
        return
    try:
        provider = make_provider("gigachat")
        provider.inner._auth()
        ok(f"ключ GigaChat работает, модель {provider.model}")
    except LLMError as error:
        fail(f"GigaChat не отвечает: {str(error)[:200]}")


def check_dashboard():
    print("Дашборд")
    if os.environ.get("DASHBOARD_PASSWORD"):
        ok("пароль дашборда задан")
    else:
        warn("не задан DASHBOARD_PASSWORD — без пароля дашборд можно открывать только на этом компьютере")
    if os.environ.get("DASHBOARD_DOMAIN"):
        ok(f"адрес для HTTPS: https://{os.environ['DASHBOARD_DOMAIN']}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="не обращаться к ВКонтакте и GigaChat")
    a = ap.parse_args()

    load_env()
    check_files()
    check_vk(not a.offline)
    check_llm(not a.offline)
    check_dashboard()
    print()
    if problems:
        print(f"Нужно исправить: {len(problems)}. Подробности — в docs/install.md, раздел «Если что-то не так».")
        sys.exit(1)
    print("Всё готово к запуску: docker compose up -d")


if __name__ == "__main__":
    main()
