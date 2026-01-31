from enum import Enum
from functools import total_ordering


@total_ordering
class Role(str, Enum):
    user = "Пользователь"
    moderator = "Модератор"
    senior_moderator = "Старший Модератор"
    admin = "Администратор"

    @property
    def level(self) -> int:
        return self.__class__._member_names_.index(self.name)

    @classmethod
    def from_level(cls, level: int) -> "Role":
        try:
            return cls[cls._member_names_[level]]
        except (IndexError, TypeError):
            raise ValueError(f"Invalid role level: {level}")

    def __eq__(self, other):
        if isinstance(other, int):
            return self.level == other
        if not isinstance(other, Role):
            return NotImplemented
        return self.level == other.level

    def __lt__(self, other):
        if isinstance(other, int):
            return self.level < other
        if not isinstance(other, Role):
            return NotImplemented
        return self.level < other.level
