from tortoise import fields
from tortoise.models import Model

from src.core import enums


class Cluster(Model):
    """Кластеры чатов. Было сказано, что нужен один глобальный, но таблица оставлена для гибкости."""

    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=64, unique=True)
    slug = fields.CharField(max_length=64, null=True, db_index=True)
    is_global = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)

    chats: "fields.ReverseRelation[Chat]"

    class Meta:
        table = "clusters"


class Chat(Model):
    """Информация о чатах."""

    id = fields.IntField(primary_key=True)
    tg_chat_id = fields.BigIntField(unique=True)
    title = fields.CharField(max_length=255, null=True)
    username = fields.CharField(max_length=64, null=True)
    chat_type = fields.CharField(max_length=32, null=True)
    cluster = fields.ForeignKeyField(
        "models.Cluster", related_name="chats", null=True, on_delete=fields.CASCADE
    )
    is_active = fields.BooleanField(default=True)
    infinite_invite_link = fields.CharField(max_length=64, null=True)
    settings = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    roles: "fields.ReverseRelation[UserRole]"
    pins: "fields.ReverseRelation[MessagePin]"

    class Meta:
        table = "chats"
        indexes = [("cluster_id",)]


class User(Model):
    """Пользователи Telegram."""

    id = fields.IntField(primary_key=True)
    tg_user_id = fields.BigIntField(unique=True)
    username = fields.CharField(max_length=64, null=True, db_index=True)
    first_name = fields.CharField(max_length=128, null=True)
    last_name = fields.CharField(max_length=128, null=True)
    is_bot = fields.BooleanField(default=False)
    is_owner = fields.BooleanField(default=False)
    banned_until = fields.DatetimeField(null=True)
    meta = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    last_seen = fields.DatetimeField(null=True)

    roles: "fields.ReverseRelation[UserRole]"
    nicks: "fields.ReverseRelation[Nick]"

    class Meta:
        table = "users"


class UserRole(Model):
    """Присвоение роли пользователю в контексте чатов."""

    id = fields.IntField(primary_key=True)
    user = fields.ForeignKeyField(
        "models.User", related_name="roles", on_delete=fields.CASCADE
    )
    chat = fields.ForeignKeyField(
        "models.Chat", related_name="user_roles", on_delete=fields.CASCADE
    )
    level = fields.CharEnumField(enums.Role, default=enums.Role.user)
    assigned_by = fields.ForeignKeyField(
        "models.User",
        related_name="assigned_roles",
        null=True,
        on_delete=fields.SET_NULL,
    )
    assigned_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "user_roles"
        indexes = [("user_id", "chat_id")]
        unique_together = (("user_id", "chat_id"),)


class Nick(Model):
    """Внутренние ники пользователей в чатах."""

    id = fields.IntField(primary_key=True)
    user = fields.ForeignKeyField(
        "models.User", related_name="nicks", on_delete=fields.CASCADE
    )
    chat = fields.ForeignKeyField(
        "models.Chat", related_name="nicks", on_delete=fields.CASCADE
    )
    nick = fields.CharField(max_length=128)
    created_by = fields.ForeignKeyField(
        "models.User",
        related_name="created_nicks",
        null=True,
        on_delete=fields.SET_NULL,
    )
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "nicks"
        unique_together = (("user_id", "chat_id"),)


class InviteLink(Model):
    """Одноразовые и временные пригласительные ссылки."""

    id = fields.IntField(primary_key=True)
    token = fields.CharField(max_length=128, unique=True, db_index=True)
    chat = fields.ForeignKeyField(
        "models.Chat", related_name="invite_links", on_delete=fields.CASCADE
    )
    creator = fields.ForeignKeyField(
        "models.User",
        related_name="created_invites",
        null=True,
        on_delete=fields.SET_NULL,
    )
    max_uses = fields.IntField(default=1)
    used_count = fields.IntField(default=0)
    expires_at = fields.DatetimeField(null=True)
    single_use = fields.BooleanField(default=True)
    is_active = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "invite_links"
        indexes = [("chat_id",)]


class InviteUsage(Model):
    """Лог использования пригласительных ссылок."""

    id = fields.IntField(primary_key=True)
    invite = fields.ForeignKeyField(
        "models.InviteLink", related_name="usages", on_delete=fields.CASCADE
    )
    user = fields.ForeignKeyField(
        "models.User",
        related_name="invite_usages",
        null=True,
        on_delete=fields.SET_NULL,
    )
    used_at = fields.DatetimeField(auto_now_add=True)
    meta = fields.JSONField(null=True)

    class Meta:
        table = "invite_usages"
        indexes = [("invite_id",)]


class Mute(Model):
    """Запись о муте пользователя в чате."""

    id = fields.IntField(primary_key=True)
    user = fields.ForeignKeyField(
        "models.User", related_name="mutes", on_delete=fields.CASCADE
    )
    chat = fields.ForeignKeyField(
        "models.Chat", related_name="mutes", on_delete=fields.CASCADE
    )
    start_at = fields.DatetimeField(auto_now_add=True)
    end_at = fields.DatetimeField(null=True)
    reason = fields.TextField(null=True)
    created_by = fields.ForeignKeyField(
        "models.User",
        related_name="created_mutes",
        null=True,
        on_delete=fields.SET_NULL,
    )
    active = fields.BooleanField(default=True)
    auto_unmute = fields.BooleanField(default=True)

    class Meta:
        table = "mutes"
        indexes = [("user_id", "chat_id"), ("active",)]


