"""Дашборд кураторов волонтёрской программы ГИМ.

Запуск из корня проекта (там лежит .streamlit/config.toml с цветами ГИМ):
    streamlit run dashboard/app.py

Три раздела, от общего к частному:
    «Обзор»          — вся картина набора простыми словами и главные цифры (dashboard/overview.py);
    «Все кандидаты»  — рейтинг с фильтрами и сравнение нескольких кандидатов (dashboard/candidates.py);
    «Кандидат»       — один человек подробно и решение куратора (dashboard/candidate.py);
    «Волонтёры»      — опрос через четыре месяца и как модель учится на его ответах (dashboard/volunteers.py).
Слева — выбор набора, число свободных мест, важность факторов (1–5) и выгрузка в Excel.
Если в .env задан DASHBOARD_PASSWORD, дашборд сначала спросит пароль.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from bot.storage import Storage  # noqa: E402
from dashboard import candidate, candidates, overview, theme, volunteers  # noqa: E402
from dashboard.data import (BOT_DB, apply_weights, factor_titles, item_titles, load_bot,  # noqa: E402
                            load_historical, load_model_versions, load_surveys)
from dashboard.export import build_excel  # noqa: E402
from dashboard.navigation import CANDIDATE, CANDIDATES, OVERVIEW, VIEWS, VOLUNTEERS  # noqa: E402
from dashboard.weights import factor_defaults, factors_with_data, item_weights  # noqa: E402
from scorer.llm import load_env  # noqa: E402

BOT_SOURCE = "Текущий набор"
HISTORY_SOURCE = "Наборы 2024–2025"

st.set_page_config(page_title="Отбор волонтёров ГИМ", page_icon="🏛", layout="wide")
theme.apply_css()


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
    return load_bot() if source == BOT_SOURCE else load_historical()


def show_history():
    st.session_state["source"] = HISTORY_SOURCE


def reset_importance():
    for factor, value in factor_defaults().items():
        st.session_state[f"importance_{factor}"] = value


def keep_view():
    """Повторное нажатие на активный раздел снимает выбор — возвращаем его обратно."""
    if not st.session_state.get("view"):
        st.session_state["view"] = OVERVIEW


storage = Storage(BOT_DB)
factors = factor_titles()
items = item_titles()


# ---------------------------------------------------------------- боковая панель

# Ссылка вида http://localhost:8501/?nabor=2024-2025 сразу открывает прошлые наборы — удобно для показа.
if "source" not in st.session_state and st.query_params.get("nabor") == "2024-2025":
    st.session_state["source"] = HISTORY_SOURCE

with st.sidebar:
    st.html('<img class="gim-logo" src="app/static/logo.svg" alt="Волонтёры Исторического музея">')
    source = st.radio("Набор", [BOT_SOURCE, HISTORY_SOURCE], key="source")
    free_places = st.number_input("Свободных мест", min_value=1, max_value=100, value=18,
                                  help="Сколько человек музей готов взять в этот набор.")

    raw = load(source)
    shown_factors = factors_with_data(raw, factors) if not raw.empty else factors

    st.markdown("**Важность факторов**")
    st.caption("1 — слабое влияние на балл, 5 — сильное.")
    for factor, value in factor_defaults().items():
        st.session_state.setdefault(f"importance_{factor}", value)
    # Скрытый фактор (без данных) остаётся с важностью по рубрике.
    importance = dict(factor_defaults())
    for factor in shown_factors:
        importance[factor] = st.slider(theme.FACTOR_SHORT.get(factor, factors[factor]), 1, 5,
                                       key=f"importance_{factor}", help=theme.FACTOR_HINTS.get(factor))
    st.button("Вернуть важность по рубрике музея", on_click=reset_importance, width="stretch")

st.title("Отбор волонтёров")
if raw.empty:
    overview.empty_state(on_show_history=show_history)
    st.stop()

weights = item_weights(importance)
df = apply_weights(raw, weights)
decisions = storage.decisions()
df["decision"] = [decisions.get(key, ("не решено", ""))[0] for key in df["key"]]
df = df.sort_values("index", ascending=False).reset_index(drop=True)
df["place"] = range(1, len(df) + 1)

excel_name = "kandidaty_bot.xlsx" if source == BOT_SOURCE else "kandidaty_2024-2025.xlsx"
excel_bytes = build_excel(df, factors, items, decisions)
st.sidebar.download_button("Скачать Excel", data=excel_bytes, file_name=excel_name, type="primary",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           width="stretch")
st.sidebar.caption("Все кандидаты с баллами, ответами, вопросами к собеседованию и решениями.")


# ---------------------------------------------------------------- разделы

st.session_state.setdefault("view", OVERVIEW)
st.segmented_control("Раздел", VIEWS, key="view", on_change=keep_view, label_visibility="collapsed")
st.write("")

view = st.session_state.get("view") or OVERVIEW
if view == OVERVIEW:
    overview.render(df, shown_factors, free_places)
elif view == CANDIDATES:
    candidates.render(df, shown_factors, free_places, excel_bytes, excel_name)
elif view == CANDIDATE:
    candidate.render(df, shown_factors, items, weights, storage, decisions)
elif view == VOLUNTEERS:
    volunteers.render(load_surveys(), load_model_versions(), BOT_SOURCE)
