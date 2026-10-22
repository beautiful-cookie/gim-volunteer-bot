"""Проверка цитат: действительно ли фраза, которую привела модель, есть в ответах кандидата."""
import re


def normalize(s):
    """Нижний регистр, ё → е, без кавычек и знаков препинания, одиночные пробелы."""
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[«»\"'“”„()\[\].,;:!?—–-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def quote_found(quote, text):
    """Цитата считается найденной, если каждый её кусок (куски разделены «...») есть в тексте.

    text должен быть уже нормализован (normalize).
    Модель иногда слегка меняет слова: «участвовал в хакатонах» вместо «участвовал в хакатоне».
    Поэтому кусок засчитывается и тогда, когда 80 % его слов встречаются в тексте
    (слова сравниваем по первым 5 буквам, чтобы окончания не мешали).
    """
    pieces = [p for p in (normalize(x) for x in re.split(r"\.\.\.|…", quote)) if p]
    if not pieces:
        return False
    text_stems = {word[:5] for word in text.split()}
    for piece in pieces:
        if piece in text:
            continue
        words = piece.split()
        found = sum(1 for word in words if word[:5] in text_stems)
        if found < 0.8 * len(words):
            return False
    return True
