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


class MuteAction(CallbackData, prefix="mute"):
    initiator_id: int = 0
    user_id: int
    duration: str


class UnmuteAction(CallbackData, prefix="unmute"):
    initiator_id: int = 0
    user_id: int
