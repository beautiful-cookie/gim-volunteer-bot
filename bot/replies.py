"""Ответ бота и кнопка — общие для анкеты (bot/engine.py) и опроса волонтёров (bot/survey.py)."""
from dataclasses import dataclass, field


@dataclass
class Button:
    label: str
    payload: dict
    color: str = "secondary"   # primary, secondary, positive, negative


@dataclass
class Reply:
    text: str
    buttons: list = field(default_factory=list)   # список рядов, ряд — список кнопок
