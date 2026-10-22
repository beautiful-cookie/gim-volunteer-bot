"""Раздел «Волонтёры»: как дела у тех, кого взяли в команду, и как модель учится на их ответах.

Через четыре месяца после решения «Взят в команду» бот присылает волонтёру короткий опрос (bot/survey.py).
О недовольных бот сразу пишет в беседу кураторов, а ответы становятся новыми примерами для модели
прогноза — она переобучается сама (bot/retrain.py). История версий модели — внизу раздела.
"""
import pandas as pd
import plotly.graph_objects as go_plot
import streamlit as st

from dashboard import theme
from dashboard.navigation import CANDIDATE, go
from dashboard.overview import plural
from scorer.score import load_rubric

STAYING = ("Да", "Скорее да")


def open_volunteer(key, bot_source):
    """Карточка волонтёра открывается в разделе «Кандидат» текущего набора."""
    go(CANDIDATE, candidate_key=key, source=bot_source)


# ---------------------------------------------------------------- цифры

def stat_cards(surveys, answered):
    alerts = answered[answered["alert"] != ""]
    satisfaction = answered["answers"].apply(lambda a: int(a["satisfaction"]) if a.get("satisfaction") else None)
    staying = answered["answers"].apply(lambda a: a.get("continue") in STAYING)
    waiting = int((surveys["status"] == "sent").sum())
    declined = int(surveys["status"].isin(["declined", "expired", "undelivered"]).sum())

    with st.container(key="grid_stats"):
        columns = st.columns(4)
        with columns[0], st.container(key="card_pink_sent"):
            st.html(theme.stat("Опрос отправлен", len(surveys),
                               f"Ответили {len(answered)}, ждём ответа {waiting}, не ответили или отказались {declined}."))
        with columns[1], st.container(key="card_beige_satisfaction"):
            average = f"{satisfaction.mean():.1f}".replace(".", ",") if satisfaction.notna().any() else "—"
            st.html(theme.stat("Довольны", average, "Средняя оценка ответивших.", small="из 5"))
        with columns[2], st.container(key="card_rose_staying"):
            share = f"{staying.mean():.0%}" if len(answered) else "—"
            st.html(theme.stat("Хотят продолжать", share, "Ответили «да» или «скорее да»."))
        with columns[3], st.container(key="card_red_alerts"):
            st.html(theme.stat("Требуют внимания", len(alerts), "Бот уже написал о них в беседу кураторов."))


# ---------------------------------------------------------------- кто недоволен

def alerts_list(answered, bot_source):
    alerts = answered[answered["alert"] != ""]
    st.markdown("### Требуют внимания")
    if alerts.empty:
        st.html('<div class="hint">Недовольных нет — все ответившие волонтёры в порядке.</div>')
        return
    st.html('<div class="hint">Стоит поговорить с волонтёром, пока он не ушёл из программы.</div>')
    for _, v in alerts.iterrows():
        name = v["name"] or f"Анкета {v['label']}"
        with st.container(key=f"row_alert_{v['key'].replace(':', '_')}"):   # ключ — для CSS: строка не переносится
            row, button = st.columns([4, 1], vertical_alignment="center")
        # Причины сигнала переносятся на новую строку, а не обрезаются многоточием, как в рейтинге.
        row.html(f'<div class="rank-row"><div class="rank-name" style="white-space:normal">{theme.esc(name)}'
                 f'<span>{theme.esc(v["alert"])}</span></div></div>')
        button.button("Открыть", key=f"open_alert_{v['key']}", on_click=open_volunteer, args=(v["key"], bot_source),
                      width="stretch")


def satisfaction_chart(answered):
    """Сколько волонтёров поставили каждую оценку от 1 до 5."""
    values = answered["answers"].apply(lambda a: a.get("satisfaction"))
    counts = [int((values == str(score)).sum()) for score in range(1, 6)]
    figure = go_plot.Figure(go_plot.Bar(
        x=[str(score) for score in range(1, 6)], y=counts, text=counts, textposition="outside", cliponaxis=False,
        marker_color=theme.RED, width=0.55,
        hovertemplate="Оценка %{x}: %{y} чел.<extra></extra>"))
    figure.update_yaxes(showticklabels=False, showgrid=False)
    figure.update_xaxes(type="category")
    return theme.style_figure(figure, height=230)


