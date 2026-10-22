"""Раздел «Обзор»: вся картина набора на одном экране.

Сверху — пара предложений обычным языком, ниже — четыре карточки с главными цифрами,
затем графики. На столбики можно нажать: откроется список именно этих кандидатов.
"""
from collections import Counter

import plotly.graph_objects as go_plot
import streamlit as st

from dashboard import theme
from dashboard.navigation import CANDIDATES, go, open_candidate, selected_points
from dashboard.weights import grade_thresholds


def plural(number, one, few, many):
    """1 анкета, 2 анкеты, 5 анкет."""
    if number % 10 == 1 and number % 100 != 11:
        return one
    if 2 <= number % 10 <= 4 and not 12 <= number % 100 <= 14:
        return few
    return many


def summary_text(df, free_places):
    """Два-три предложения о наборе для человека, который видит дашборд впервые."""
    total = len(df)
    strong = int((df["grade"] == 3).sum())
    flagged = int(df["flags"].apply(bool).sum())
    demand = Counter(d for ds in df["directions"] for d in ds).most_common()

    parts = [f"В наборе <b>{total} {plural(total, 'анкета', 'анкеты', 'анкет')}</b>, "
             f"сильных — <b>{strong}</b>, свободных мест — <b>{free_places}</b>."]
    if flagged:
        parts.append(f"У <b>{flagged}</b> {plural(flagged, 'кандидата', 'кандидатов', 'кандидатов')} есть замечания.")
    if len(demand) >= 2:
        parts.append(f"Чаще всего выбирают <b>{demand[0][0].lower()}</b> направление, "
                     f"реже всего — <b>{demand[-1][0].lower()}</b>.")
    return " ".join(parts)


# ---------------------------------------------------------------- карточки с цифрами

def stat_cards(df, free_places):
    strong = int((df["grade"] == 3).sum())
    flags = Counter(f for fs in df["flags"] for f in fs)
    flagged = int(df["flags"].apply(bool).sum())
    invited = int(df["decision"].isin(["Пригласить", "Взят в команду"]).sum())
    decided = int((df["decision"] != "не решено").sum())
    strong_from = grade_thresholds()[2]

    with st.container(key="grid_stats"):
        columns = st.columns(4)
        with columns[0], st.container(key="card_pink_total"):
            decided_text = f"Решения приняты по {decided}." if decided else "Решений пока нет."
            st.html(theme.stat("Анкет в наборе", len(df),
                               f"Средний балл — {df['index'].mean():.0f} из 100. {decided_text}"))
        with columns[1], st.container(key="card_beige_strong"):
            st.html(theme.stat("Сильные анкеты", strong, f"Балл {strong_from} и выше.", small=f"из {len(df)}"))
        with columns[2], st.container(key="card_rose_flags"):
            top = flags.most_common(1)
            note = f"Чаще всего: {theme.esc(top[0][0])} ({top[0][1]})." if top else "Замечаний нет."
            st.html(theme.stat("С замечаниями", flagged, note))
        with columns[3], st.container(key="card_red_places"):
            left = max(free_places - invited, 0)
            share = invited / free_places if free_places else 0
            st.html(theme.stat("Приглашено", invited, theme.meter(share) + f"Свободных мест осталось: {left}.",
                               small=f"/ {free_places}"))


# ---------------------------------------------------------------- графики

def grades_chart(df):
    """Сколько анкет с каждой оценкой. Нажатие на столбик — список этих кандидатов."""
    names = [theme.GRADE_NAMES[g] for g in (3, 2, 1, 0)]
    counts = [int((df["grade"] == g).sum()) for g in (3, 2, 1, 0)]
    figure = go_plot.Figure(go_plot.Bar(
        x=names, y=counts, text=counts, textposition="outside", cliponaxis=False,
        marker_color=[theme.GRADE_COLORS[g] for g in (3, 2, 1, 0)],
        hovertemplate="%{x} анкета: %{y}<extra>Нажмите, чтобы открыть список</extra>"))
    figure.update_yaxes(showticklabels=False, showgrid=False)
    return theme.style_figure(figure, height=250)


def directions_chart(df):
    demand = Counter(d for ds in df["directions"] for d in ds).most_common()
    demand.reverse()   # в горизонтальном графике первая строка — внизу
    figure = go_plot.Figure(go_plot.Bar(
        y=[name for name, _ in demand], x=[count for _, count in demand], orientation="h",
        text=[count for _, count in demand], textposition="outside", cliponaxis=False,
        marker_color=theme.RED, width=0.5,
        hovertemplate="%{y}: %{x} кандидатов<extra>Нажмите, чтобы открыть список</extra>"))
    figure.update_xaxes(showticklabels=False, showgrid=False)
    return theme.style_figure(figure, height=250)


