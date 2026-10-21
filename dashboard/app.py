"""Дашборд кураторов волонтёрской программы ГИМ.

Запуск из корня проекта:
    streamlit run dashboard/app.py

Вкладки: обзор набора (макро), рейтинг с ползунками весов, карточка кандидата (микро) с решением куратора,
качество модели. Слева — выбор набора, веса вопросов и выгрузка в Excel.
Если в .env задан DASHBOARD_PASSWORD, дашборд сначала спросит пароль.
"""
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from bot.storage import Storage  # noqa: E402
from dashboard.data import (BOT_DB, apply_weights, default_weights, factor_titles, item_titles,  # noqa: E402
                            load_bot, load_historical, model_metrics)
from dashboard.export import build_excel  # noqa: E402
from scorer.llm import load_env  # noqa: E402

GRADE_COLORS = {"0": "#9AA2B0", "1": "#C98A1B", "2": "#2A64B5", "3": "#2F7A4C"}
DECISIONS = ["не решено", "Пригласить", "Резерв", "Отказ"]

st.set_page_config(page_title="Отбор волонтёров ГИМ", page_icon="🏛", layout="wide")


# ---------------------------------------------------------------- вход по паролю

def password_ok():
    load_env()
    password = os.environ.get("DASHBOARD_PASSWORD")
    if not password or st.session_state.get("authorized"):
        return True
    typed = st.text_input("Пароль дашборда", type="password")
    if typed == password:
        st.session_state["authorized"] = True
        st.rerun()
    elif typed:
        st.error("Неверный пароль.")
    return False


if not password_ok():
    st.stop()


# ---------------------------------------------------------------- данные

@st.cache_data(ttl=30)
def load(source):
    return load_bot() if source == "bot" else load_historical()


storage = Storage(BOT_DB)
factors = factor_titles()
items = item_titles()

st.sidebar.title("Отбор волонтёров ГИМ")
source_name = st.sidebar.radio("Набор", ["Текущий набор (бот)", "История 2024–2025"])
source = "bot" if source_name.startswith("Текущий") else "hist"
raw = load(source)

if raw.empty:
    st.info("Пока нет ни одной анкеты. Когда кандидаты отправят анкеты через бота, они появятся здесь. "
            "Чтобы посмотреть, как выглядит дашборд, выберите слева «История 2024–2025».")
    st.stop()

# Веса вопросов — те же, что представитель проставил в таблице; ползунки меняют их на лету.
with st.sidebar.expander("Веса вопросов", expanded=False):
    st.caption("По умолчанию — веса представителя из config/rubric.yaml. Индекс и рейтинг пересчитываются сразу.")
    if st.button("Вернуть веса представителя"):
        for item in items:
            st.session_state.pop(f"w_{item}", None)
    weights = {}
    defaults = default_weights()
    for item, question in items.items():
        weights[item] = st.slider(question[:60], 0, 5, defaults[item], key=f"w_{item}")

free_places = st.sidebar.number_input("Свободных мест в наборе", min_value=0, max_value=100, value=18)

df = apply_weights(raw, weights)
decisions = storage.decisions()
df["decision"] = [decisions.get(key, ("не решено", ""))[0] for key in df["key"]]
df = df.sort_values("index", ascending=False).reset_index(drop=True)
df["place"] = range(1, len(df) + 1)