def answers_table(surveys):
    rows = []
    for _, v in surveys.iterrows():
        a = v["answers"]
        rows.append({"Волонтёр": v["name"] or f"Анкета {v['label']}", "Опрос отправлен": v["sent_at"],
                     "Статус": v["status_text"], "Доволен(льна), 1–5": a.get("satisfaction", ""),
                     "Ожидания": a.get("expectations", ""), "Продолжит": a.get("continue", ""),
                     "Часов в месяц": a.get("hours", ""), "Посоветует друзьям": a.get("recommend", ""),
                     "Что изменить": a.get("improve", ""), "Сигнал": v["alert"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# ---------------------------------------------------------------- модель учится

def model_block(versions):
    config = load_rubric()["checkin_survey"]
    rule = config["success"]
    st.markdown("### Модель учится на опросах")
    st.html(f'<p class="section-note">Каждый ответ на опрос — пример того, кто стал успешным волонтёром: '
            f'хочет продолжать («{"» или «".join(rule["continue"])}») и уделяет от 5 часов в месяц. '
            f'Когда новых ответов набирается {config["min_new_labels"]}, бот сам переобучает прогноз активности '
            f'и оставляет новую модель, только если она угадывает не хуже прежней.</p>')

    accepted = versions[versions["accepted"] == 1] if not versions.empty else versions
    if accepted.empty:
        st.html('<p><b>Сейчас работает:</b> исходная модель по наборам 2024–2025.</p>')
    else:
        last = accepted.iloc[-1]
        n_survey, n_history = int(last["n_survey"]), int(last["n_history"])
        history = f" и {n_history} волонтёрах прошлых наборов" if n_history else ""
        st.html(f'<p><b>Сейчас работает:</b> версия от {theme.esc(last["created_at"][:10])}, обучена на '
                f'{n_survey} {plural(n_survey, "ответе", "ответах", "ответах")} опроса{history}.</p>')
    if versions.empty:
        st.html('<div class="hint">Переобучений ещё не было: ждём первых ответов на опрос.</div>')
        return

    def auc(value):
        return "—" if pd.isna(value) else f"{value:.2f}".replace(".", ",")

    table = pd.DataFrame({
        "Дата": versions["created_at"].str[:10],
        "Ответов опроса": versions["n_survey"],
        "Из прошлых наборов": versions["n_history"],
        "Точность новой": versions["auc_new"].apply(auc),
        "Точность прежней": versions["auc_old"].apply(auc),
        "Итог": versions["accepted"].map({1: "принята", 0: "оставили прежнюю"}),
    })
    st.dataframe(table.iloc[::-1], hide_index=True, width="stretch")
    st.html('<div class="hint">Точность (AUC) — доля пар «успешный и неуспешный волонтёр», в которых модель '
            'поставила успешного выше: 0,5 — наугад, 1 — без ошибок. Новую модель проверяют на тех, '
            'кого она не видела при обучении.</div>')


# ---------------------------------------------------------------- раздел целиком

def render(surveys, versions, bot_source):
    st.html('<p class="lead">Через четыре месяца после решения «Взят в команду» бот спрашивает волонтёров, '
            'как идут дела. О недовольных он сразу пишет кураторам, а ответы учат прогноз активности.</p>')
    if surveys.empty:
        with st.container(key="card_pink_no_surveys"):
            st.markdown("### Опросов пока не было")
            st.html('<p class="lead" style="margin:0">Отметьте в карточке кандидата решение «Взят в команду» — '
                    'через четыре месяца бот пришлёт этому волонтёру опрос.</p>')
    else:
        answered = surveys[surveys["status"] == "completed"]
        stat_cards(surveys, answered)
        st.write("")
        with st.container(key="grid_volunteers"):
            left, right = st.columns([3, 2])
            with left, st.container(key="card_white_alerts"):
                alerts_list(answered, bot_source)
            with right, st.container(key="card_white_satisfaction"):
                st.markdown("### Насколько довольны")
                st.plotly_chart(satisfaction_chart(answered), key="chart_satisfaction",
                                config=theme.PLOTLY_CONFIG, theme=None)
                st.html('<div class="hint">Оценки ответивших: 1 — совсем не доволен, 5 — очень доволен.</div>')
        st.write("")
        with st.expander("Все ответы опроса"):
            answers_table(surveys)
    st.write("")
    with st.container(key="card_rose_model"):
        model_block(versions)
