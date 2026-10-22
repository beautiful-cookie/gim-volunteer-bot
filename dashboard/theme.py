"""Оформление дашборда: цвета ГИМ, понятные подписи, стили карточек и графиков.

Цвета взяты из презентации ГИМ, стиль карточек — пастельные блоки со скруглёнными углами.
Палитры графиков проверены на различимость (в том числе для людей с нарушениями цветового зрения).

Адаптивность — «изящная деградация»: дашборд сделан под компьютер, на планшете карточки
переносятся по две в ряд, на телефоне всё идёт в одну колонку и пропадают декоративные элементы.
"""
import html
from urllib.parse import quote

import streamlit as st

# ---------------------------------------------------------------- цвета

WINE = "#4A1A20"        # основной текст и боковая панель
RED = "#891F27"         # фирменный бордовый ГИМ: акценты, один ряд данных на графике
PINK = "#E17980"        # розовый из презентации
SOFT_PINK = "#F6D3D7"   # пастельная карточка
ROSE = "#FBE4E6"        # светлая карточка
BEIGE = "#F1E4D8"       # нейтральная карточка
CREAM = "#FBF4EF"       # фон страницы
SURFACE = "#FFFDFB"     # фон графиков внутри белых карточек
MUTED = "#8A6A6E"       # второстепенный текст
GRID = "#EADBD3"        # линии сетки
AVERAGE = "#CDBFB6"     # «среднее по набору» — приглушённый цвет для сравнения

# Оценка 0–3 — порядковая шкала одного оттенка: чем сильнее анкета, тем темнее.
GRADE_COLORS = {0: "#E8A0A6", 1: "#D36A73", 2: "#A8323F", 3: "#6E1A22"}
GRADE_NAMES = {3: "Сильная", 2: "Хорошая", 1: "Средняя", 0: "Слабая"}

# Сравнение двух-трёх кандидатов: цвета закреплены за порядком выбора.
COMPARE_COLORS = ["#A8323F", "#4F79B8", "#B5862A"]

# Короткие и понятные названия факторов для подписей.
FACTOR_SHORT = {"engagement": "Вовлечённость", "availability": "Свободное время",
                "experience": "Опыт и навыки", "direction_fit": "Подходит направлению",
                "quality": "Качество анкеты"}
FACTOR_HINTS = {
    "engagement": "Почему выбрал ГИМ, чего ждёт, откуда узнал",
    "availability": "Учёба и работа, курс, сколько часов готов уделять, где живёт",
    "experience": "Опыт работы, волонтёрства, профильный факультет",
    "direction_fit": "Подтверждён ли выбор направления опытом или интересами",
    "quality": "Насколько грамотно и полно заполнена анкета",
}

# Сердце из логотипа программы — декоративный элемент карточек.
# Закодировано целиком: символы < и > внутри <style> санитайзер Streamlit считает тегами и выбрасывает стили.
HEART_SVG = "data:image/svg+xml;utf8," + quote(
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'>"
    "<path fill='#891F27' d='M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.7 4.5c2.1 0 3.6 1.2 4.3 2.6"
    ".7-1.4 2.2-2.6 4.3-2.6 3.7 0 5.8 3.9 4.3 7.3C19.5 16.4 12 21 12 21z'/></svg>")


def grade_name(grade):
    if grade is None or grade != grade:   # grade != grade — проверка на NaN
        return "Нет оценки"
    return GRADE_NAMES[int(grade)]


# ---------------------------------------------------------------- CSS

