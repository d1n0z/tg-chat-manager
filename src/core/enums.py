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
        return list(Role).index(self)

    def __eq__(self, other):
        if isinstance(other, int):
            return self.level == other
        if not isinstance(other, Role):
            return NotImplemented
        return self.level == other.level

    def __lt__(self, other):
        if isinstance(other, int):
            return self.level == other
        if not isinstance(other, Role):
            return NotImplemented
        return self.level < other.level
