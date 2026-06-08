"""novel_writer 可复用小说生成服务。"""

from __future__ import annotations

import asyncio
from typing import Any

from src.app.plugin_system.api import llm_api
from src.app.plugin_system.base import BaseService
from src.app.plugin_system.types import LLMPayload, ROLE, SystemReminderBucket, Text
from src.core.config import get_core_config
from src.kernel.logger import get_logger

from .config import NovelWriterConfig
from .prompts import build_managed_chapter_instruction
from .schemas import (
    NovelGenerationRequest,
    NovelGenerationResult,
    NovelRuntimeContext,
    QualityReport,
)

logger = get_logger("novel_writer.service")


class NovelGenerationService(BaseService):
    """供其他插件复用的小说正文生成服务。"""

    service_name = "novel_generation"
    service_description = "根据 Bot 人设、作品上下文和用户要求生成小说正文。"
    version = "1.1.1"

    async def generate_standalone(
        self,
        request: NovelGenerationRequest,
    ) -> NovelGenerationResult:
        """生成独立小说正文。"""

        return await self.generate(request)

    async def generate_chapter(
        self,
        request: NovelGenerationRequest,
    ) -> NovelGenerationResult:
        """生成文章管理场景下的章节正文。"""

        managed_request = NovelGenerationRequest(
            user_request=build_managed_chapter_instruction(
                user_request=request.user_request,
                project_context=request.project_context,
                continuation_context=request.continuation_context,
                chapter_number=request.chapter_number,
                chapter_title=request.chapter_title,
                target_chars=request.target_chars,
            ),
            mode="chapter",
            runtime_context=request.runtime_context,
            request_name=request.request_name or "novel_writer.generate_chapter",
            min_chars=request.min_chars,
            max_chars=request.max_chars,
        )
        return await self.generate(managed_request)

    async def continue_chapter(
        self,
        request: NovelGenerationRequest,
    ) -> NovelGenerationResult:
        """基于已有作品上下文续写章节。"""

        continuation = request.continuation_context or "请自然承接上一章继续推进剧情。"
        return await self.generate_chapter(
            NovelGenerationRequest(
                user_request=request.user_request,
                mode="continue",
                project_context=request.project_context,
                continuation_context=continuation,
                chapter_number=request.chapter_number,
                chapter_title=request.chapter_title,
                target_chars=request.target_chars,
                min_chars=request.min_chars,
                max_chars=request.max_chars,
                runtime_context=request.runtime_context,
                request_name=request.request_name or "novel_writer.continue_chapter",
            )
        )

    async def generate(
        self,
        request: NovelGenerationRequest,
    ) -> NovelGenerationResult:
        """执行一次 LLM 小说生成请求。"""

        user_request = request.user_request.strip()
        if not user_request:
            return NovelGenerationResult(ok=False, error="小说创作要求不能为空")

        config = self._config()
        prompt = self.build_prompt(user_request, config, request.runtime_context)
        max_attempts = self._max_attempts(config, request)
        retry_interval = self._retry_interval(config, request)
        last_error = ""

        for attempt in range(1, max_attempts + 1):
            try:
                body = await self._generate_body_with_timeout(
                    prompt,
                    config,
                    request,
                    self._timeout_seconds(config, request),
                )
            except asyncio.TimeoutError:
                last_error = (
                    f"小说生成超时：第 {attempt}/{max_attempts} 次尝试超过 "
                    f"{self._timeout_seconds(config, request)} 秒"
                )
                logger.warning(last_error)
            except Exception as exc:
                last_error = f"小说生成失败：{exc}"
                logger.error(last_error, exc_info=True)
            else:
                report = self.quality_check(body, request)
                if not body:
                    last_error = "小说生成结果为空"
                elif report.status == "fail":
                    return NovelGenerationResult(
                        ok=False,
                        body=body,
                        error="小说生成结果未通过质量检查",
                        quality_report=report,
                    )
                else:
                    return NovelGenerationResult(ok=True, body=body, quality_report=report)

            if attempt < max_attempts and retry_interval > 0:
                await asyncio.sleep(retry_interval)

        return NovelGenerationResult(ok=False, error=last_error or "小说生成失败")

    async def _generate_body_with_timeout(
        self,
        prompt: str,
        config: NovelWriterConfig,
        request: NovelGenerationRequest,
        timeout_seconds: float,
    ) -> str:
        """在完整超时窗口内发送请求并读取正文。"""

        return await asyncio.wait_for(
            self._generate_body(prompt, config, request),
            timeout=timeout_seconds,
        )

    async def _generate_body(
        self,
        prompt: str,
        config: NovelWriterConfig,
        request: NovelGenerationRequest,
    ) -> str:
        """执行一次不含外层重试的 LLM 调用。"""

        llm_request = llm_api.create_llm_request(
            self._get_model_set(config, request),
            request_name=request.request_name,
            with_reminder=SystemReminderBucket.ACTOR,
        )
        llm_request.add_payload(LLMPayload(ROLE.USER, [Text(prompt)]))
        response = await llm_request.send(stream=False)
        return str(await response).strip()

    def build_prompt(
        self,
        user_request: str,
        config: NovelWriterConfig | None = None,
        runtime_context: NovelRuntimeContext | None = None,
    ) -> str:
        """构建小说生成提示词。"""

        config = config or self._config()
        bot_persona, background_story = self.build_persona(runtime_context)
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

    def build_persona(
        self,
        runtime_context: NovelRuntimeContext | None = None,
    ) -> tuple[str, str]:
        """从 CoreConfig 与运行时上下文构建人设材料。"""

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
        runtime_hint = self._runtime_hint(runtime_context)
        if runtime_hint:
            lines.append(runtime_hint)
        return "\n".join(lines), personality.background_story

    def quality_check(
        self,
        draft: str,
        request: NovelGenerationRequest | None = None,
    ) -> QualityReport:
        """执行确定性的轻量质量检查。"""

        text = draft.strip()
        issues: list[str] = []
        if not text:
            issues.append("empty_body")
        if "作为AI" in text or "作为 AI" in text:
            issues.append("ai_meta_commentary")
        if "【用户要求】" in text or "【Bot 人设】" in text:
            issues.append("prompt_leak")
        if request and request.min_chars and len(text) < request.min_chars:
            issues.append("below_min_chars")
        if request and request.max_chars and len(text) > request.max_chars:
            issues.append("above_max_chars")
        status = "pass" if not issues else "fail"
        return QualityReport(status=status, issues=issues, char_count=len(text))

    def split_text(self, text: str, max_words_per_message: int) -> list[str]:
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

    def _config(self) -> NovelWriterConfig:
        """获取插件配置。"""

        cfg = getattr(self.plugin, "config", None)
        return cfg if isinstance(cfg, NovelWriterConfig) else NovelWriterConfig()

    def _timeout_seconds(
        self,
        config: NovelWriterConfig,
        request: NovelGenerationRequest,
    ) -> float:
        """解析本次生成尝试的完整超时时间。"""

        value = request.timeout_seconds or config.writer.generation_timeout_seconds
        return max(1.0, float(value))

    def _max_attempts(
        self,
        config: NovelWriterConfig,
        request: NovelGenerationRequest,
    ) -> int:
        """解析总尝试次数。"""

        retries = request.max_retries
        if retries is None:
            retries = config.writer.generation_max_retries
        return max(1, int(retries) + 1)

    def _retry_interval(
        self,
        config: NovelWriterConfig,
        request: NovelGenerationRequest,
    ) -> float:
        """解析重试间隔秒数。"""

        value = request.retry_interval_seconds
        if value is None:
            value = config.writer.generation_retry_interval_seconds
        return max(0.0, float(value))

    def _get_model_set(
        self,
        config: NovelWriterConfig,
        request: NovelGenerationRequest | None = None,
    ) -> list[dict[str, Any]]:
        """按配置获取模型集，并应用生成参数。"""

        temperature = config.writer.temperature
        max_tokens = request.max_tokens if request and hasattr(request, "max_tokens") else None
        max_tokens = max_tokens or config.writer.max_tokens
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

    @staticmethod
    def _runtime_hint(runtime_context: NovelRuntimeContext | None) -> str:
        """构建运行时上下文提示。"""

        if runtime_context is None:
            return ""
        lines = []
        if runtime_context.bot_nickname:
            lines.append(f"当前 Bot 昵称：{runtime_context.bot_nickname}")
        if runtime_context.stream_name:
            lines.append(f"当前聊天流名称：{runtime_context.stream_name}")
        if runtime_context.recent_content:
            lines.append(f"最近聊天上下文：\n{runtime_context.recent_content}")
        return "\n".join(lines)
