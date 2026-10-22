"""Раздел «Кандидат»: всё про одного человека и решение куратора.

Решение и комментарий сохраняются сразу, без отдельной кнопки «Сохранить».
"""
import pandas as pd
import plotly.graph_objects as go_plot
import streamlit as st

from dashboard import theme
from dashboard.candidates import display_name

# «Взят в команду» — после собеседования: через четыре месяца бот пришлёт этому волонтёру опрос.
DECISIONS = ["Пригласить", "Резерв", "Отказ", "Взят в команду"]


# ---------------------------------------------------------------- выбор кандидата

def step(keys, delta):
    """Кнопки «← Предыдущий» и «Следующий →»: соседний кандидат по рейтингу."""
    position = keys.index(st.session_state["candidate_key"]) + delta
    st.session_state["candidate_key"] = keys[max(0, min(position, len(keys) - 1))]


def picker(df):
    keys = list(df["key"])
    if st.session_state.get("candidate_key") not in keys:
        st.session_state["candidate_key"] = keys[0]
    labels = {c["key"]: f"{c['place']}. {display_name(c)} · {c['index']:.0f}" for _, c in df.iterrows()}
    with st.container(key="row_picker"):   # ключ — для CSS: на телефоне стрелки остаются рядом со списком
        choose, back, forward = st.columns([6, 1, 1], vertical_alignment="bottom")
        choose.selectbox("Кандидат", keys, format_func=labels.get, key="candidate_key")
        back.button("←", help="Предыдущий в рейтинге", on_click=step, args=(keys, -1))
        forward.button("→", help="Следующий в рейтинге", on_click=step, args=(keys, 1))
    return df[df["key"] == st.session_state["candidate_key"]].iloc[0]


# ---------------------------------------------------------------- решение куратора

def save_decision(storage, key):
    decision = st.session_state.get(f"decision_{key}") or "не решено"
    note = st.session_state.get(f"note_{key}", "")
    storage.set_decision(key, decision, note)


def decision_block(c, storage, decisions):
    current, note = decisions.get(c["key"], ("не решено", ""))
    st.markdown("### Решение куратора")
    st.segmented_control("Решение", DECISIONS, default=current if current in DECISIONS else None,
                         key=f"decision_{c['key']}", on_change=save_decision, args=(storage, c["key"]),
                         label_visibility="collapsed", width="stretch")
    st.text_area("Комментарий", value=note, key=f"note_{c['key']}", height=96,
                 placeholder="Например: уточнить график на собеседовании",
                 on_change=save_decision, args=(storage, c["key"]))
    st.html('<div class="hint">Сохраняется автоматически.</div>')


# ---------------------------------------------------------------- шапка

def header(c, total):
    chips = [theme.grade_chip(c["grade"]), theme.chip(f"Место {c['place']} из {total}")]
    chips += [theme.chip(d) for d in c["directions"]]
    flags = "".join(theme.chip(f"⚠ {flag}", "chip-warn") for flag in c["flags"])
    link = (f' · <a href="{theme.esc(c["vk_url"])}" target="_blank">страница ВКонтакте</a>'
            if c["vk_url"] else "")
    score = f"{c['index']:.0f}" if pd.notna(c["index"]) else "—"
    label = f"Анкета {c['label']}" if c["name"] else ""   # без ФИО номер анкеты и так в заголовке
    st.html(f'<div class="stat-label">{theme.esc(label)}{link}</div>'
            f'<h3 style="margin:.1rem 0 .6rem;font-size:1.6rem">{theme.esc(display_name(c))}</h3>'
            f'<div>{"".join(chips)}</div><div style="margin-top:.2rem">{flags}</div>'
            f'<div class="hero-score" style="margin-top:.8rem">{score} <small>из 100</small></div>'
            f'<div class="stat-note">Балл анкеты по рубрике музея</div>')


# ---------------------------------------------------------------- сильные и слабые стороны

