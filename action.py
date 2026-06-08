"""novel_writer 小说创作动作组件。"""

from __future__ import annotations

from typing import Annotated, Any

from src.app.plugin_system.api import service_api
from src.app.plugin_system.base import BaseAction
from src.kernel.logger import get_logger

from .config import NovelWriterConfig
from .schemas import NovelGenerationRequest, NovelRuntimeContext
from .service import NovelGenerationService

logger = get_logger("novel_writer.action")


class WriteNovelAction(BaseAction):
    """根据 Bot 人设与用户要求创作小说并发送合并转发消息。"""

    action_name = "write_novel"
    action_description = (
        "当用户想看 Bot 写小说、写故事、编故事、创作小说、续写剧情、"
        "根据人设和背景写一段文学内容时使用。会根据 Bot 的 actor 人设与背景"
        "生成小说，并打包成合并转发聊天记录发送到当前聊天流。"
    )
    primary_action = False
    associated_types = ["text"]
    dependencies = []

    async def execute(
        self,
        user_request: Annotated[
            str,
            "用户对小说的要求，例如题材、主题、角色、篇幅、风格或剧情方向。",
        ],
    ) -> tuple[bool, str]:
        """执行小说创作并通过 forward_msg 发送。"""

        if not user_request.strip():
            return False, "小说创作要求不能为空"

        logger.info(
            f"开始执行 write_novel: stream={self.chat_stream.stream_id}, "
            f"request_len={len(user_request.strip())}"
        )
        config = self._config()
        result = await self._generate_novel(user_request.strip(), config)
        if not result.ok:
            return False, result.error or "小说生成失败"

        novel = result.body
        if not novel.strip():
            logger.warning(f"小说生成结果为空: stream={self.chat_stream.stream_id}")
            return False, "小说生成结果为空"

        nodes = self._build_forward_nodes(novel, config.writer.max_words_per_message)
        logger.info(f"小说生成完成: chars={len(novel)}, nodes={len(nodes)}")
        service = service_api.get_service("forward_msg:service:forward_msg_protocol")
        if service is None or not hasattr(service, "send_forward_message"):
            logger.warning("forward_msg 服务不可用")
            return await self._handle_forward_failure(
                novel,
                config,
                "forward_msg 服务不可用",
            )

        result = await service.send_forward_message(nodes, self.chat_stream.stream_id)
        ok, message = result if isinstance(result, tuple) else (False, "forward_msg 返回值异常")
        logger.info(f"forward_msg 发送结果: ok={ok}, message={message}")
        if not ok:
            return await self._handle_forward_failure(novel, config, str(message))
        return True, str(message)

    def _config(self) -> NovelWriterConfig:
        """获取插件配置。"""

        if isinstance(self.plugin.config, NovelWriterConfig):
            return self.plugin.config
        return NovelWriterConfig()

    async def _generate_novel(
        self,
        user_request: str,
        config: NovelWriterConfig,
    ):
        """调用框架 LLM API 生成小说正文。"""

        service = self._generation_service()
        return await service.generate_standalone(
            NovelGenerationRequest(
                user_request=user_request,
                runtime_context=self._runtime_context(),
                request_name="novel_writer.write_novel",
            )
        )

    def _get_model_set(self, config: NovelWriterConfig):
        """按配置获取模型集，并应用生成参数。"""

        return self._generation_service()._get_model_set(config)

    def _build_prompt(self, user_request: str, config: NovelWriterConfig) -> str:
        """构建小说生成提示词。"""

        return self._generation_service().build_prompt(
            user_request,
            config,
            self._runtime_context(),
        )

    def _build_persona_from_core_config(self) -> tuple[str, str]:
        """通过框架配置入口获取 Bot 人设与背景。"""

        return self._generation_service().build_persona(self._runtime_context())

    def _runtime_context(self) -> NovelRuntimeContext:
        """构建生成服务所需的运行时上下文。"""

        return NovelRuntimeContext(
            bot_nickname=self.chat_stream.bot_nickname or "",
            stream_name=self.chat_stream.stream_name or "",
            recent_content=self._get_recent_chat_content(max_messages=6),
        )

    def _build_runtime_persona_hint(self) -> str:
        """构建运行时可从 ChatStream 获取的人设辅助信息。"""

        lines = []
        if self.chat_stream.bot_nickname:
            lines.append(f"当前 Bot 昵称：{self.chat_stream.bot_nickname}")
        if self.chat_stream.stream_name:
            lines.append(f"当前聊天流名称：{self.chat_stream.stream_name}")
        recent_content = self._get_recent_chat_content(max_messages=6)
        if recent_content:
            lines.append(f"最近聊天上下文：\n{recent_content}")
        return "\n".join(lines)

    async def _handle_forward_failure(
        self,
        novel: str,
        config: NovelWriterConfig,
        reason: str,
    ) -> tuple[bool, str]:
        """处理合并转发失败后的直发兜底。"""

        if not config.writer.fallback_to_direct_send:
            return False, reason

        chunks = self._split_text(novel, config.writer.max_words_per_message)
        warning = (
            "forward_msg 依赖不可用或发送失败，已改为直接发送小说正文；"
            "小说内容过多时可能导致刷屏。"
        )
        if not await self._send_to_stream(warning):
            return False, f"{reason}；直发提醒发送失败"

        sent_count = 0
        for chunk in chunks:
            if await self._send_to_stream(chunk):
                sent_count += 1
        if sent_count != len(chunks):
            return False, f"{reason}；直发完成 {sent_count}/{len(chunks)} 条"
        return True, f"{reason}；已直发小说正文 {sent_count} 条"

    def _build_forward_nodes(
        self,
        novel: str,
        max_words_per_message: int,
    ) -> list[dict[str, Any]]:
        """将小说正文拆分为 OneBot 合并转发节点。"""

        chunks = self._split_text(novel, max_words_per_message)
        user_id = self.chat_stream.bot_id or "0"
        nickname = self.chat_stream.bot_nickname or "Bot"
        return [
            {
                "type": "node",
                "data": {
                    "user_id": user_id,
                    "nickname": nickname,
                    "message_seq": 0,
                    "content": [{"type": "text", "data": {"text": chunk}}],
                },
            }
            for chunk in chunks
        ]

    def _split_text(self, text: str, max_words_per_message: int) -> list[str]:
        """按配置上限拆分文本，优先在自然段之间切分。"""

        return self._generation_service().split_text(text, max_words_per_message)

    def _generation_service(self) -> NovelGenerationService:
        """创建绑定当前插件实例的生成服务。"""

        return NovelGenerationService(self.plugin)
