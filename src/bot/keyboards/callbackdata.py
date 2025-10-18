from typing import Optional
from aiogram.filters.callback_data import CallbackData


class ChatsPaginate(CallbackData, prefix="chats"):
    initiator_id: int = 0
    page: int


class ChatSelect(CallbackData, prefix="chat"):
    initiator_id: int = 0
    chat_id: int


class GenerateInvite(CallbackData, prefix="gen_inv"):
    initiator_id: int = 0
    chat_id: int


class NickListPaginate(CallbackData, prefix="nlist"):
    initiator_id: int = 0
    chat_id: int
    page: int
    no_nick_mode: bool


class MuteAction(CallbackData, prefix="mute"):
    initiator_id: int = 0
    user_id: int
    duration: str


class UnmuteAction(CallbackData, prefix="unmute"):
    initiator_id: int = 0
    user_id: int


class GByNickPaginate(CallbackData, prefix="gbynick"):
    initiator_id: int = 0
    chat_id: int
    nick: str
    page: int


class Activate(CallbackData, prefix="activate"):
    initiator_id: int = 0


class UserStats(CallbackData, prefix="userstats"):
    initiator_id: int = 0
    user_id: int
    button: str
    access_key: Optional[str] = None


class Form(CallbackData, prefix="form"):
    initiator_id: int = 0
    accept: bool
