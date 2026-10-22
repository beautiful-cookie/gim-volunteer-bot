"""Сборка команды: раскладываем кандидатов по направлениям с учётом мест, графика и прогноза активности.

Правило простое, его можно объяснить за минуту:
    1. Для каждой пары «кандидат — направление, которое он выбрал» считаем пригодность:
       половина — балл анкеты, половина — прогноз активности; +10, если это направление советует
       нейросеть по анкете. В фонды берём только тех, кто свободен по будням (там работают днём в будни).
    2. Сначала ставим закреплённых куратором вручную.
    3. Дальше идём по парам от самой пригодной к наименее: если кандидат ещё свободен и в направлении
       есть место — ставим. Так каждый попадает туда, где он сильнее, а сильные не занимают чужие места.
У каждого решения — объяснение словами, у каждого не попавшего — причина.
"""
import math

DIRECTIONS = ["Организационное", "Проектное", "Фондовое", "Инклюзивное", "Медиа"]
WEEKDAYS_ONLY = {"Фондовое"}


def is_missing(value):
    return value is None or (isinstance(value, float) and math.isnan(value))


def wanted(c):
    """Направления, куда кандидат готов: выбранные им, а если «пока не определился» — любые."""
    chosen = [d for d in c["directions"] if d in DIRECTIONS]
    return chosen or list(DIRECTIONS)


def weekdays_ok(c):
    """Свободен ли по будням. Если в анкете вопроса не было (прошлые наборы) — не знаем, не запрещаем."""
    schedule = (c.get("answers") or {}).get("schedule")
    return schedule in (None, "", "Будни", "Гибко")


def forecast(c):
    """Прогноз активности 0–1; если модели нет — балл анкеты как запасной вариант."""
    if not is_missing(c.get("p_success")):
        return float(c["p_success"])
    return float(c["index"]) / 100 if not is_missing(c.get("index")) else 0.0


def fitness(c, direction):
    """Пригодность кандидата для направления, 0–110, и объяснение словами. None — направление ему закрыто."""
    if direction in WEEKDAYS_ONLY and not weekdays_ok(c):
        return None, "в фонды только по будням"
    index = 0.0 if is_missing(c.get("index")) else float(c["index"])
    score = 0.5 * index + 50 * forecast(c)
    reasons = [f"балл {index:.0f}", f"прогноз активности {forecast(c):.0%}"]
    if c.get("recommended_direction") == direction:
        score += 10
        reasons.append("нейросеть советует это направление")
    if direction in WEEKDAYS_ONLY:
        reasons.append("свободен(на) по будням")
    return score, ", ".join(reasons)


def build_team(candidates, places, pinned=None):
    """candidates — строки дашборда (dict), places — {направление: мест}, pinned — {key: направление}.

    Возвращает (команда {направление: [(кандидат, объяснение)]}, не попавшие [(кандидат, причина)])."""
    pinned = pinned or {}
    team = {d: [] for d in DIRECTIONS}
    free = dict(places)
    placed = set()

    for c in candidates:
        direction = pinned.get(c["key"])
        if direction and free.get(direction, 0) > 0:
            team[direction].append((c, "закреплён(а) куратором"))
            free[direction] -= 1
            placed.add(c["key"])

    pairs = []
    for c in candidates:
        if c["key"] in placed:
            continue
        for direction in wanted(c):
            score, why = fitness(c, direction)
            if score is not None:
                pairs.append((score, c["key"], direction, c, why))
    pairs.sort(key=lambda pair: (-pair[0], pair[1]))

    for score, key, direction, c, why in pairs:
        if key in placed or free.get(direction, 0) <= 0:
            continue
        team[direction].append((c, why))
        free[direction] -= 1
        placed.add(key)

    left_out = []
    for c in candidates:
        if c["key"] in placed:
            continue
        closed = [d for d in wanted(c) if fitness(c, d)[0] is None]
        if closed and len(closed) == len(wanted(c)):
            reason = "в фонды только по будням, другие направления не выбраны"
        else:
            reason = "места в выбранных направлениях заняты более подходящими кандидатами"
        left_out.append((c, reason))
    return team, left_out


def average_forecast(candidates):
    values = [forecast(c) for c in candidates]
    return sum(values) / len(values) if values else 0.0
