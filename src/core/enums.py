from enum import Enum


class Role(str, Enum):
    user = "user"
    moderator = "moderator"
    senior_moderator = "senior_moderator"
    admin = "admin"
    
    @property
    def level(self) -> int:
        return {"user": 0, "moderator": 1, "senior_moderator": 2, "admin": 3}[self.value]
    
    def __ge__(self, other) -> bool:
        return self.level >= other.level
