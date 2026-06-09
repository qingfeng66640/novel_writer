"""novel_writer 生成服务的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class NovelRuntimeContext:
    """生成请求可选的运行时上下文。"""

    bot_nickname: str = ""
    stream_name: str = ""
    recent_content: str = ""


@dataclass(slots=True)
class NovelGenerationRequest:
    """小说生成服务请求。"""

    user_request: str
    mode: str = "standalone"
    project_context: str = ""
    continuation_context: str = ""
    chapter_number: int | None = None
    chapter_title: str = ""
    target_chars: int | None = None
    min_chars: int | None = None
    max_chars: int | None = None
    system_requirements: str = ""
    quality_requirements: str = ""
    timeout_seconds: int | None = None
    max_retries: int | None = None
    retry_interval_seconds: float | None = None
    runtime_context: NovelRuntimeContext | None = None
    request_name: str = "novel_writer.generate"


@dataclass(slots=True)
class QualityReport:
    """生成正文的轻量质量检查结果。"""

    status: str
    issues: list[str] = field(default_factory=list)
    issue_details: dict[str, int] = field(default_factory=dict)
    char_count: int = 0


@dataclass(slots=True)
class NovelGenerationResult:
    """小说生成服务结果。"""

    ok: bool
    body: str = ""
    title: str = ""
    summary: str = ""
    quality_report: QualityReport | None = None
    error: str = ""
