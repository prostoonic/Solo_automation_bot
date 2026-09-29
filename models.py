from dataclasses import dataclass


@dataclass
class Exercise:
    lesson: int
    number: int
    title: str
    text: str
    errors_allowed: int = 0
    type: int = 1
    speed: int = 0
    difficulty: int = 0
    lowspeed: int = 0
    highspeed: int = 0

    @property
    def display_name(self) -> str:
        return f"{self.title} ({len(self.text)} симв.)"


@dataclass
class BotSettings:
    cpm: float
    error_percent: float