def factors_chart(df, factors):
    """Средний балл набора по каждому фактору — где кандидатам в целом не хватает."""
    rows = sorted(((theme.FACTOR_SHORT.get(f, title), df[f"F_{f}"].mean()) for f, title in factors.items()),
                  key=lambda row: row[1])
    figure = go_plot.Figure(go_plot.Bar(
        y=[name for name, _ in rows], x=[value for _, value in rows], orientation="h",
        text=[f"{value:.0f}" for _, value in rows], textposition="outside", cliponaxis=False,
        marker_color=theme.RED, width=0.5, hovertemplate="%{y}: в среднем %{x:.0f} из 100<extra></extra>"))
    figure.update_xaxes(range=[0, 108], showticklabels=False, showgrid=False)
    return theme.style_figure(figure, height=250)


def on_grade_click():
    points = selected_points("chart_grades")
    if points:
        go(CANDIDATES, filter_grades=[points[0]["x"]], filter_directions=[])


def on_direction_click():
    points = selected_points("chart_directions")
    if points:
        go(CANDIDATES, filter_directions=[points[0]["y"]], filter_grades=[])


# ---------------------------------------------------------------- лучшие кандидаты

def top_list(df, free_places, show=5):
    st.markdown(f"### Лучшие на {free_places} мест")
    st.html('<div class="hint">По баллу анкеты.</div>')
    for _, c in df.head(show).iterrows():
        name = c["name"] or f"Анкета {c['label']}"
        with st.container(key=f"row_{c['key'].replace(':', '_')}"):   # ключ — для CSS: строка не переносится
            row, button = st.columns([4, 1], vertical_alignment="center")
        row.html(f'<div class="rank-row"><div class="rank-place">{c["place"]}</div>'
                 f'<div class="rank-name">{theme.esc(name)}<span>{theme.esc(theme.grade_name(c["grade"]))} анкета'
                 f'{" · есть замечания" if c["flags"] else ""}</span></div>'
                 f'<div class="rank-score">{c["index"]:.0f}</div></div>')
        button.button("Открыть", key=f"open_{c['key']}", on_click=open_candidate, args=(c["key"],),
                      width="stretch")
    st.button("Все кандидаты →", on_click=go, args=(CANDIDATES,), type="primary")


# ---------------------------------------------------------------- раздел целиком

def render(df, factors, free_places):
    st.html(f'<p class="lead">{summary_text(df, free_places)}</p>')
    stat_cards(df, free_places)
    st.write("")

    with st.container(key="grid_charts"):
        left, right = st.columns(2)
        with left, st.container(key="card_white_grades"):
            st.markdown("### Как оценены анкеты")
            st.plotly_chart(grades_chart(df), key="chart_grades", on_select=on_grade_click,
                            selection_mode="points", config=theme.PLOTLY_CONFIG, theme=None)
            st.html('<div class="hint">Нажмите на столбик — откроется список этих кандидатов.</div>')
        with right, st.container(key="card_white_directions"):
            st.markdown("### Куда хотят кандидаты")
            st.plotly_chart(directions_chart(df), key="chart_directions", on_select=on_direction_click,
                            selection_mode="points", config=theme.PLOTLY_CONFIG, theme=None)
            st.html('<div class="hint">Один кандидат может выбрать несколько направлений.</div>')

    st.write("")
    with st.container(key="grid_bottom"):
        left, right = st.columns([3, 2])
        with left, st.container(key="card_white_top"):
            top_list(df, free_places)
        with right, st.container(key="card_white_factors"):
            st.markdown("### Сильные и слабые стороны набора")
            st.plotly_chart(factors_chart(df, factors), key="chart_factors", config=theme.PLOTLY_CONFIG, theme=None)
            st.html('<div class="hint">Средний балл по каждому фактору, из 100.</div>')


def empty_state(on_show_history):
    with st.container(key="card_pink_empty"):
        st.markdown("### Анкет пока нет")
        st.html('<p class="lead" style="margin:0 0 1rem">Здесь появятся анкеты из бота ВКонтакте. '
                'Пример — наборы 2024–2025.</p>')
        st.button("Открыть наборы 2024–2025", type="primary", on_click=on_show_history)
