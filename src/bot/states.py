from aiogram.fsm.state import State, StatesGroup


class UserStatsState(StatesGroup):
    set_nick = State()


class MassForm(StatesGroup):
    gather_nicks = State()


class IPAnalytics(StatesGroup):
    gather_ips = State()