def factors_chart(c, df, factors):
    names = [theme.FACTOR_SHORT.get(f, title) for f, title in factors.items()]
    names.reverse()
    mine = [c.get(f"F_{f}") for f in factors][::-1]
    average = [df[f"F_{f}"].mean() for f in factors][::-1]
    figure = go_plot.Figure()
    figure.add_trace(go_plot.Bar(y=names, x=average, orientation="h", name="Среднее по набору",
                                 marker_color=theme.AVERAGE, hovertemplate="В среднем: %{x:.0f}<extra></extra>"))
    # Пустой фактор рисуем нулевым столбиком с подписью «нет данных», чтобы строка не выглядела пропавшей.
    figure.add_trace(go_plot.Bar(y=names, x=[v if pd.notna(v) else 0 for v in mine], orientation="h",
                                 name="Кандидат", marker_color=theme.RED,
                                 text=[f"{v:.0f}" if pd.notna(v) else "нет данных" for v in mine],
                                 textposition="outside", cliponaxis=False,
                                 hovertemplate="%{y}: %{x:.0f} из 100<extra></extra>"))
    figure.update_layout(barmode="group", bargap=0.35, bargroupgap=0.1)
    figure.update_xaxes(range=[0, 112], showticklabels=False, showgrid=False)
    figure = theme.style_figure(figure, height=320)
    figure.update_layout(showlegend=True, legend={"traceorder": "reversed"})
    return figure


# ---------------------------------------------------------------- что важно знать

def notes(c):
    st.markdown("### Что важно знать")
    if c["summary"]:
        st.html(f'<div class="section-note">{theme.esc(c["summary"])}</div>')
    else:
        st.html('<div class="hint">Описания нет: анкета не оценена нейросетью.</div>')
    if c["recommended_direction"]:
        st.html(f'<p style="margin-top:.8rem"><b>Подойдёт направление:</b> {theme.esc(c["recommended_direction"])}</p>')
    if c["interview_questions"]:
        questions = "".join(f"<li>{theme.esc(q)}</li>" for q in c["interview_questions"] if q.strip())
        st.html(f'<p style="margin:.8rem 0 .2rem"><b>Спросить на собеседовании:</b></p><ol>{questions}</ol>')
    if pd.notna(c["p_success"]):
        st.html(f'<p style="margin-top:.8rem"><b>Прогноз активности:</b> {c["p_success"]:.0%} '
                f'<span class="hint">— вероятность стать активным волонтёром, по данным прошлых наборов.</span></p>')
    survey_note(c)


def survey_note(c):
    """Ответы опроса через четыре месяца, если волонтёр его прошёл."""
    survey = c.get("survey")
    if not isinstance(survey, dict) or survey["status"] != "completed":
        return
    a = survey["answers"]
    text = (f'доволен(льна) на <b>{theme.esc(a.get("satisfaction", "—"))} из 5</b> · ожидания: '
            f'{theme.esc(a.get("expectations", "—")).lower()} · продолжит: {theme.esc(a.get("continue", "—")).lower()}'
            f' · часов в месяц: {theme.esc(a.get("hours", "—"))}')
    improve = f'<br>Что изменить: «{theme.esc(a["improve"])}»' if a.get("improve") else ""
    warn = f'<div style="margin-top:.3rem">{theme.chip("⚠ " + survey["alert"], "chip-warn")}</div>' if survey["alert"] else ""
    st.html(f'<p style="margin-top:.8rem"><b>Опрос через 4 месяца:</b> {text}{improve}</p>{warn}')


def details(c, items, weights):
    with st.expander("Ответы анкеты"):
        for question, answer in c["answers"].items():
            if question == "_clarified":
                continue
            if question == "followups":
                for q, a in answer:
                    st.markdown(f"**Уточнение:** {q}\n\n{a or '— пропущено'}")
                continue
            st.markdown(f"**{question}:** {', '.join(answer) if isinstance(answer, list) else answer}")
    with st.expander("Баллы по каждому вопросу"):
        rows = []
        for item, question in items.items():
            score = c.get(f"s_{item}")
            rows.append({"Вопрос": question, "Балл 0–3": f"{score:.0f}" if pd.notna(score) else "—",
                         "Вес": round(weights[item], 1)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.html('<div class="hint">Прочерк — такого вопроса в анкете не было.</div>')


# ---------------------------------------------------------------- раздел целиком

def render(df, factors, items, weights, storage, decisions):
    c = picker(df)
    st.write("")
    with st.container(key="grid_candidate"):
        left, right = st.columns([3, 2])
        with left, st.container(key="card_pink_head"):
            header(c, len(df))
        with right, st.container(key="card_white_decision"):
            decision_block(c, storage, decisions)

    st.write("")
    with st.container(key="grid_candidate_body"):
        left, right = st.columns([3, 2])
        with left, st.container(key="card_white_strengths"):
            st.markdown("### Сильные и слабые стороны")
            st.plotly_chart(factors_chart(c, df, factors), key="chart_candidate", config=theme.PLOTLY_CONFIG,
                            theme=None)
        with right, st.container(key="card_rose_notes"):
            notes(c)
    st.write("")
    details(c, items, weights)
