import xml.etree.ElementTree as ET
from typing import List

from models import Exercise


def load_exercises(path: str) -> List[Exercise]:
    """
    Читает XML и возвращает список упражнений.

    Структура XML:
    <exercises>
      <exercise lesson="0" number="1" errors="0" type="0">
        <text>...</text>
        <text2>...</text2>   <!-- необязательно -->
      </exercise>
    </exercises>
    """
    tree = ET.parse(path)
    root = tree.getroot()

    if root.tag != "exercises":
        raise ValueError("Ожидался корневой тег <exercises>")

    exercises: List[Exercise] = []

    for ex_elem in root.findall("exercise"):
        lesson = int(ex_elem.get("lesson", "0"))
        number = int(ex_elem.get("number", "0"))
        errors_allowed = int(ex_elem.get("errors", "0"))
        type_ = int(ex_elem.get("type", "1"))
        speed = int(ex_elem.get("speed", "0"))
        difficulty = int(ex_elem.get("difficulty", "0"))
        lowspeed = int(ex_elem.get("lowspeed", "0"))
        highspeed = int(ex_elem.get("highspeed", "0"))

        text_elem = ex_elem.find("text")
        text2_elem = ex_elem.find("text2")

        text = ""
        if text_elem is not None and text_elem.text:
            text = text_elem.text.strip()

        # В упражнениях type=5 и type=7 в <text> лежит намеренно
        # искажённый текст, а в <text2> — правильный/целевой.
        if type_ in (5, 7) and text2_elem is not None and text2_elem.text:
            text2 = text2_elem.text.strip()
            if text2:
                text = text2

        title = f"Урок {lesson}.{number}" if lesson != 0 else f"Разминка {number}"

        exercises.append(
            Exercise(
                lesson=lesson,
                number=number,
                title=title,
                text=text,
                errors_allowed=errors_allowed,
                type=type_,
                speed=speed,
                difficulty=difficulty,
                lowspeed=lowspeed,
                highspeed=highspeed,
            )
        )

    exercises.sort(key=lambda e: (e.lesson, e.number))
    return exercises