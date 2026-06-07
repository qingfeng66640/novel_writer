"""novel_writer 小说创作动作组件。"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from src.app.plugin_system.api import llm_api, service_api
from src.app.plugin_system.base import BaseAction
from src.app.plugin_system.types import LLMPayload, ROLE, SystemReminderBucket, Text
from src.core.config import get_core_config
from src.kernel.logger import get_logger

from .config import NovelWriterConfig

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
    dependencies = ["forward_msg:service:forward_msg_protocol"]

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
        try:
            novel = await self._generate_novel(user_request.strip(), config)
        except asyncio.TimeoutError:
            logger.warning(f"小说生成超时: stream={self.chat_stream.stream_id}")
            return False, "小说生成超时，请稍后重试"
        except Exception as exc:
            logger.error(f"小说生成失败: {exc}", exc_info=True)
            return False, f"小说生成失败：{exc}"

        if not novel.strip():
            logger.warning(f"小说生成结果为空: stream={self.chat_stream.stream_id}")
            return False, "小说生成结果为空"

        nodes = self._build_forward_nodes(novel, config.writer.max_words_per_message)
        logger.info(f"小说生成完成: chars={len(novel)}, nodes={len(nodes)}")
        service = service_api.get_service("forward_msg:service:forward_msg_protocol")
        if service is None or not hasattr(service, "send_forward_message"):
            logger.warning("forward_msg 服务不可用")
            return False, "forward_msg 服务不可用"

        result = await service.send_forward_message(nodes, self.chat_stream.stream_id)
        ok, message = result if isinstance(result, tuple) else (False, "forward_msg 返回值异常")
        logger.info(f"forward_msg 发送结果: ok={ok}, message={message}")
        return bool(ok), str(message)

    def _config(self) -> NovelWriterConfig:
        """获取插件配置。"""

        if isinstance(self.plugin.config, NovelWriterConfig):
            return self.plugin.config
        return NovelWriterConfig()

    async def _generate_novel(
        self,
        user_request: str,
        config: NovelWriterConfig,
    ) -> str:
        """调用框架 LLM API 生成小说正文。"""

        model_set = self._get_model_set(config)
        request = llm_api.create_llm_request(
            model_set,
            request_name="novel_writer.write_novel",
            with_reminder=SystemReminderBucket.ACTOR,
        )
        prompt = self._build_prompt(user_request, config)
        logger.debug(
            f"发送小说生成 LLM 请求: model_count={len(model_set)}, "
            f"prompt_len={len(prompt)}, max_tokens={config.writer.max_tokens}"
        )
        request.add_payload(LLMPayload(ROLE.USER, [Text(prompt)]))
        response = await asyncio.wait_for(request.send(stream=False), timeout=120.0)
        novel = str(await response).strip()
        logger.debug(f"小说生成 LLM 响应完成: chars={len(novel)}")
        return novel

    def _get_model_set(self, config: NovelWriterConfig):
        """按配置获取模型集，并应用生成参数。"""

        temperature = config.writer.temperature
        max_tokens = config.writer.max_tokens
        model_name = config.writer.model_name.strip()
        if model_name:
            return llm_api.get_model_set_by_name(
                model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        model_set = llm_api.get_model_set_by_task("actor")
        return [
            {
                **entry,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            for entry in model_set
        ]

    def _build_prompt(self, user_request: str, config: NovelWriterConfig) -> str:
        """构建小说生成提示词。"""

        bot_persona, background_story = self._build_persona_from_core_config()
        background_prompt = config.writer.background_prompt_template.format(
            background_story=background_story,
        )
        return config.writer.novel_prompt_template.format(
            bot_persona=bot_persona,
            background_prompt=background_prompt,
            background_story=background_story,
            user_request=user_request,
            min_words=config.writer.min_words,
            min_paragraphs=config.writer.min_paragraphs,
        )

    def _build_persona_from_core_config(self) -> tuple[str, str]:
        """通过框架配置入口获取 Bot 人设与背景。"""

        personality = get_core_config().personality
        alias_names = "、".join(personality.alias_names) or "无"
        safety_guidelines = "\n".join(
            f"- {item}" for item in personality.safety_guidelines
        )
        negative_behaviors = "\n".join(
            f"- {item}" for item in personality.negative_behaviors
        )
        lines = [
            f"昵称：{personality.nickname}",
            f"别名：{alias_names}",
            f"身份：{personality.identity}",
            f"核心人格：{personality.personality_core}",
            f"人格侧面：{personality.personality_side}",
            f"表达风格：{personality.reply_style}",
            f"安全准则：\n{safety_guidelines}",
            f"禁止行为：\n{negative_behaviors}",
        ]
        runtime_hint = self._build_runtime_persona_hint()
        if runtime_hint:
            lines.append(runtime_hint)
        return "\n".join(lines), personality.background_story

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

        limit = max(1, max_words_per_message)
        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs or [text.strip()]:
            if len(paragraph) > limit:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(
                    paragraph[index : index + limit]
                    for index in range(0, len(paragraph), limit)
                )
                continue
            candidate = paragraph if not current else f"{current}\n\n{paragraph}"
            if len(candidate) <= limit:
                current = candidate
            else:
                chunks.append(current)
                current = paragraph
        if current:
            chunks.append(current)
        return chunks or [text.strip()]