CSS = f"""
<style>
[data-testid="stElementContainer"]:has(.gim-css) {{ display: none; }}

/* Заголовки страницы — шрифтом из презентации ГИМ (в нём только заглавные буквы) */
h1, h2, .gim-title {{
    font-family: "Letopis Display", "Onest", sans-serif !important;
    text-transform: uppercase; letter-spacing: .02em; color: {RED} !important; font-weight: 400 !important;
}}
h1 {{ font-size: 2.6rem !important; line-height: 1.05 !important; }}
h2 {{ font-size: 1.7rem !important; }}
h3 {{ font-weight: 600 !important; font-size: 1.15rem !important; }}
.block-container {{ max-width: 1320px; padding-top: 2.2rem; }}

/* Боковая панель: логотип в светлом круге */
.gim-logo {{ display: block; width: 132px; height: 132px; margin: 0 auto .4rem; border-radius: 50%;
    background: #fff; padding: 6px; }}
.gim-sidebar-title {{ text-align: center; font-family: "Letopis Display", sans-serif; font-size: 1.25rem;
    letter-spacing: .03em; color: #FBEDEE; margin-bottom: 1rem; }}

/* Карточки: st.container(key="card_<цвет>_...") */
[class*="st-key-card_"] {{ border-radius: 28px; padding: 22px 24px 20px; position: relative; overflow: hidden; }}
[class*="st-key-card_pink"] {{ background: {SOFT_PINK}; }}
[class*="st-key-card_rose"] {{ background: {ROSE}; }}
[class*="st-key-card_beige"] {{ background: {BEIGE}; }}
[class*="st-key-card_white"] {{ background: {SURFACE}; border: 1px solid {GRID}; }}
[class*="st-key-card_red"] {{ background: {RED}; color: #FFF5F5; }}
[class*="st-key-card_red"] * {{ color: #FFF5F5; }}
[class*="st-key-card_"]:not([class*="st-key-card_white"])::after {{
    content: ""; position: absolute; right: -26px; top: -26px; width: 96px; height: 96px;
    background: url("{HEART_SVG}") no-repeat center / contain; opacity: .10; pointer-events: none;
    transform: rotate(14deg);
}}
[class*="st-key-card_red"]::after {{ filter: brightness(3); opacity: .14 !important; }}
[class*="st-key-card_"] > * {{ position: relative; z-index: 1; }}

/* Сетки: st.container(key="grid_...") с колонками верхнего уровня (вложенные колонки не трогаем).
   Карточки в одном ряду — одной высоты. */
[class*="st-key-grid_"] > * > [data-testid="stHorizontalBlock"] {{ align-items: stretch; }}
[class*="st-key-grid_"] > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {{ height: 100%; }}
[class*="st-key-grid_"] > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > [data-testid="stVerticalBlock"] > * {{ flex: 1 1 auto; }}
[class*="st-key-grid_"] > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] [class*="st-key-card_"] {{ height: 100%; }}

/* st.container(key="row_..."): колонки всегда в одну линию, даже на телефоне
   (строка рейтинга с кнопкой «Открыть», выбор кандидата со стрелками). */
[class*="st-key-row_"] [data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap !important; }}
[class*="st-key-row_"] [data-testid="stColumn"] {{ min-width: 0 !important; }}
[class*="st-key-row_"] [data-testid="stColumn"]:not(:first-child) {{ flex: 0 0 auto !important; width: auto !important; }}

/* Переключатели (разделы, решение куратора): выбранный вариант — заливкой, как кнопки в референсе */
.st-key-view button {{ padding: .35rem 1.1rem; }}
button[data-variant="segmented_control"][aria-checked="true"] {{ background: {RED} !important; border-color: {RED} !important; }}
button[data-variant="segmented_control"][aria-checked="true"] * {{ color: #FFF5F5 !important; }}

/* Цифры в карточках */
.stat-label {{ font-weight: 600; font-size: 1.02rem; margin-bottom: .3rem; }}
.stat-value {{ font-size: 3.1rem; font-weight: 600; line-height: 1; letter-spacing: -.02em; margin: .2rem 0 .5rem; }}
.stat-value small {{ font-size: 1.3rem; font-weight: 500; opacity: .75; letter-spacing: 0; }}
.stat-note {{ font-size: .9rem; opacity: .85; line-height: 1.35; }}
.meter {{ height: 10px; border-radius: 6px; background: rgba(255,255,255,.28); margin: .7rem 0 .45rem; overflow: hidden; }}
.meter > div {{ height: 100%; border-radius: 6px; background: #FFF5F5; }}

/* Вводный текст под заголовком */
.lead {{ font-size: 1.08rem; line-height: 1.55; color: {WINE}; max-width: 760px; margin: -.4rem 0 1.4rem; }}
.lead b {{ color: {RED}; }}
.hint {{ color: {MUTED}; font-size: .88rem; }}

/* Чипы: оценка, направления, «обратить внимание» */
.chip {{ display: inline-block; padding: .18rem .7rem; margin: 0 .3rem .3rem 0; border-radius: 999px;
    font-size: .82rem; font-weight: 500; background: {SURFACE}; border: 1px solid {GRID}; color: {WINE}; }}
.chip-dark {{ background: {WINE}; border-color: {WINE}; color: #FFF5F5; }}
.chip-warn {{ background: #FFF1DA; border-color: #EBCB8B; color: #6B4A12; }}
.chip-dot {{ display: inline-block; width: .6rem; height: .6rem; border-radius: 50%; margin-right: .35rem; vertical-align: 0; }}

/* Строка рейтинга в обзоре */
.rank-row {{ display: flex; align-items: center; gap: .9rem; padding: .55rem .9rem; margin-bottom: .45rem;
    border-radius: 18px; background: {SURFACE}; border: 1px solid {GRID}; }}
.rank-place {{ width: 2.1rem; height: 2.1rem; border-radius: 50%; background: {SOFT_PINK}; color: {RED};
    display: flex; align-items: center; justify-content: center; font-weight: 600; flex-shrink: 0; }}
.rank-name {{ flex: 1; min-width: 0; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.rank-name span {{ display: block; font-weight: 400; font-size: .82rem; color: {MUTED}; }}
.rank-score {{ font-weight: 600; font-size: 1.15rem; }}

/* Крупная оценка в карточке кандидата */
.hero-score {{ font-size: 4rem; font-weight: 600; line-height: 1; letter-spacing: -.03em; }}
.hero-score small {{ font-size: 1.3rem; font-weight: 500; opacity: .7; }}
.section-note {{ white-space: pre-wrap; line-height: 1.5; }}

/* ---------- Планшет: цифры по две в ряд, графики и списки — в одну колонку ---------- */
@media (max-width: 1100px) {{
    [class*="st-key-grid_"] > * > [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
    [class*="st-key-grid_"] > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
        flex: 1 1 100% !important; min-width: 100% !important; }}
    .st-key-grid_stats > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
        flex: 1 1 calc(50% - 1rem) !important; min-width: calc(50% - 1rem) !important; }}
    h1 {{ font-size: 2.1rem !important; }}
    .stat-value {{ font-size: 2.6rem; }}
}}

/* ---------- Телефон: одна колонка, без декора, компактнее ---------- */
@media (max-width: 640px) {{
    .block-container {{ padding: 3.6rem .9rem 3rem; }}
    .st-key-grid_stats > * > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
        flex: 1 1 100% !important; min-width: 100% !important; }}
    [class*="st-key-card_"] {{ border-radius: 22px; padding: 16px 18px; }}
    [class*="st-key-card_"]::after {{ display: none; }}
    h1 {{ font-size: 1.7rem !important; }}
    .lead {{ font-size: .98rem; }}
    .stat-value {{ font-size: 2.3rem; }}
    .hero-score {{ font-size: 3rem; }}
    .hide-on-phone {{ display: none !important; }}
}}
</style>
"""


