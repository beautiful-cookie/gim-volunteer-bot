"""Автоматический анализ открытой страницы ВКонтакте кандидата (с его согласия в начале анкеты).

С ключом сообщества (VK_GROUP_TOKEN) доступно:
    — открыт ли профиль, город, дата рождения, род занятий;
    — состоит ли кандидат в музейных сообществах из списка vk_analysis.museum_groups (rubric.yaml).
      Некоторые сообщества скрывают участников — их проверить нельзя, они просто пропускаются.
С сервисным ключом приложения ВК (VK_SERVICE_TOKEN, необязательно) дополнительно:
    — подписки на сообщества с музейными и историческими названиями;
    — общие друзья с участниками сообщества волонтёров (vk_analysis.volunteers_group).

Сохраняем только выводы (сколько, какие музеи), а не списки друзей и подписок.
Любая ошибка API не роняет обработку анкеты: соответствующий признак остаётся None.
"""
import datetime
import re

from loguru import logger

_resolved_groups = {}   # короткое имя → (id, название); заполняется один раз за запуск бота


async def resolve_groups(api, screen_names):
    """Короткие имена сообществ → id. Несуществующее имя API молча подменяет нашим сообществом — сверяем имя."""
    missing = [name for name in screen_names if name not in _resolved_groups]
    for name in missing:
        try:
            group = (await api.groups.get_by_id(group_ids=[name])).groups[0]
        except Exception as error:
            logger.warning(f"Сообщество «{name}» не найдено: {error}")
            _resolved_groups[name] = None
            continue
        if (group.screen_name or "").lower() != name.lower() and f"club{group.id}" != name.lower():
            logger.warning(f"Сообщество «{name}» не найдено (ВК вернул другое: {group.screen_name})")
            _resolved_groups[name] = None
        else:
            _resolved_groups[name] = (group.id, group.name)
    return {name: _resolved_groups[name] for name in screen_names if _resolved_groups.get(name)}


async def museum_memberships(api, user_id, screen_names):
    """Названия музейных сообществ, где состоит кандидат, и сколько сообществ удалось проверить."""
    groups = await resolve_groups(api, screen_names)
    found, checked = [], 0
    for group_id, title in groups.values():
        try:
            is_member = await api.groups.is_member(group_id=group_id, user_id=user_id)
        except Exception:
            continue   # сообщество скрывает список участников
        checked += 1
        if int(is_member) == 1:
            found.append(title)
    return found, checked


def parse_vk_bdate(text):
    """«5.3.2004» → date; «5.3» (год скрыт) → None."""
    parts = (text or "").split(".")
    if len(parts) != 3:
        return None
    try:
        return datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
    except ValueError:
        return None


async def analyze_profile(api, user_id, config, service_api=None):
    """Признаки страницы кандидата для рубрики, флагов и карточки куратора."""
    result = {"name": None, "open": None, "city": None, "bdate": None, "occupation": None,
              "museum_groups": None, "museum_groups_checked": 0,
              "museum_subscriptions": None, "volunteer_friends": None}
    try:
        user = (await api.users.get(user_ids=[user_id], fields="city,bdate,occupation,is_closed"))[0]
    except Exception as error:
        logger.warning(f"Профиль {user_id} недоступен: {error}")
        return result

    result["name"] = f"{user.first_name} {user.last_name}"
    result["open"] = not user.is_closed
    result["city"] = user.city.title if user.city else None
    result["bdate"] = parse_vk_bdate(user.bdate)
    if user.occupation:
        result["occupation"] = user.occupation.name

    found, checked = await museum_memberships(api, user_id, config.get("museum_groups", []))
    result["museum_groups_checked"] = checked
    if checked:
        result["museum_groups"] = found

    if service_api is not None and result["open"]:
        result["museum_subscriptions"] = await museum_subscriptions(service_api, user_id, config["subscription_keywords"])
        result["volunteer_friends"] = await volunteer_friends(api, service_api, user_id, config.get("volunteers_group"))
    return result


async def museum_subscriptions(service_api, user_id, keywords):
    """Подписки с музейными и историческими названиями (нужен сервисный ключ)."""
    try:
        reply = await service_api.users.get_subscriptions(user_id=user_id, extended=1, count=200)
    except Exception as error:
        logger.warning(f"Подписки {user_id} недоступны: {error}")
        return None
    names = [item.name for item in reply.items if getattr(item, "name", None)]
    return [name for name in names if re.search(keywords, name.lower())]


async def volunteer_friends(api, service_api, user_id, volunteers_group):
    """Сколько друзей кандидата состоят в сообществе волонтёров (нужен сервисный ключ для списка друзей)."""
    if not volunteers_group:
        return None
    try:
        friends = await service_api.friends.get(user_id=user_id, count=5000)
    except Exception as error:
        logger.warning(f"Друзья {user_id} недоступны: {error}")
        return None
    if not friends.items:
        return 0
    try:
        members = await api.groups.is_member(group_id=volunteers_group, user_ids=friends.items[:500])
    except Exception as error:
        logger.warning(f"Не удалось проверить сообщество волонтёров: {error}")
        return None
    return sum(1 for member in members if getattr(member, "member", 0) == 1)


def profile_summary(profile):
    """Одна строка для карточки куратора и дашборда. Пустая — страницу не проверяли (например, в симуляторе)."""
    if profile is None:
        return ""
    if profile.get("open") is None:
        return "страница ВК недоступна"
    parts = ["профиль открыт" if profile["open"] else "профиль закрыт"]
    if profile.get("city"):
        parts.append(f"город: {profile['city']}")
    if profile.get("occupation"):
        parts.append(f"место учёбы или работы: {profile['occupation']}")
    groups = profile.get("museum_groups")
    if groups:
        parts.append("музейные сообщества: " + ", ".join(groups))
    elif groups == []:
        parts.append("в проверенных музейных сообществах не состоит")
    if profile.get("museum_subscriptions"):
        parts.append(f"исторических и музейных подписок: {len(profile['museum_subscriptions'])}")
    if profile.get("volunteer_friends") is not None:
        parts.append(f"друзей среди волонтёров: {profile['volunteer_friends']}")
    return "; ".join(parts)
