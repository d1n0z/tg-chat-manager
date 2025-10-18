from enum import Enum


class Role(str, Enum):
    user = "Пользователь"
    moderator = "Модератор"
    senior_moderator = "Старший Модератор"
    admin = "Администратор"
    
    @property
    def level(self) -> int:
        return list(Role).index(self)
    
    def __ge__(self, other) -> bool:
        return self.level >= other.level
