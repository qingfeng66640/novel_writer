"""novel_writer 命令组件。"""

from __future__ import annotations

import asyncio

from src.app.plugin_system.api import send_api
from src.app.plugin_system.base import BaseCommand
from src.app.plugin_system.types import PermissionLevel
from src.core.models.message import Message
from src.core.models.stream import ChatStream
from src.kernel.concurrency import get_task_manager
from src.kernel.logger import get_logger

from .action import WriteNovelAction

logger = get_logger("novel_writer.command")


class NovelCommand(BaseCommand):
    """通过管理员命令直接触发一次简短小说创作。"""

    command_name = "novel"
    command_description = "管理员直接触发 novel_writer 生成一篇简短小说"
    permission_level = PermissionLevel.OPERATOR
    dependencies = []

    async def execute(self, message_text: str) -> tuple[bool, str]:
        """执行 /novel 命令并后台复用 write_novel Action。"""

        stripped = message_text.strip()
        if stripped.startswith(self.command_prefix):
            return False, "命令文本格式错误：只接受去掉前缀后的小说要求"
        if stripped.startswith(self.command_name):
            return False, "命令文本格式错误：只接受去掉 command_name 后的小说要求"

        user_request = stripped or "请写一篇简短的小说。"
        action_request = f"请写一篇简短的小说。用户要求：{user_request}"
        await self._send_feedback("小说生成已开始，请稍等。")
        get_task_manager().create_task(
            self._run_generation(action_request),
            name="novel_writer_command_generation",
            daemon=True,
        )
        return True, "小说生成已开始，请稍等。"

    async def _run_generation(self, action_request: str) -> None:
        """后台执行小说生成，避免命令事件处理器超时取消。"""

        action = WriteNovelAction(self._chat_stream(), self.plugin)
        try:
            ok, message = await action.execute(action_request)
        except asyncio.CancelledError:
            await self._send_feedback("小说生成已中断。")
            raise
        except Exception as exc:
            logger.error(f"/novel 后台生成异常: {exc}", exc_info=True)
            await self._send_feedback(f"小说生成失败：{exc}")
            return
        if not ok:
            await self._send_feedback(f"小说生成失败：{message}")

    async def _send_feedback(self, content: str) -> bool:
        """向触发命令的聊天流发送命令执行反馈。"""

        message = self._message or Message(stream_id=self.stream_id)
        return await send_api.send_text(
            content,
            self.stream_id,
            platform=message.platform or None,
            reply_to=self.message_id or None,
        )

    def _chat_stream(self) -> ChatStream:
        """根据命令消息构造 Action 所需的 ChatStream。"""

        message = self._message or Message(stream_id=self.stream_id)
        stream = ChatStream(
            stream_id=self.stream_id,
            platform=message.platform,
            chat_type=message.chat_type or "private",
            stream_name=message.sender_cardname or message.sender_name or "",
        )
        stream.context.current_message = message
        stream.context.add_history_message(message)
        return stream