def apply_css():
    # Если HTML начинается с <style>, санитайзер в браузере его выбрасывает. Поэтому впереди — пустой маркер,
    # а блок с маркером скрыт первым же правилом CSS, чтобы не занимал места на странице.
    st.html('<span class="gim-css"></span>' + CSS)


# ---------------------------------------------------------------- маленькие HTML-блоки

def esc(text):
    return html.escape(str(text))


def chip(text, kind=""):
    return f'<span class="chip {kind}">{esc(text)}</span>'


def grade_chip(grade):
    color = GRADE_COLORS.get(int(grade), MUTED) if grade == grade and grade is not None else MUTED
    return (f'<span class="chip"><span class="chip-dot" style="background:{color}"></span>'
            f'{esc(grade_name(grade))} анкета</span>')


def stat(label, value, note="", small=""):
    """Карточка-цифра: подпись, крупное число, пояснение мелким текстом."""
    small_html = f" <small>{esc(small)}</small>" if small else ""
    return (f'<div class="stat-label">{esc(label)}</div>'
            f'<div class="stat-value">{esc(value)}{small_html}</div>'
            f'<div class="stat-note">{note}</div>')


def meter(share):
    """Полоса заполнения 0–1 (для карточки «Места»)."""
    width = max(0, min(1, share)) * 100
    return f'<div class="meter"><div style="width:{width:.0f}%"></div></div>'


# ---------------------------------------------------------------- графики

PLOTLY_CONFIG = {"displayModeBar": False, "responsive": True}


def style_figure(figure, height=280):
    """Единый спокойный стиль: прозрачный фон, тонкая сетка, скруглённые концы столбиков."""
    figure.update_layout(
        height=height, margin={"t": 8, "b": 8, "l": 8, "r": 8},
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Onest, sans-serif", "color": WINE, "size": 13},
        hoverlabel={"bgcolor": "#FFFFFF", "bordercolor": GRID, "font": {"color": WINE, "family": "Onest, sans-serif"}},
        legend={"orientation": "h", "y": -0.18, "x": 0, "title": None, "font": {"size": 12}},
        barcornerradius=4, bargap=0.35, showlegend=False,
    )
    # automargin — чтобы подписи категорий («Организационное», «Сильная») не обрезались.
    figure.update_xaxes(gridcolor=GRID, linecolor=GRID, zeroline=False, tickfont={"color": WINE}, title=None,
                        automargin=True, showgrid=False)
    figure.update_yaxes(gridcolor=GRID, linecolor=GRID, zeroline=False, tickfont={"color": WINE}, title=None,
                        automargin=True, ticksuffix="  ")
    return figure
