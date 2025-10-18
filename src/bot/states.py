from aiogram.fsm.state import StatesGroup, State


class UserStatsState(StatesGroup):
    set_nick = State()