class GlobalBan(Model):
    """Глобальные баны в контексте кластера или глобально (cluster nullable -> глобально по всем)."""

    id = fields.IntField(primary_key=True)
    user = fields.ForeignKeyField(
        "models.User", related_name="global_bans", on_delete=fields.CASCADE
    )
    cluster = fields.ForeignKeyField(
        "models.Cluster",
        related_name="global_bans",
        null=True,
        on_delete=fields.CASCADE,
    )
    reason = fields.TextField(null=True)
    created_by = fields.ForeignKeyField(
        "models.User",
        related_name="created_global_bans",
        null=True,
        on_delete=fields.SET_NULL,
    )
    created_at = fields.DatetimeField(auto_now_add=True)
    active = fields.BooleanField(default=True)
    lifted_by = fields.ForeignKeyField(
        "models.User",
        related_name="lifted_global_bans",
        null=True,
        on_delete=fields.SET_NULL,
    )
    lifted_at = fields.DatetimeField(null=True)

    class Meta:
        table = "global_bans"
        indexes = [("user_id", "cluster_id"), ("active",)]


class WelcomeMessage(Model):
    """Приветственное сообщение для кластера."""

    id = fields.IntField(primary_key=True)
    cluster = fields.ForeignKeyField(
        "models.Cluster",
        related_name="welcome_message",
        null=True,
        on_delete=fields.CASCADE,
    )
    text = fields.TextField()
    created_by = fields.ForeignKeyField(
        "models.User",
        related_name="created_welcomes",
        null=True,
        on_delete=fields.SET_NULL,
    )
    created_at = fields.DatetimeField(auto_now_add=True)
    is_default = fields.BooleanField(default=False)

    class Meta:
        table = "welcome_messages"
        unique_together = (("cluster_id",),)


class MessagePin(Model):
    """Закреплённые сообщения."""

    id = fields.IntField(primary_key=True)
    chat = fields.ForeignKeyField(
        "models.Chat", related_name="pins", on_delete=fields.CASCADE
    )
    message_id = fields.BigIntField()
    pinned_by = fields.ForeignKeyField(
        "models.User", related_name="pins_created", null=True, on_delete=fields.SET_NULL
    )
    pinned_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "message_pins"
        unique_together = (("chat_id", "message_id"),)


class NewsBroadcast(Model):
    """Логи рассылок по кластерам."""

    id = fields.IntField(primary_key=True)
    cluster = fields.ForeignKeyField(
        "models.Cluster",
        related_name="news_broadcasts",
        null=True,
        on_delete=fields.CASCADE,
    )
    actor = fields.ForeignKeyField(
        "models.User", related_name="news_actions", null=True, on_delete=fields.SET_NULL
    )
    content = fields.TextField()
    sent_count = fields.IntField(default=0)
    success_count = fields.IntField(default=0)
    failed_count = fields.IntField(default=0)
    meta = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "news_broadcasts"
        indexes = [("cluster_id",)]


class LogEntry(Model):
    """Унифицированный лог для действий(в т.ч. команд)."""

    id = fields.IntField(primary_key=True)
    cluster = fields.ForeignKeyField(
        "models.Cluster", related_name="logs", null=True, on_delete=fields.CASCADE
    )
    chat = fields.ForeignKeyField(
        "models.Chat", related_name="logs", null=True, on_delete=fields.CASCADE
    )
    action = fields.CharField(max_length=64, description="Например: GBAN, GKICK, MUTE")
    target_user = fields.ForeignKeyField(
        "models.User", related_name="target_logs", null=True, on_delete=fields.SET_NULL
    )
    actor_user = fields.ForeignKeyField(
        "models.User", related_name="actor_logs", null=True, on_delete=fields.SET_NULL
    )
    reason = fields.TextField(null=True)
    meta = fields.JSONField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "log_entries"
        indexes = [("created_at",), ("cluster_id",)]


class ChatSetting(Model):
    id = fields.IntField(primary_key=True)
    chat = fields.ForeignKeyField(
        "models.Chat", related_name="settings_rows", on_delete=fields.CASCADE
    )
    key = fields.CharField(max_length=128)
    value = fields.JSONField(null=True)

    class Meta:
        table = "chat_settings"
        unique_together = (("chat_id", "key"),)


class ClusterSetting(Model):
    id = fields.IntField(primary_key=True)
    cluster = fields.ForeignKeyField(
        "models.Cluster", related_name="settings_rows", on_delete=fields.CASCADE
    )
    key = fields.CharField(max_length=128)
    value = fields.JSONField(null=True)

    class Meta:
        table = "cluster_settings"
        unique_together = (("cluster_id", "key"),)


class WordFilter(Model):
    """Фильтр запрещённых слов в чатах."""

    id = fields.IntField(primary_key=True)
    chat = fields.ForeignKeyField(
        "models.Chat", related_name="word_filters", on_delete=fields.CASCADE
    )
    word = fields.CharField(max_length=255)
    added_by = fields.ForeignKeyField(
        "models.User",
        related_name="added_word_filters",
        null=True,
        on_delete=fields.SET_NULL,
    )
    added_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "word_filters"
        unique_together = (("chat_id", "word"),)
        indexes = [("chat_id",)]


class MessageLog(Model):
    """Лог всех сообщений для корректного удаления в топиках."""

    id = fields.IntField(primary_key=True)
    chat = fields.ForeignKeyField(
        "models.Chat", related_name="message_logs", on_delete=fields.CASCADE
    )
    message_id = fields.BigIntField()
    message_thread_id = fields.BigIntField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "message_logs"
        indexes = [("chat_id", "message_thread_id", "created_at")]


async def init():
    await Cluster.get_or_create(name="GLOBAL", defaults={"is_global": True})