st.sidebar.download_button(
    "Скачать Excel", data=build_excel(df, factors, items, decisions),
    file_name=f"anketa_{source}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.sidebar.caption("Листы: рейтинг, ответы, вопросы к собеседованию, сводка набора.")


def grade_text(value):
    return "—" if pd.isna(value) else str(int(value))


tab_overview, tab_rating, tab_card, tab_model = st.tabs(
    ["Обзор набора", "Рейтинг", "Карточка кандидата", "Качество модели"])


# ---------------------------------------------------------------- обзор набора

with tab_overview:
    invited = int((df["decision"] == "Пригласить").sum())
    flagged = int(df["flags"].apply(bool).sum())
    columns = st.columns(5)
    columns[0].metric("Анкет", len(df))
    columns[1].metric("Средний индекс", f"{df['index'].mean():.0f}")
    columns[2].metric("С оценкой 3", int((df["grade"] == 3).sum()))
    columns[3].metric("С флагами", flagged)
    columns[4].metric("Приглашено / мест", f"{invited} / {free_places}")

    left, right = st.columns(2)
    with left:
        chart = df.assign(Оценка=df["grade"].apply(grade_text))
        figure = px.histogram(chart, x="index", color="Оценка", nbins=20, range_x=[0, 100],
                              color_discrete_map=GRADE_COLORS, category_orders={"Оценка": ["3", "2", "1", "0"]},
                              labels={"index": "Индекс 0–100", "count": "Анкет"}, title="Распределение индекса")
        figure.update_layout(bargap=0.05, yaxis_title="Анкет")
        st.plotly_chart(figure, width="stretch")
    with right:
        chart = df.assign(Оценка=df["grade"].apply(grade_text), P=df["p_success"].fillna(0.3))
        figure = px.scatter(chart, x="F_experience", y="F_engagement", color="Оценка", size="P", size_max=16,
                            hover_name="label", hover_data={"name": True, "index": True, "P": False},
                            color_discrete_map=GRADE_COLORS, range_x=[-5, 105], range_y=[-5, 105],
                            labels={"F_experience": "Опыт и навыки", "F_engagement": "Вовлечённость"},
                            title="Вовлечённость × опыт")
        st.plotly_chart(figure, width="stretch")
        st.caption("Размер точки — вероятность успеха по модели. Справа сверху — опытные и вовлечённые.")

    left, right = st.columns(2)
    with left:
        demand = Counter(d for ds in df["directions"] for d in ds)
        chart = pd.DataFrame(demand.most_common(), columns=["Направление", "Кандидатов"])
        figure = px.bar(chart, x="Кандидатов", y="Направление", orientation="h", title="Спрос на направления")
        figure.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(figure, width="stretch")
    with right:
        if source == "bot":
            stages = [("Начали анкету", raw.attrs.get("sessions_started", len(df))), ("Отправили", len(df)),
                      ("Оценены", int((df["status"] == "scored").sum())), ("Приглашены", invited)]
        else:
            order = ["не приглашён", "не пришёл", "не взят после собеседования", "взят", "нет данных"]
            counts = df["stage"].value_counts()
            stages = [(stage, int(counts.get(stage, 0))) for stage in order]
        chart = pd.DataFrame(stages, columns=["Этап", "Кандидатов"])
        figure = px.funnel(chart, x="Кандидатов", y="Этап", title="Воронка набора")
        st.plotly_chart(figure, width="stretch")

    left, right = st.columns(2)
    with left:
        chart = pd.DataFrame(Counter(df["channel"].fillna("не указан")).most_common(), columns=["Источник", "Кандидатов"])
        st.plotly_chart(px.pie(chart, names="Источник", values="Кандидатов", hole=0.5, title="Откуда узнали"),
                        width="stretch")
    with right:
        flags = Counter(f for fs in df["flags"] for f in fs)
        if flags:
            chart = pd.DataFrame(flags.most_common(8), columns=["Флаг", "Анкет"])
            figure = px.bar(chart, x="Анкет", y="Флаг", orientation="h", title="Частые флаги")
            figure.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(figure, width="stretch")


# ---------------------------------------------------------------- рейтинг

with tab_rating:
    filters = st.columns([2, 2, 1, 2])
    all_directions = sorted({d for ds in df["directions"] for d in ds})
    chosen_directions = filters[0].multiselect("Направления", all_directions, placeholder="Все")
    chosen_grades = filters[1].multiselect("Оценка", [3, 2, 1, 0], placeholder="Все")
    hide_flagged = filters[2].checkbox("Без флагов")
    search = filters[3].text_input("Поиск по ФИО или номеру")

    view = df
    if chosen_directions:
        view = view[view["directions"].apply(lambda ds: any(d in ds for d in chosen_directions))]
    if chosen_grades:
        view = view[view["grade"].isin(chosen_grades)]
    if hide_flagged:
        view = view[~view["flags"].apply(bool)]
    if search:
        mask = view["name"].str.contains(search, case=False, na=False) | view["label"].str.contains(search, case=False)
        view = view[mask]

    table = pd.DataFrame({
        "Место": view["place"], "Анкета": view["label"], "ФИО": view["name"],
        "Индекс": view["index"], "Оценка": view["grade"], "P(успеха)": view["p_success"],
        **{title: view[f"F_{factor}"] for factor, title in factors.items()},
        "Флаги": view["flags"].apply(", ".join), "Направления": view["directions"].apply(", ".join),
        "Решение": view["decision"],
    })
    event = st.dataframe(
        table, hide_index=True, width="stretch", height=560, on_select="rerun", selection_mode="single-row",
        column_config={
            "Индекс": st.column_config.ProgressColumn("Индекс", min_value=0, max_value=100, format="%.0f"),
            "P(успеха)": st.column_config.ProgressColumn("P(успеха)", min_value=0, max_value=1, format="%.2f"),
            "Оценка": st.column_config.NumberColumn("Оценка", format="%d"),
        })
    st.caption(f"Показано {len(view)} из {len(df)}. Индекс зависит от весов слева, P(успеха) — от модели "
               "и от весов не зависит. Выберите строку, чтобы открыть кандидата во вкладке «Карточка кандидата».")
    if event.selection.rows:
        st.session_state["selected_key"] = view.iloc[event.selection.rows[0]]["key"]
        st.success(f"Выбран {view.iloc[event.selection.rows[0]]['label']} — откройте вкладку «Карточка кандидата».")


# ---------------------------------------------------------------- карточка кандидата

SHORT_FACTOR_NAMES = {"engagement": "Вовлечённость", "availability": "Доступность", "experience": "Опыт",
                      "direction_fit": "Направление", "quality": "Качество"}


def radar(candidate, everyone):
    names = [SHORT_FACTOR_NAMES.get(f, title) for f, title in factors.items()]
    mine = [candidate.get(f"F_{f}") or 0 for f in factors]
    mean = [everyone[f"F_{f}"].mean() for f in factors]
    figure = go.Figure()
    figure.add_trace(go.Scatterpolar(r=mean + mean[:1], theta=names + names[:1], name="Среднее по набору",
                                     line={"color": "#9AA2B0", "dash": "dash"}, fill="toself", opacity=0.4))
    figure.add_trace(go.Scatterpolar(r=mine + mine[:1], theta=names + names[:1], name="Кандидат",
                                     line={"color": "#9C2F27"}, fill="toself", opacity=0.6))
    figure.update_layout(polar={"radialaxis": {"range": [0, 100], "tickfont": {"size": 9}}},
                         margin={"t": 30, "b": 30, "l": 45, "r": 45}, legend={"orientation": "h"}, height=380)
    return figure


with tab_card:
    keys = list(df["key"])
    labels = {row["key"]: f"{row['place']}. {row['label']} {row['name']} · {row['index']}" for _, row in df.iterrows()}
    selected = st.session_state.get("selected_key", keys[0])
    key = st.selectbox("Кандидат", keys, index=keys.index(selected) if selected in keys else 0,
                       format_func=labels.get)
    c = df[df["key"] == key].iloc[0]

    st.subheader(f"{c['name']}  ·  {c['label']}" if c["name"] else c["label"])
    columns = st.columns(4)
    columns[0].metric("Оценка 0–3", grade_text(c["grade"]))
    columns[1].metric("Индекс", f"{c['index']:.0f}" if pd.notna(c["index"]) else "—")
    columns[2].metric("P(успеха)", f"{c['p_success']:.0%}" if pd.notna(c["p_success"]) else "—")
    columns[3].metric("Место в рейтинге", f"{c['place']} из {len(df)}")
    if c["vk_url"]:
        st.markdown(f"[Страница ВКонтакте]({c['vk_url']})")
    for flag in c["flags"]:
        st.warning(flag)

    left, right = st.columns([1, 1])
    with left:
        st.plotly_chart(radar(c, df), width="stretch")
    with right:
        if c["summary"]:
            st.markdown("**Саммари**")
            st.write(c["summary"])
        if c["recommended_direction"]:
            st.markdown(f"**Рекомендуемое направление:** {c['recommended_direction']}")
        if c["interview_questions"]:
            st.markdown("**Вопросы для собеседования**")
            for number, question in enumerate(c["interview_questions"], 1):
                st.write(f"{number}. {question}")

    st.markdown("**Баллы по пунктам рубрики** (0–3; пусто — такого вопроса не было)")
    scores = pd.DataFrame([{"Балл": c.get(f"s_{item}"), "Вес": weights[item], "Вопрос": question}
                           for item, question in items.items()])
    scores["Балл"] = pd.to_numeric(scores["Балл"])   # None → пустая ячейка вместо надписи «None»
    st.dataframe(scores, hide_index=True, width="stretch")
    if c["evidence"]:
        st.markdown("**Подтверждённый опыт**")
        for category, quote in c["evidence"].items():
            st.write(f"• {category}: «{quote}»")

    with st.expander("Ответы анкеты"):
        for question, answer in c["answers"].items():
            if question in ("_clarified",):
                continue
            if question == "followups":
                for q, a in answer:
                    st.write(f"**Уточнение:** {q}\n\n{a or '— пропущено'}")
                continue
            st.write(f"**{question}:** {', '.join(answer) if isinstance(answer, list) else answer}")

    st.markdown("**Решение куратора**")
    current_decision, current_note = decisions.get(key, ("не решено", ""))
    columns = st.columns([1, 3])
    decision = columns[0].radio("Решение", DECISIONS, index=DECISIONS.index(current_decision),
                                key=f"decision_{key}", label_visibility="collapsed")
    note = columns[1].text_area("Комментарий", value=current_note, key=f"note_{key}")
    if st.button("Сохранить решение", type="primary"):
        storage.set_decision(key, decision, note)
        st.success("Решение сохранено.")
        st.rerun()


# ---------------------------------------------------------------- качество модели

with tab_model:
    st.markdown(
        "Насколько индекс и модель предсказывают **реальную активность** волонтёров (часов в год), "
        "по историческим данным 2024–2025 гг. AUC 0,5 — угадывание наугад, 1,0 — идеальное разделение. "
        "Взятых волонтёров с известными часами всего 44, поэтому интервалы широкие: "
        "цифры станут надёжнее после загрузки анкет 2017–2023 гг.")
    for name, table in model_metrics().items():
        st.markdown(f"**Успех: {name.replace('AUC ', '').replace('ч', ' ч/год')}**")
        st.dataframe(table, hide_index=True, width="stretch")

    history = apply_weights(load("hist"), weights)
    taken = history[history["outcome_hours"].notna()]
    if not taken.empty:
        left, right = st.columns(2)
        with left:
            figure = px.box(history, x="curator_score", y="index", points="all",
                            labels={"curator_score": "Балл куратора 0–3", "index": "Индекс"},
                            title="Индекс и балл куратора (112 анкет)")
            st.plotly_chart(figure, width="stretch")
        with right:
            figure = px.scatter(taken, x="index", y="outcome_hours", hover_name="label",
                                labels={"index": "Индекс", "outcome_hours": "Часов в год"},
                                title="Индекс и реальная активность (взятые волонтёры)")
            st.plotly_chart(figure, width="stretch")

    decided = df[df["decision"] != "не решено"]
    if not decided.empty:
        figure = px.box(decided, x="decision", y="index", points="all",
                        labels={"decision": "Решение куратора", "index": "Индекс"},
                        title="Решения кураторов в этом наборе и индекс")
        st.plotly_chart(figure, width="stretch")
