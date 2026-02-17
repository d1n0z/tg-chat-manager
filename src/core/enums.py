from enum import Enum


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
