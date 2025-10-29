from pyrogram.client import Client

from src.core.config import settings
from src.core.managers.chat_setting import ChatSettingManager
from src.core.managers.chats import ChatManager
from src.core.managers.cluster_setting import ClusterSettingManager
from src.core.managers.clusters import ClusterManager
from src.core.managers.global_ban import GlobalBanManager
from src.core.managers.invite_links import InviteLinkManager
from src.core.managers.invite_usage import InviteUsageManager
from src.core.managers.log_entry import LogEntryManager
from src.core.managers.message_logs import MessageLogManager
from src.core.managers.message_pins import MessagePinManager
from src.core.managers.mute import MuteManager
from src.core.managers.news_broadcast import NewsBroadcastManager
from src.core.managers.nicks import NickManager
from src.core.managers.reaction_watch import ReactionWatchManager
from src.core.managers.user_roles import UserRoleManager
from src.core.managers.users import UserManager
from src.core.managers.welcome_messages import WelcomeMessageManager
from src.core.managers.word_filter import WordFilterManager

to_init = [
    chat_settings := ChatSettingManager(),
    chats := ChatManager(),
    cluster_settings := ClusterSettingManager(),
    clusters := ClusterManager(),
    global_bans := GlobalBanManager(),
    invite_links := InviteLinkManager(),
    invite_usage := InviteUsageManager(),
    log_entries := LogEntryManager(),
    message_logs := MessageLogManager(),
    message_pins := MessagePinManager(),
    mutes := MuteManager(),
    news_broadcasts := NewsBroadcastManager(),
    nicks := NickManager(),
    reaction_watches := ReactionWatchManager(),
    user_roles := UserRoleManager(),
    users := UserManager(),
    welcome_messages := WelcomeMessageManager(),
    word_filters := WordFilterManager(),
]
pyrogram_client = Client(
    "bot", api_id=settings.API_ID, api_hash=settings.API_HASH, bot_token=settings.TOKEN
)


async def initialize():
    await pyrogram_client.start()
    for manager in to_init:
        await manager.initialize()


async def close():
    for manager in to_init:
        await manager.sync()
        await manager.close()
    await pyrogram_client.stop()
