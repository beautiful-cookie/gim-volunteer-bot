"""Переходы между разделами: из обзора — в список кандидатов с фильтром, из списка — в карточку.

Переходы делаются через колбэки (on_click / on_select): Streamlit вызывает их до перерисовки страницы,
поэтому в них можно менять значения виджетов — раздел, фильтры, выбранного кандидата.
"""
import streamlit as st

OVERVIEW = "Обзор"
CANDIDATES = "Все кандидаты"
CANDIDATE = "Кандидат"
VIEWS = [OVERVIEW, CANDIDATES, CANDIDATE]


def go(view, **values):
    """Открыть раздел и, если нужно, выставить фильтры или кандидата."""
    st.session_state["view"] = view
    for key, value in values.items():
        st.session_state[key] = value


def open_candidate(key):
    go(CANDIDATE, candidate_key=key)


def selected_points(chart_key):
    """Точки, на которые нажали на графике Plotly (пусто, если нажатие сняли)."""
    event = st.session_state.get(chart_key)
    if not event:
        return []
    return event.selection.points
