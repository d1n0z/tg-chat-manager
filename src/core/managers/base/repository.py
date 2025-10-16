import asyncio
from abc import ABC


class BaseRepository(ABC):
    def __init__(self, lock: asyncio.Lock):
        self._lock = lock
