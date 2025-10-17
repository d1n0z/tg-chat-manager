from aiogram.filters.callback_data import CallbackData


class ChatsPaginate(CallbackData, prefix="chats"):
    page: int


class ChatSelect(CallbackData, prefix="chat"):
    chat_id: int


class GenerateInvite(CallbackData, prefix="gen_inv"):
    chat_id: int


class NickListPaginate(CallbackData, prefix="nlist"):
    chat_id: int
    page: int


class MuteAction(CallbackData, prefix="mute"):
    user_id: int
    duration: str


class UnmuteAction(CallbackData, prefix="unmute"):
    user_id: int
