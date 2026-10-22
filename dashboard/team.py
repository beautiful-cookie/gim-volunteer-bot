"""Раздел «Сборка команды»: куратор вводит места по направлениям — система раскладывает кандидатов.

Логика распределения — в dashboard/assign.py. Здесь только интерфейс: места, закрепление вручную,
команда по направлениям с объяснениями, сравнение с отбором «просто по рейтингу» и кнопка «Пригласить».
"""
import streamlit as st

from dashboard import theme
from dashboard.assign import DIRECTIONS, average_forecast, build_team
from dashboard.candidates import display_name
from dashboard.navigation import open_candidate

DEFAULT_PLACES = {"Организационное": 6, "Проектное": 4, "Фондовое": 2, "Инклюзивное": 3, "Медиа": 3}
NOT_IN_POOL = ("Отказ", "Взят в команду")   # отказанных и уже работающих волонтёров не распределяем


def places_inputs():
    st.markdown("### Сколько мест в каждом направлении")
    with st.container(key="grid_places"):
        columns = st.columns(len(DIRECTIONS))
    places = {}
    for column, direction in zip(columns, DIRECTIONS):
        places[direction] = column.number_input(direction, min_value=0, max_value=50,
                                                value=DEFAULT_PLACES[direction], key=f"places_{direction}")
    return places


def pins_block(pool):
    """Закрепить кандидата за направлением вручную — остальные перераспределятся."""
    pins = st.session_state.setdefault("team_pins", {})
    names = {c["key"]: display_name(c) for c in pool}
    with st.expander(f"Закрепить вручную ({len(pins)})"):
        with st.container(key="row_pin"):
            who, where, button = st.columns([3, 2, 1], vertical_alignment="bottom")
        key = who.selectbox("Кандидат", list(names), format_func=names.get, key="pin_who")
        direction = where.selectbox("Направление", DIRECTIONS, key="pin_where")
        if button.button("Закрепить", width="stretch"):
            pins[key] = direction
        for pinned_key, pinned_direction in list(pins.items()):
            if pinned_key not in names:
                continue
            text, remove = st.columns([5, 1], vertical_alignment="center")
            text.html(f'{theme.esc(names[pinned_key])} → <b>{theme.esc(pinned_direction)}</b>')
            if remove.button("Снять", key=f"unpin_{pinned_key}"):
                del pins[pinned_key]
                st.rerun()
    return pins


def stat_cards(team, left_out, pool, places):
    members = [c for group in team.values() for c, _ in group]
    total = sum(places.values())
    # Взять просто первых N по рейтингу — сколько из них не встанут ни на одно место (переполнены фонды,
    # не подходит график)? Это то, что куратор сейчас разруливает вручную.
    by_rating = sorted(pool, key=lambda c: -(c["index"] or 0))[:total]
    _, misfit = build_team(by_rating, places)
    with st.container(key="grid_stats"):
        columns = st.columns(4)
        with columns[0], st.container(key="card_pink_team_size"):
            st.html(theme.stat("Собрано", len(members), f"Кандидатов в пуле: {len(pool)}.", small=f"из {total} мест"))
        with columns[1], st.container(key="card_red_team_forecast"):
            st.html(theme.stat("Прогноз активности команды", f"{average_forecast(members):.0%}",
                               "Средняя вероятность стать активным волонтёром."))
        with columns[2], st.container(key="card_beige_team_rating"):
            st.html(theme.stat("Если брать просто по рейтингу", len(misfit),
                               f"из первых {total} по баллу не встали бы ни на одно место: "
                               f"направление переполнено или не подходит график.", small=f"из {total}"))
        with columns[3], st.container(key="card_rose_team_left"):
            st.html(theme.stat("Не попали", len(left_out), "Причина — у каждого ниже."))


def direction_cards(team, places):
    shown = [d for d in DIRECTIONS if places[d] > 0]
    for start in range(0, len(shown), 3):
        with st.container(key=f"grid_team_{start}"):
            columns = st.columns(3)
        for column, direction in zip(columns, shown[start:start + 3]):
            members = team[direction]
            with column, st.container(key=f"card_white_team_{direction}"):
                st.markdown(f"### {direction} · {len(members)} из {places[direction]}")
                if not members:
                    st.html('<div class="hint">Никто из выбравших это направление не подошёл.</div>')
                for c, why in members:
                    with st.container(key=f"row_team_{c['key'].replace(':', '_')}"):
                        row, button = st.columns([4, 1], vertical_alignment="center")
                    row.html(f'<div class="rank-row"><div class="rank-name" style="white-space:normal">'
                             f'{theme.esc(display_name(c))}<span>{theme.esc(why)}</span></div></div>')
                    button.button("→", key=f"team_open_{c['key']}", help="Открыть карточку",
                                  on_click=open_candidate, args=(c["key"],))
        st.write("")


def invite_button(team, storage, decisions):
    """Отметить всю собранную команду решением «Пригласить» — с направлением в комментарии."""
    if not st.button("Пригласить собранную команду", type="primary"):
        return
    count = 0
    for direction, members in team.items():
        for c, _ in members:
            decision, note = decisions.get(c["key"], ("не решено", ""))
            if decision in NOT_IN_POOL:
                continue
            storage.set_decision(c["key"], "Пригласить", (note + " " if note else "") + f"Сборка команды: {direction}")
            count += 1
    st.success(f"Решение «Пригласить» поставлено {count} кандидатам. Направление записано в комментарий.")


def render(df, storage, decisions):
    st.html('<p class="lead">Введите, сколько мест в каждом направлении, — система разложит кандидатов так, '
            'чтобы каждый попал туда, где он сильнее и куда хочет сам. В фонды — только свободные по будням. '
            'Поменяйте числа, и команда пересоберётся сразу.</p>')
    pool = [c for c in df.to_dict("records") if c["decision"] not in NOT_IN_POOL]
    places = places_inputs()
    pins = pins_block(pool)
    team, left_out = build_team(pool, places, pins)
    st.write("")
    stat_cards(team, left_out, pool, places)
    st.write("")
    direction_cards(team, places)
    invite_button(team, storage, decisions)
    if left_out:
        with st.expander(f"Не попали в команду ({len(left_out)})"):
            for c, reason in left_out:
                st.html(f'<p><b>{theme.esc(display_name(c))}</b> · балл {c["index"]:.0f} — {theme.esc(reason)}</p>')
