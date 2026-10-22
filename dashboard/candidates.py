"""Раздел «Все кандидаты»: рейтинг с фильтрами и сравнение нескольких кандидатов между собой."""
from functools import partial

import pandas as pd
import plotly.graph_objects as go_plot
import streamlit as st

from dashboard import theme
from dashboard.navigation import open_candidate


def display_name(candidate):
    return candidate["name"] or f"Анкета {candidate['label']}"


# ---------------------------------------------------------------- фильтры

def filters(df):
    """Строка фильтров над таблицей. Значения хранятся в session_state — их выставляет и обзор."""
    directions = sorted({d for ds in df["directions"] for d in ds})
    with st.container(key="grid_filters"):
        left, right = st.columns([2, 3])
        grades = left.pills("Оценка", list(theme.GRADE_NAMES.values()), selection_mode="multi", key="filter_grades")
        chosen = right.pills("Направление", directions, selection_mode="multi", key="filter_directions")
    with st.container(key="grid_search"):
        left, right = st.columns([2, 3], vertical_alignment="center")
        search = left.text_input("Поиск", placeholder="Имя или номер анкеты", key="filter_search",
                                 label_visibility="collapsed")
        clean = right.toggle("Только без замечаний", key="filter_clean",
                             help="Скрыть кандидатов, у которых есть что уточнить: 1 курс, только фонды и т. п.")

    view = df
    if grades:
        view = view[view["grade"].apply(theme.grade_name).isin(grades)]
    if chosen:
        view = view[view["directions"].apply(lambda ds: any(d in ds for d in chosen))]
    if clean:
        view = view[~view["flags"].apply(bool)]
    if search:
        mask = (view["name"].str.contains(search, case=False, na=False)
                | view["label"].str.contains(search, case=False, na=False))
        view = view[mask]
    return view


# ---------------------------------------------------------------- рейтинг

def on_row_click(keys):
    event = st.session_state.get("table_rating")
    if event and event.selection.rows:
        open_candidate(keys[event.selection.rows[0]])


def rating_table(view, factors, free_places):
    show_factors = st.toggle("Показать баллы по факторам", key="show_factors")
    table = pd.DataFrame({
        "Место": view["place"],
        "Кандидат": [display_name(c) for _, c in view.iterrows()],
        "Балл": view["index"],
        "Оценка": view["grade"].apply(theme.grade_name),
        "На места": ["✓" if place <= free_places else "" for place in view["place"]],
        "Обратить внимание": view["flags"].apply(", ".join),
        "Направления": view["directions"].apply(", ".join),
        "Решение": view["decision"].replace("не решено", ""),
    })
    column_config = {
        "Место": st.column_config.NumberColumn(width="small"),
        "Балл": st.column_config.ProgressColumn("Балл", min_value=0, max_value=100, format="%.0f",
                                                help="Балл анкеты из 100 по рубрике музея и выбранной важности факторов"),
        "На места": st.column_config.TextColumn(width="small",
                                                help=f"Входит в первые {free_places} по баллу (свободных мест — слева)"),
    }
    if show_factors:
        for factor in factors:
            title = theme.FACTOR_SHORT.get(factor, factors[factor])
            table[title] = view[f"F_{factor}"]
            column_config[title] = st.column_config.ProgressColumn(title, min_value=0, max_value=100, format="%.0f",
                                                                   help=theme.FACTOR_HINTS.get(factor))
    # У st.dataframe нет параметра args для колбэка, поэтому ключи строк «пришиваем» через partial.
    st.dataframe(table, hide_index=True, width="stretch", height=480, key="table_rating",
                 on_select=partial(on_row_click, list(view["key"])), selection_mode="single-row",
                 column_config=column_config)


# ---------------------------------------------------------------- сравнение

def compare_chart(df, keys, factors):
    """Сгруппированные столбики: факторы по вертикали, у каждого кандидата свой цвет."""
    names = [theme.FACTOR_SHORT.get(f, title) for f, title in factors.items()]
    names.reverse()
    figure = go_plot.Figure()
    # В горизонтальной группе первый ряд рисуется снизу — добавляем кандидатов с конца,
    # чтобы сверху был первый выбранный, а легенду разворачиваем обратно.
    for number in reversed(range(len(keys))):
        c = df[df["key"] == keys[number]].iloc[0]
        values = [c.get(f"F_{f}") for f in factors][::-1]
        figure.add_trace(go_plot.Bar(
            y=names, x=[v if pd.notna(v) else 0 for v in values], orientation="h", name=display_name(c),
            marker_color=theme.COMPARE_COLORS[number],
            customdata=[f"{v:.0f} из 100" if pd.notna(v) else "нет данных" for v in values],
            hovertemplate=f"{theme.esc(display_name(c))}<br>%{{y}}: %{{customdata}}<extra></extra>"))
    figure.update_layout(barmode="group", bargap=0.3, bargroupgap=0.12)
    figure.update_xaxes(range=[0, 100])
    figure = theme.style_figure(figure, height=110 + 60 * len(keys) * 2)
    figure.update_layout(showlegend=True, legend={"traceorder": "reversed"})
    return figure


def compare(df, factors, free_places):
    st.markdown("### Сравнить кандидатов")
    st.html('<div class="hint">Выберите до трёх кандидатов. Сначала показаны пограничные: '
            'последний, кто проходит на свободные места, и первый, кто не проходит.</div>')
    labels = {c["key"]: f"{c['place']}. {display_name(c)} · {c['index']:.0f}" for _, c in df.iterrows()}
    if "compare_keys" not in st.session_state:
        border = min(free_places, len(df) - 1)   # места считаются с 1, строки — с 0
        st.session_state["compare_keys"] = list(df["key"].iloc[max(border - 1, 0):border + 1])
    keys = st.multiselect("Кандидаты", list(df["key"]), max_selections=3, format_func=labels.get,
                          key="compare_keys", label_visibility="collapsed")
    if len(keys) < 2:
        st.info("Выберите хотя бы двух кандидатов.")
        return
    st.plotly_chart(compare_chart(df, keys, factors), key="chart_compare", config=theme.PLOTLY_CONFIG, theme=None)

    # Те же цифры таблицей — для точного сравнения и для тех, кому трудно различать цвета.
    rows = {}
    for key in keys:
        c = df[df["key"] == key].iloc[0]
        values = {"Балл анкеты": c["index"], **{theme.FACTOR_SHORT.get(f, t): c.get(f"F_{f}") for f, t in factors.items()}}
        # Streamlit показывает пропуск как «None» — выводим числа текстом, а пропуск прочерком.
        rows[display_name(c)] = {name: f"{v:.0f}" if pd.notna(v) else "—" for name, v in values.items()}
    st.dataframe(pd.DataFrame(rows), width="stretch")


# ---------------------------------------------------------------- раздел целиком

def render(df, factors, free_places, excel_bytes, excel_name):
    text, button = st.columns([4, 1], vertical_alignment="center")
    text.html('<p class="lead" style="margin:0">Все анкеты набора по баллу. '
              'Выберите строку — откроется карточка кандидата.</p>')
    button.download_button("Скачать Excel", data=excel_bytes, file_name=excel_name, width="stretch",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.write("")
    view = filters(df)

    with st.container(key="card_white_rating"):
        st.markdown(f"### Рейтинг · {len(view)} из {len(df)}")
        rating_table(view, factors, free_places)

    st.write("")
    with st.container(key="card_white_compare"):
        compare(df, factors, free_places)
