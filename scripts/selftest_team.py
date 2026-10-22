"""Самотест сборки команды (dashboard/assign.py): места, график фондов, закрепление, объяснения.

    python scripts/selftest_team.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dashboard.assign import build_team  # noqa: E402


def person(key, index, p, directions, schedule="Гибко", recommended=""):
    return {"key": key, "index": index, "p_success": p, "directions": directions,
            "recommended_direction": recommended, "answers": {"schedule": schedule}}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    people = [
        person("a", 90, 0.8, ["Фондовое", "Медиа"], schedule="Выходные"),   # в фонды нельзя — уйдёт в медиа
        person("b", 70, 0.7, ["Фондовое"], schedule="Будни", recommended="Фондовое"),
        person("c", 85, 0.9, ["Медиа"]),
        person("d", 60, 0.3, ["Медиа"]),
        person("e", 50, 0.5, ["Фондовое"], schedule="Выходные"),            # только фонды и только выходные
        person("f", 40, 0.2, []),                                            # не определился — куда есть место
    ]
    places = {"Организационное": 1, "Проектное": 0, "Фондовое": 1, "Инклюзивное": 0, "Медиа": 2}
    team, left = build_team(people, places)
    keys = {d: [c["key"] for c, _ in members] for d, members in team.items()}
    assert keys["Фондовое"] == ["b"], keys
    assert sorted(keys["Медиа"]) == ["a", "c"], keys
    assert keys["Организационное"] == ["f"], keys
    reasons = {c["key"]: why for c, why in left}
    assert "по будням" in reasons["e"] and "заняты" in reasons["d"], reasons
    assert "нейросеть советует" in team["Фондовое"][0][1]

    # Куратор закрепил d за медиа — d попадает, кто-то из сильных уступает место.
    team, left = build_team(people, places, pinned={"d": "Медиа"})
    media = [c["key"] for c, _ in team["Медиа"]]
    assert "d" in media and len(media) == 2, media
    assert any(why == "закреплён(а) куратором" for _, why in team["Медиа"])
    print("Самотест сборки команды пройден.")


if __name__ == "__main__":
    main()
