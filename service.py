"""novel_writer 可复用小说生成服务。"""

from __future__ import annotations

import asyncio
import re
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


_PARAGRAPH_MARKER = "<paragraph/>"
_PARAGRAPH_MARKER_PATTERN = re.compile(r"\s*<paragraph\s*/>\s*", re.IGNORECASE)
_NUMBERED_PARAGRAPH_PATTERN = re.compile(r"(?m)^[ \t]*(?:\d+|[一二三四五六七八九十百千]+)[\.、．）)][ \t]*")
_SHORT_PARAGRAPH_CHAR_LIMIT = 80
_NATURAL_PARAGRAPH_TARGET_CHARS = 180


class NovelGenerationService(BaseService):
    """供其他插件复用的小说正文生成服务。"""

    service_name = "novel_generation"
    service_description = "根据 Bot 人设、作品上下文和用户要求生成小说正文。"
    version = "1.2.1"

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
            project_context=request.project_context,
            continuation_context=request.continuation_context,
            runtime_context=request.runtime_context,
            request_name=request.request_name or "novel_writer.generate_chapter",
            target_chars=request.target_chars,
            min_chars=request.min_chars,
            max_chars=request.max_chars,
            system_requirements=request.system_requirements,
            quality_requirements=request.quality_requirements,
            timeout_seconds=request.timeout_seconds,
            max_retries=request.max_retries,
            retry_interval_seconds=request.retry_interval_seconds,
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
                system_requirements=request.system_requirements,
                quality_requirements=request.quality_requirements,
                timeout_seconds=request.timeout_seconds,
                max_retries=request.max_retries,
                retry_interval_seconds=request.retry_interval_seconds,
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
        prompt = self.build_prompt(
            user_request,
            config,
            request.runtime_context,
            request,
        )
        max_attempts = self._max_attempts(config, request)
        retry_interval = self._retry_interval(config, request)
        last_result: NovelGenerationResult | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                body = await self._generate_body_with_timeout(
                    prompt,
                    config,
                    request,
                    self._timeout_seconds(config, request),
                )
            except asyncio.TimeoutError:
                error = (
                    f"小说生成超时：第 {attempt}/{max_attempts} 次尝试超过 "
                    f"{self._timeout_seconds(config, request)} 秒"
                )
                last_result = NovelGenerationResult(ok=False, error=error)
                logger.warning(error)
            except Exception as exc:
                error = f"小说生成失败：{exc}"
                last_result = NovelGenerationResult(ok=False, error=error)
                logger.error(error, exc_info=True)
            else:
                body = self.clean_novel_body(body)
                report = self.quality_check(body, request)
                if report.status == "pass":
                    return NovelGenerationResult(ok=True, body=body, quality_report=report)

                error = self._quality_error(report)
                last_result = NovelGenerationResult(
                    ok=False,
                    body=body,
                    error=error,
                    quality_report=report,
                )
                logger.warning(
                    f"小说生成质量检查失败：第 {attempt}/{max_attempts} 次尝试，"
                    f"issues={report.issues}, details={report.issue_details}"
                )
                if not self._retry_on_quality_failure(config, request):
                    return last_result

            if attempt < max_attempts and retry_interval > 0:
                await asyncio.sleep(retry_interval)

        return last_result or NovelGenerationResult(ok=False, error="小说生成失败")

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
        llm_request.add_payload(
            LLMPayload(ROLE.SYSTEM, [Text(self.build_system_prompt(config, request))])
        )
        llm_request.add_payload(LLMPayload(ROLE.USER, [Text(prompt)]))
        response = await llm_request.send(stream=False)
        return str(await response).strip()

    def build_system_prompt(
        self,
        config: NovelWriterConfig,
        request: NovelGenerationRequest,
    ) -> str:
        """构建原生 system prompt。"""

        lines = [
            "你是一名专业小说写作专家，擅长根据角色人设、世界观背景、作品上下文和用户要求创作可保存的小说正文或章节正文。",
            "你的任务是生成完整、连贯、可直接保存的小说正文。你必须严格遵守以下规则：",
            "",
            "【写作质量】",
            "- 正文必须具有小说叙事感，而不是剧情梗概、设定说明或聊天回复。",
            "- 每个段落应推进至少一种内容：场景、动作、对话、心理、冲突、氛围或关系变化。",
            "- 不要用空泛总结凑字数；如果篇幅不足，应继续扩写具体场景、动作、对话和心理描写。",
            "- 保持角色性格、身份、表达风格和背景一致。",
            "- 优先满足用户提出的题材、情节、篇幅、风格和续写方向。",
            "",
            "【输出限制】",
            "- 只输出小说正文。",
            "- 不要解释创作过程。",
            "- 不要输出“好的”“以下是”“我来写”等开场白。",
            "- 不要 AI 自述，不要提到模型、提示词、系统要求或质量检查。",
            "- 不要输出标题，除非用户明确要求标题。",
            "- 禁止使用数字序号、项目符号、Markdown 列表或章节大纲格式。",
            "",
            "【段落协议】",
            f"- 使用 `{_PARAGRAPH_MARKER}` 作为唯一段落分隔标记。",
            f"- `{_PARAGRAPH_MARKER}` 只能出现在两个自然段之间。",
            f"- 不要在正文开头或结尾输出 `{_PARAGRAPH_MARKER}`。",
            f"- 不要连续输出多个 `{_PARAGRAPH_MARKER}`。",
            "- 每个自然段通常包含多句连续描写或对话推进。",
            "- 禁止把每一句话都单独拆成一个段落。",
            "",
            "【篇幅要求】",
            f"- 除非用户明确要求极短篇幅，否则正文至少达到 {config.writer.min_words} 字。",
            f"- 除非用户明确要求极短篇幅，否则正文至少包含 {config.writer.min_paragraphs} 个自然段。",
            "- 如果调用方提供最小字符数、目标字符数或最大字符数，以调用方要求为准。",
        ]
        extra_requirements = self._system_requirements(request)
        quality_requirements = self._quality_requirements(config, request)
        if quality_requirements:
            lines.extend(["", "【调用方字数与质量要求】", quality_requirements])
        if extra_requirements:
            lines.extend(["", "【调用方系统要求】", extra_requirements])
        return "\n".join(lines)
    def build_prompt(
        self,
        user_request: str,
        config: NovelWriterConfig | None = None,
        runtime_context: NovelRuntimeContext | None = None,
        request: NovelGenerationRequest | None = None,
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
            project_context=self._project_context(request),
            continuation_context=self._continuation_context(request),
            user_request=user_request,
            min_words=config.writer.min_words,
            min_paragraphs=config.writer.min_paragraphs,
        )

    @staticmethod
    def _project_context(request: NovelGenerationRequest | None) -> str:
        """提取作品或章节上下文。"""

        return request.project_context.strip() if request and request.project_context.strip() else "无"

    @staticmethod
    def _continuation_context(request: NovelGenerationRequest | None) -> str:
        """提取续写上下文。"""

        return request.continuation_context.strip() if request and request.continuation_context.strip() else "无"

    @staticmethod
    def _system_requirements(request: NovelGenerationRequest | None) -> str:
        """提取调用方系统级生成要求。"""

        return request.system_requirements.strip() if request and request.system_requirements.strip() else ""

    @staticmethod
    def _quality_requirements(
        config: NovelWriterConfig,
        request: NovelGenerationRequest | None,
    ) -> str:
        """构建字数与质量要求。"""

        min_chars = request.min_chars if request else None
        target_chars = request.target_chars if request else None
        max_chars = request.max_chars if request else None
        lines = []
        if min_chars:
            lines.append(f"正文最少 {min_chars} 个中文字符。")
        if target_chars:
            lines.append(f"正文目标约 {target_chars} 个中文字符。")
        if max_chars:
            lines.append(f"正文最多 {max_chars} 个中文字符，避免超出过多。")
        if request and request.quality_requirements.strip():
            lines.append(request.quality_requirements.strip())
        return "\n".join(lines)

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

    def clean_novel_body(self, draft: str) -> str:
        """清理模型误输出的列表式小说格式并整理为小说自然段。"""

        text = _NUMBERED_PARAGRAPH_PATTERN.sub("", draft.strip()).strip()
        marker_used = bool(_PARAGRAPH_MARKER_PATTERN.search(text))
        if marker_used:
            text = _PARAGRAPH_MARKER_PATTERN.sub("\n\n", text).strip()
            return re.sub(r"\n{3,}", "\n\n", text)
        return self._merge_sentence_paragraphs(text)

    def _merge_sentence_paragraphs(self, text: str) -> str:
        """将模型误拆的一句一段合并为自然段。"""

        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        if len(paragraphs) < 3:
            return text
        short_count = sum(1 for paragraph in paragraphs if len(paragraph) <= _SHORT_PARAGRAPH_CHAR_LIMIT)
        if short_count / len(paragraphs) < 0.6:
            return text

        merged: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = paragraph if not current else f"{current}{paragraph}"
            if len(candidate) <= _NATURAL_PARAGRAPH_TARGET_CHARS:
                current = candidate
                continue
            if current:
                merged.append(current)
            current = paragraph
        if current:
            merged.append(current)
        return "\n\n".join(merged)

    def quality_check(
        self,
        draft: str,
        request: NovelGenerationRequest | None = None,
    ) -> QualityReport:
        """执行确定性的轻量质量检查。"""

        text = draft.strip()
        issues: list[str] = []
        issue_details: dict[str, int] = {}
        if not text:
            issues.append("empty_body")
        if "作为AI" in text or "作为 AI" in text:
            issues.append("ai_meta_commentary")
        if "【用户要求】" in text or "【Bot 人设】" in text:
            issues.append("prompt_leak")
        if request and request.min_chars and len(text) < request.min_chars:
            issues.append("below_min_chars")
            issue_details["min_chars"] = request.min_chars
        if request and request.max_chars and len(text) > request.max_chars:
            issues.append("above_max_chars")
            issue_details["max_chars"] = request.max_chars
        if request and request.target_chars:
            issue_details["target_chars"] = request.target_chars
        status = "pass" if not issues else "fail"
        return QualityReport(
            status=status,
            issues=issues,
            issue_details=issue_details,
            char_count=len(text),
        )

    @staticmethod
    def _quality_error(report: QualityReport) -> str:
        """构建质量检查失败错误。"""

        return (
            "小说生成结果未通过质量检查："
            f"issues={report.issues}, char_count={report.char_count}, details={report.issue_details}"
        )

    @staticmethod
    def _retry_on_quality_failure(
        config: NovelWriterConfig,
        request: NovelGenerationRequest,
    ) -> bool:
        """判断质量失败是否可重试。"""

        return config.writer.retry_on_quality_failure and request.max_retries != 0

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
            model_set = llm_api.get_model_set_by_name(
                model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return self._apply_generation_model_options(model_set, config, request)
        model_set = llm_api.get_model_set_by_task("actor")
        return self._apply_generation_model_options(
            [
                {
                    **entry,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                for entry in model_set
            ],
            config,
            request,
        )

    def _apply_generation_model_options(
        self,
        model_set: list[dict[str, Any]],
        config: NovelWriterConfig,
        request: NovelGenerationRequest | None,
    ) -> list[dict[str, Any]]:
        """复制模型配置并应用小说生成专用超时和重试策略。"""

        timeout_seconds = self._timeout_seconds(
            config,
            request or NovelGenerationRequest(user_request="__model_options__"),
        )
        return [
            {
                **entry,
                "timeout": timeout_seconds,
                "max_retry": 0,
                "retry_interval": 0,
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
