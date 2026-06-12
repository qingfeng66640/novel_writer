"""novel_writer 插件契约测试。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from plugins.novel_writer.action import WriteNovelAction  # noqa: E402
from plugins.novel_writer.command import NovelCommand  # noqa: E402
from plugins.novel_writer.config import NovelWriterConfig  # noqa: E402
from plugins.novel_writer.plugin import NovelWriterPlugin  # noqa: E402
from plugins.novel_writer.schemas import NovelGenerationRequest, NovelGenerationResult  # noqa: E402
from plugins.novel_writer.service import NovelGenerationService  # noqa: E402
from src.app.plugin_system.api import send_api  # noqa: E402
from src.kernel.concurrency import get_task_manager  # noqa: E402
from src.app.plugin_system.types import PermissionLevel  # noqa: E402
from src.core.models.message import Message  # noqa: E402

PLUGIN_DIR = Path(__file__).resolve().parents[1]


def _make_action(config: NovelWriterConfig | None = None) -> WriteNovelAction:
    """构造测试用 Action 实例。"""

    plugin = NovelWriterPlugin(config or NovelWriterConfig())
    chat_stream = SimpleNamespace(
        stream_id="stream",
        bot_id="10000",
        bot_nickname="小狐狸",
        stream_name="测试流",
        context=SimpleNamespace(history_messages=[]),
    )
    return WriteNovelAction(chat_stream, plugin)


def test_manifest_matches_plugin_contract() -> None:
    """manifest 名称、版本与组件清单保持一致。"""

    manifest = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    plugin = NovelWriterPlugin(NovelWriterConfig())
    component_names = {
        getattr(component, "action_name", None)
        or getattr(component, "service_name", None)
        or getattr(component, "command_name", None)
        for component in plugin.get_components()
    }
    include_names = {item["component_name"] for item in manifest["include"]}
    assert manifest["name"] == NovelWriterPlugin.plugin_name
    assert manifest["version"] == NovelWriterPlugin.plugin_version
    assert include_names <= component_names
    assert "novel_generation" in component_names
    assert "novel" in component_names
    assert manifest["dependencies"]["plugins"] == []
    assert manifest["dependencies"]["components"] == []
    assert manifest["dependencies_required"] is False
    assert manifest["include"][0]["dependencies"] == []


def test_write_novel_action_declares_associated_types() -> None:
    """Action components must explicitly declare supported message types."""

    assert WriteNovelAction.validate_associated_types() == ["text"]


def test_novel_command_is_admin_only() -> None:
    """/novel 命令仅允许管理员权限触发。"""

    assert NovelCommand.command_name == "novel"
    assert NovelCommand.permission_level == PermissionLevel.OPERATOR


async def test_novel_command_starts_background_generation(monkeypatch: Any) -> None:
    """/novel 命令立即返回并把生成放入后台任务。"""

    created: dict[str, Any] = {}
    feedback: list[tuple[str, str, str | None, str | None]] = []

    def fake_create_task(
        coro: Any,
        name: str | None = None,
        daemon: bool = False,
        **kwargs: Any,
    ) -> SimpleNamespace:
        created["coro"] = coro
        created["name"] = name
        created["daemon"] = daemon
        coro.close()
        return SimpleNamespace(task_id="task")

    async def fake_send_text(
        content: str,
        stream_id: str,
        platform: str | None = None,
        reply_to: str | None = None,
    ) -> bool:
        feedback.append((content, stream_id, platform, reply_to))
        return True

    monkeypatch.setattr(get_task_manager(), "create_task", fake_create_task)
    monkeypatch.setattr(send_api, "send_text", fake_send_text)
    message = Message(
        message_id="msg",
        sender_id="admin",
        sender_name="管理员",
        platform="qq",
        chat_type="group",
        stream_id="stream",
    )
    command = NovelCommand(
        plugin=NovelWriterPlugin(NovelWriterConfig()),
        stream_id="stream",
        message_id="msg",
        message=message,
    )
    assert await command.execute("赛博狐狸") == (True, "小说生成已开始，请稍等。")
    assert created == {
        "coro": created["coro"],
        "name": "novel_writer_command_generation",
        "daemon": True,
    }
    assert feedback == [("小说生成已开始，请稍等。", "stream", "qq", "msg")]


async def test_novel_command_background_reuses_write_action(monkeypatch: Any) -> None:
    """/novel 后台任务复用 write_novel Action 执行生成与发送。"""

    captured: dict[str, Any] = {}

    async def fake_execute(self: WriteNovelAction, user_request: str) -> tuple[bool, str]:
        captured["stream_id"] = self.chat_stream.stream_id
        captured["platform"] = self.chat_stream.platform
        captured["request"] = user_request
        return True, "ok"

    monkeypatch.setattr(WriteNovelAction, "execute", fake_execute)
    command = NovelCommand(
        plugin=NovelWriterPlugin(NovelWriterConfig()),
        stream_id="stream",
        message_id="msg",
        message=Message(message_id="msg", platform="qq", chat_type="group", stream_id="stream"),
    )
    await command._run_generation("请写一篇简短的小说。用户要求：赛博狐狸")
    assert captured == {
        "stream_id": "stream",
        "platform": "qq",
        "request": "请写一篇简短的小说。用户要求：赛博狐狸",
    }


async def test_novel_command_reports_generation_failure(monkeypatch: Any) -> None:
    """/novel 生成失败时主动反馈失败原因。"""

    feedback: list[str] = []

    async def fake_execute(self: WriteNovelAction, user_request: str) -> tuple[bool, str]:
        return False, "模型超时"

    async def fake_send_text(
        content: str,
        stream_id: str,
        platform: str | None = None,
        reply_to: str | None = None,
    ) -> bool:
        feedback.append(content)
        return True

    monkeypatch.setattr(WriteNovelAction, "execute", fake_execute)
    monkeypatch.setattr(send_api, "send_text", fake_send_text)
    command = NovelCommand(
        plugin=NovelWriterPlugin(NovelWriterConfig()),
        stream_id="stream",
        message_id="msg",
        message=Message(message_id="msg", platform="qq", stream_id="stream"),
    )
    await command._run_generation("请写一篇简短的小说。用户要求：赛博狐狸")
    assert feedback == ["小说生成失败：模型超时"]


async def test_novel_command_reports_cancellation(monkeypatch: Any) -> None:
    """/novel 后台任务被取消时主动反馈中断。"""

    feedback: list[str] = []

    async def fake_execute(self: WriteNovelAction, user_request: str) -> tuple[bool, str]:
        raise asyncio.CancelledError

    async def fake_send_text(
        content: str,
        stream_id: str,
        platform: str | None = None,
        reply_to: str | None = None,
    ) -> bool:
        feedback.append(content)
        return True

    monkeypatch.setattr(WriteNovelAction, "execute", fake_execute)
    monkeypatch.setattr(send_api, "send_text", fake_send_text)
    command = NovelCommand(
        plugin=NovelWriterPlugin(NovelWriterConfig()),
        stream_id="stream",
        message_id="msg",
        message=Message(message_id="msg", platform="qq", stream_id="stream"),
    )
    try:
        await command._run_generation("请写一篇简短的小说。用户要求：赛博狐狸")
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("命令取消时应继续抛出 CancelledError")
    assert feedback == ["小说生成已中断。"]


def test_config_defaults_use_actor_task() -> None:
    """默认配置不指定模型名称，表示使用 actor task。"""

    config = NovelWriterConfig()
    assert config.writer.enabled is True
    assert config.writer.model_name == ""
    assert config.writer.temperature == 0.9
    assert config.writer.generation_timeout_seconds == 120
    assert config.writer.generation_max_retries == 1
    assert config.writer.generation_retry_interval_seconds == 1.0
    assert config.writer.retry_on_quality_failure is True
    assert config.writer.min_words == 1200
    assert config.writer.fallback_to_direct_send is True
    assert config.writer.max_words_per_message == 500
    assert "{bot_persona}" in config.writer.novel_prompt_template
    assert "{user_request}" in config.writer.novel_prompt_template
    assert "{background_story}" in config.writer.background_prompt_template
    assert "【系统生成要求】" not in config.writer.novel_prompt_template
    assert "【质量要求】" not in config.writer.novel_prompt_template


def test_config_field_descriptions_explain_placeholders() -> None:
    """配置字段描述说明参数与占位符用途。"""

    fields = NovelWriterConfig.WriterSection.model_fields
    assert "false 时插件不注册生成 Service" in fields["enabled"].description
    assert "write_novel Action" in fields["enabled"].description
    assert "[[models]].name" in fields["model_name"].description
    assert "model_tasks.actor" in fields["model_name"].description
    assert "temperature" in fields["temperature"].description
    assert "max_tokens" in fields["max_tokens"].description
    assert "完整超时时间" in fields["generation_timeout_seconds"].description
    assert "最大重试次数" in fields["generation_max_retries"].description
    assert "重试前等待" in fields["generation_retry_interval_seconds"].description
    assert "质量检查失败" in fields["retry_on_quality_failure"].description
    assert "至少达到" in fields["min_words"].description
    assert "未检测到 forward_msg" in fields["fallback_to_direct_send"].description
    assert "刷屏" in fields["fallback_to_direct_send"].description
    assert "node 节点" in fields["max_words_per_message"].description
    assert "{background_story}" in fields["background_prompt_template"].description
    assert "personality.background_story" in fields["background_prompt_template"].description
    prompt_description = fields["novel_prompt_template"].description
    assert "{bot_persona}" in prompt_description
    assert "{background_prompt}" in prompt_description
    assert "{background_story}" in prompt_description
    assert "{project_context}" in prompt_description
    assert "{continuation_context}" in prompt_description
    assert "{user_request}" in prompt_description
    assert "CoreConfig personality" in prompt_description


def test_disabled_config_unregisters_action() -> None:
    """配置关闭时不注册 Action 组件。"""

    config = NovelWriterConfig()
    config.writer.enabled = False
    plugin = NovelWriterPlugin(config)
    assert plugin.get_components() == []


def test_action_can_be_disabled_while_service_stays_available() -> None:
    """关闭 Action 时仍保留跨插件生成 Service。"""

    config = NovelWriterConfig()
    config.writer.action_enabled = False
    plugin = NovelWriterPlugin(config)
    assert plugin.get_components() == [NovelGenerationService]


def test_managed_chapter_request_wraps_project_context(monkeypatch: Any) -> None:
    """章节生成 Service 会把作品上下文包进管理型指令。"""

    captured: dict[str, NovelGenerationRequest] = {}
    service = NovelGenerationService(NovelWriterPlugin(NovelWriterConfig()))

    async def fake_generate(request: NovelGenerationRequest):
        captured["request"] = request
        return "ok"

    monkeypatch.setattr(service, "generate", fake_generate)
    result = __import__("asyncio").run(
        service.generate_chapter(
            NovelGenerationRequest(
                user_request="推进主线",
                project_context="作品：黑塔",
                continuation_context="上一章结尾",
                chapter_number=2,
                chapter_title="回声",
                target_chars=2200,
                min_chars=100,
                max_chars=3000,
                system_requirements="只输出正文",
                quality_requirements="场景必须完整",
                request_name="article_manager.generate_chapter",
            )
        )
    )

    assert result == "ok"
    managed = captured["request"]
    assert managed.mode == "chapter"
    assert managed.request_name == "article_manager.generate_chapter"
    assert managed.min_chars == 100
    assert managed.max_chars == 3000
    assert managed.project_context == "作品：黑塔"
    assert managed.continuation_context == "上一章结尾"
    assert managed.system_requirements == "只输出正文"
    assert managed.quality_requirements == "场景必须完整"
    assert "作品：黑塔" in managed.user_request
    assert "上一章结尾" in managed.user_request
    assert "第 2 章" in managed.user_request
    assert "推进主线" in managed.user_request


def test_generation_request_overrides_timeout_and_retry_config() -> None:
    """生成请求可覆盖默认超时与重试配置。"""

    config = NovelWriterConfig()
    service = NovelGenerationService(NovelWriterPlugin(config))
    request = NovelGenerationRequest(
        user_request="写小说",
        timeout_seconds=3,
        max_retries=2,
        retry_interval_seconds=0.5,
    )
    assert service._timeout_seconds(config, request) == 3.0
    assert service._max_attempts(config, request) == 3
    assert service._retry_interval(config, request) == 0.5


def test_generation_retries_timeout_then_returns_clear_error(monkeypatch: Any) -> None:
    """生成超时会按配置重试并返回明确错误。"""

    config = NovelWriterConfig()
    config.writer.generation_timeout_seconds = 1
    config.writer.generation_max_retries = 1
    config.writer.generation_retry_interval_seconds = 0
    service = NovelGenerationService(NovelWriterPlugin(config))
    attempts = 0

    async def fake_generate_body(*_args: Any, **_kwargs: Any) -> str:
        nonlocal attempts
        attempts += 1
        raise TimeoutError

    monkeypatch.setattr(service, "_generate_body", fake_generate_body)
    monkeypatch.setattr(service, "build_prompt", lambda *_args: "prompt")
    result = __import__("asyncio").run(
        service.generate(NovelGenerationRequest(user_request="写小说"))
    )
    assert attempts == 2
    assert result.ok is False
    assert "小说生成超时" in result.error
    assert "2/2" in result.error


def test_build_prompt_includes_user_context_layers(monkeypatch: Any) -> None:
    """用户提示词只承载写作材料和本次要求。"""

    personality = SimpleNamespace(
        nickname="长夜月",
        alias_names=[],
        identity="人类",
        personality_core="守护者",
        personality_side="温柔",
        background_story="背景故事",
        reply_style="诗意",
        safety_guidelines=[],
        negative_behaviors=[],
    )
    monkeypatch.setattr(
        "plugins.novel_writer.service.get_core_config",
        lambda: SimpleNamespace(personality=personality),
    )
    service = NovelGenerationService(NovelWriterPlugin(NovelWriterConfig()))
    prompt = service.build_prompt(
        "推进主线",
        request=NovelGenerationRequest(
            user_request="推进主线",
            project_context="作品：黑塔",
            continuation_context="上一章结尾",
            system_requirements="只输出正文",
            quality_requirements="场景必须完整",
            min_chars=1000,
            target_chars=1500,
            max_chars=2200,
        ),
    )
    assert "【项目上下文】\n作品：黑塔" in prompt
    assert "【续写上下文】\n上一章结尾" in prompt
    assert "推进主线" in prompt
    assert "只输出正文" not in prompt
    assert "场景必须完整" not in prompt
    assert "正文最少 1000 个中文字符" not in prompt


def test_build_system_prompt_contains_writer_protocol() -> None:
    """系统提示词承载写作专家、段落协议和质量要求。"""

    config = NovelWriterConfig()
    service = NovelGenerationService(NovelWriterPlugin(config))
    prompt = service.build_system_prompt(
        config,
        NovelGenerationRequest(
            user_request="推进主线",
            system_requirements="只输出正文",
            quality_requirements="场景必须完整",
            min_chars=1000,
            target_chars=1500,
            max_chars=2200,
        ),
    )
    assert "专业小说写作专家" in prompt
    assert "只输出小说正文" in prompt
    assert "<paragraph/>" in prompt
    assert "正文至少达到 1200 字" in prompt
    assert "正文至少包含 8 个自然段" in prompt
    assert "正文最少 1000 个中文字符" in prompt
    assert "正文目标约 1500 个中文字符" in prompt
    assert "正文最多 2200 个中文字符" in prompt
    assert "只输出正文" in prompt
    assert "场景必须完整" in prompt


def test_generate_body_adds_system_payload_before_user(monkeypatch: Any) -> None:
    """LLM 调用使用原生 system payload 承载小说生成协议。"""

    payloads = []

    class FakeResponse:
        def __await__(self):
            async def _result():
                return "正文"

            return _result().__await__()

    class FakeRequest:
        def add_payload(self, payload, position=None):
            payloads.append(payload)
            return self

        async def send(self, *, stream: bool = True):
            return FakeResponse()

    monkeypatch.setattr(
        "plugins.novel_writer.service.llm_api.create_llm_request",
        lambda *_args, **_kwargs: FakeRequest(),
    )
    service = NovelGenerationService(NovelWriterPlugin(NovelWriterConfig()))
    monkeypatch.setattr(service, "_get_model_set", lambda *_args, **_kwargs: [])
    result = __import__("asyncio").run(
        service._generate_body(
            "用户提示词",
            NovelWriterConfig(),
            NovelGenerationRequest(user_request="写小说"),
        )
    )
    assert result == "正文"
    assert [payload.role for payload in payloads] == ["system", "user"]
    assert "专业小说写作专家" in payloads[0].content[0].text
    assert payloads[1].content[0].text == "用户提示词"


def test_generation_retries_quality_failure_then_succeeds(monkeypatch: Any) -> None:
    """质量检查失败会按配置重试并保留最终成功结果。"""

    config = NovelWriterConfig()
    config.writer.generation_max_retries = 1
    config.writer.generation_retry_interval_seconds = 0
    service = NovelGenerationService(NovelWriterPlugin(config))
    bodies = ["太短", "这是足够长的小说正文"]

    async def fake_generate_body(*_args: Any, **_kwargs: Any) -> str:
        return bodies.pop(0)

    monkeypatch.setattr(service, "_generate_body", fake_generate_body)
    monkeypatch.setattr(service, "build_prompt", lambda *_args, **_kwargs: "prompt")
    result = __import__("asyncio").run(
        service.generate(NovelGenerationRequest(user_request="写小说", min_chars=10))
    )
    assert result.ok is True
    assert result.body == "这是足够长的小说正文"
    assert result.quality_report is not None
    assert result.quality_report.char_count == len("这是足够长的小说正文")


def test_generation_returns_last_quality_failure_report(monkeypatch: Any) -> None:
    """质量重试耗尽后返回最后一次失败正文和质量报告。"""

    config = NovelWriterConfig()
    config.writer.generation_max_retries = 1
    config.writer.generation_retry_interval_seconds = 0
    service = NovelGenerationService(NovelWriterPlugin(config))

    async def fake_generate_body(*_args: Any, **_kwargs: Any) -> str:
        return "短"

    monkeypatch.setattr(service, "_generate_body", fake_generate_body)
    monkeypatch.setattr(service, "build_prompt", lambda *_args, **_kwargs: "prompt")
    result = __import__("asyncio").run(
        service.generate(NovelGenerationRequest(user_request="写小说", min_chars=10))
    )
    assert result.ok is False
    assert result.body == "短"
    assert result.quality_report is not None
    assert result.quality_report.issues == ["below_min_chars"]
    assert result.quality_report.issue_details["min_chars"] == 10
    assert result.quality_report.char_count == 1
    assert "below_min_chars" in result.error


def test_quality_retry_can_be_disabled(monkeypatch: Any) -> None:
    """关闭质量失败重试时直接返回第一次质量失败。"""

    config = NovelWriterConfig()
    config.writer.generation_max_retries = 3
    config.writer.generation_retry_interval_seconds = 0
    config.writer.retry_on_quality_failure = False
    service = NovelGenerationService(NovelWriterPlugin(config))
    attempts = 0

    async def fake_generate_body(*_args: Any, **_kwargs: Any) -> str:
        nonlocal attempts
        attempts += 1
        return "短"

    monkeypatch.setattr(service, "_generate_body", fake_generate_body)
    monkeypatch.setattr(service, "build_prompt", lambda *_args, **_kwargs: "prompt")
    result = __import__("asyncio").run(
        service.generate(NovelGenerationRequest(user_request="写小说", min_chars=10))
    )
    assert attempts == 1
    assert result.ok is False
    assert result.quality_report is not None
    assert result.quality_report.issues == ["below_min_chars"]


def test_build_prompt_uses_core_personality(monkeypatch: Any) -> None:
    """提示词使用框架 CoreConfig 中的人设字段。"""

    personality = SimpleNamespace(
        nickname="长夜月",
        alias_names=["长夜", "月宝"],
        identity="人类",
        personality_core="温柔、极端、孤独的守护者",
        personality_side="独自在暗处行动",
        background_story="守望三月七的背景故事",
        reply_style="诗意温柔",
        safety_guidelines=["保持安全"],
        negative_behaviors=["不要违法"],
    )
    monkeypatch.setattr(
        "plugins.novel_writer.service.get_core_config",
        lambda: SimpleNamespace(personality=personality),
    )
    action = _make_action()
    prompt = action._build_prompt("写一篇短篇小说", NovelWriterConfig())
    assert "长夜月" in prompt
    assert "温柔、极端、孤独的守护者" in prompt
    assert "守望三月七的背景故事" in prompt
    assert "写一篇短篇小说" in prompt


def test_clean_novel_body_removes_numbered_paragraphs() -> None:
    """清理模型误输出的段首序号。"""

    service = NovelGenerationService(NovelWriterPlugin(NovelWriterConfig()))
    text = "1. 月光落在车窗上。\n\n二、三月七回头看他。\n\n第三段没有序号。"
    assert service.clean_novel_body(text) == "月光落在车窗上。三月七回头看他。第三段没有序号。"


def test_clean_novel_body_converts_paragraph_markers() -> None:
    """将内部段落协议转换为用户可见的小说自然段。"""

    service = NovelGenerationService(NovelWriterPlugin(NovelWriterConfig()))
    text = "第一自然段。<paragraph/>第二自然段。\n\n<paragraph/>第三自然段。"
    assert service.clean_novel_body(text) == "第一自然段。\n\n第二自然段。\n\n第三自然段。"


def test_clean_novel_body_merges_sentence_paragraphs() -> None:
    """将模型误拆的一句一段整理为小说自然段。"""

    service = NovelGenerationService(NovelWriterPlugin(NovelWriterConfig()))
    text = "她推开门。\n\n风从走廊尽头吹来。\n\n三月七缩了缩肩。\n\n长夜月没有说话。"
    assert service.clean_novel_body(text) == "她推开门。风从走廊尽头吹来。三月七缩了缩肩。长夜月没有说话。"


def test_action_declares_valid_associated_types() -> None:
    """Action 显式声明 Neo-MoFox 1.2.0-rc 需要的关联类型。"""

    assert WriteNovelAction.associated_types == ["text"]
    assert WriteNovelAction.validate_associated_types() == ["text"]


def test_action_description_contains_natural_triggers() -> None:
    """Action 描述包含自然语言触发词。"""

    description = WriteNovelAction.action_description
    assert "写小说" in description
    assert "写故事" in description
    assert "编故事" in description
    assert "创作小说" in description


def test_split_text_respects_limit_and_paragraphs() -> None:
    """文本拆分遵守单节点字数上限。"""

    action = _make_action()
    chunks = action._split_text("第一段\n\n第二段很长", 4)
    assert chunks == ["第一段", "第二段很", "长"]
    assert all(len(chunk) <= 4 for chunk in chunks)


def test_build_forward_nodes_uses_bot_identity() -> None:
    """合并转发节点使用当前 ChatStream 的 Bot 展示身份。"""

    action = _make_action()
    nodes = action._build_forward_nodes("第一段\n\n第二段", 3)
    assert nodes[0]["type"] == "node"
    assert nodes[0]["data"]["user_id"] == "10000"
    assert nodes[0]["data"]["nickname"] == "小狐狸"
    assert nodes[0]["data"]["content"][0]["data"]["text"] == "第一段"


def test_direct_send_fallback_warns_before_sending(monkeypatch: Any) -> None:
    """合并转发不可用时按配置先提醒刷屏风险再直发正文。"""

    sent_messages: list[str] = []
    action = _make_action()

    async def fake_send_to_stream(content: str) -> bool:
        sent_messages.append(content)
        return True

    monkeypatch.setattr(action, "_send_to_stream", fake_send_to_stream)
    config = NovelWriterConfig()
    config.writer.max_words_per_message = 3
    result = __import__("asyncio").run(
        action._handle_forward_failure("第一段\n\n第二段", config, "forward_msg 服务不可用")
    )
    assert result == (True, "forward_msg 服务不可用；已直发小说正文 2 条")
    assert "可能导致刷屏" in sent_messages[0]
    assert sent_messages[1:] == ["第一段", "第二段"]


def test_direct_send_fallback_can_be_disabled() -> None:
    """关闭直发兜底时保留合并转发失败结果。"""

    config = NovelWriterConfig()
    config.writer.fallback_to_direct_send = False
    action = _make_action(config)
    result = __import__("asyncio").run(
        action._handle_forward_failure("正文", config, "forward_msg 服务不可用")
    )
    assert result == (False, "forward_msg 服务不可用")



def test_get_model_set_uses_actor_task_by_default(monkeypatch: Any) -> None:
    """未配置模型名称时使用 actor 任务模型并覆盖生成参数。"""

    calls: list[str] = []

    def fake_get_model_set_by_task(name: str) -> list[dict[str, Any]]:
        calls.append(name)
        return [{"name": name, "temperature": 0.1, "max_tokens": 10}]

    monkeypatch.setattr(
        "plugins.novel_writer.service.llm_api.get_model_set_by_task",
        fake_get_model_set_by_task,
    )
    config = NovelWriterConfig()
    config.writer.temperature = 0.8
    config.writer.max_tokens = 2048
    action = _make_action()
    assert action._get_model_set(config) == [
        {
            "name": "actor",
            "temperature": 0.8,
            "max_tokens": 2048,
            "timeout": 120.0,
            "max_retry": 0,
            "retry_interval": 0,
        }
    ]
    assert calls == ["actor"]


def test_model_set_overrides_timeout_without_mutating_source() -> None:
    """小说生成专用模型参数不污染全局模型配置。"""

    config = NovelWriterConfig()
    service = NovelGenerationService(NovelWriterPlugin(config))
    source = [{"name": "actor", "timeout": 60, "max_retry": 2, "retry_interval": 3}]
    request = NovelGenerationRequest(user_request="写小说", timeout_seconds=300)
    result = service._apply_generation_model_options(source, config, request)
    assert result == [
        {
            "name": "actor",
            "timeout": 300.0,
            "max_retry": 0,
            "retry_interval": 0,
        }
    ]
    assert source == [{"name": "actor", "timeout": 60, "max_retry": 2, "retry_interval": 3}]


def test_get_model_set_uses_configured_model_name(monkeypatch: Any) -> None:
    """配置模型名称时使用 config/model.toml 中的模型 name 与生成参数。"""

    calls: list[tuple[str, float | None, int | None]] = []

    def fake_get_model_set_by_name(
        name: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        calls.append((name, temperature, max_tokens))
        return [{"name": name, "temperature": temperature, "max_tokens": max_tokens}]

    config = NovelWriterConfig()
    config.writer.model_name = "custom-model"
    config.writer.temperature = 0.75
    config.writer.max_tokens = 4096
    action = _make_action(config)
    monkeypatch.setattr(
        "plugins.novel_writer.service.llm_api.get_model_set_by_name",
        fake_get_model_set_by_name,
    )
    assert action._get_model_set(config) == [
        {
            "name": "custom-model",
            "temperature": 0.75,
            "max_tokens": 4096,
            "timeout": 120.0,
            "max_retry": 0,
            "retry_interval": 0,
        }
    ]
    assert calls == [("custom-model", 0.75, 4096)]


def test_standalone_accepts_dict_request(monkeypatch: Any) -> None:
    """其他插件可以不 import NovelGenerationRequest，直接传 dict 调用。"""

    captured: dict[str, NovelGenerationRequest] = {}
    service = NovelGenerationService(NovelWriterPlugin(NovelWriterConfig()))

    async def fake_generate(request: NovelGenerationRequest):
        captured["request"] = request
        return NovelGenerationResult(ok=True, body="正文")

    monkeypatch.setattr(service, "generate", fake_generate)
    import asyncio
    result = asyncio.run(
        service.generate_standalone({"user_request": "写小说", "target_chars": 2000})
    )
    assert result.ok
    assert result.body == "正文"
    assert captured["request"].user_request == "写小说"
    assert captured["request"].target_chars == 2000
    assert captured["request"].mode == "standalone"


def test_chapter_accepts_dict_request(monkeypatch: Any) -> None:
    """章节生成接口可接受 dict 形式的请求。"""

    captured: dict[str, NovelGenerationRequest] = {}
    service = NovelGenerationService(NovelWriterPlugin(NovelWriterConfig()))

    async def fake_generate(request: NovelGenerationRequest):
        captured["request"] = request
        return NovelGenerationResult(ok=True, body="章节正文")

    monkeypatch.setattr(service, "generate", fake_generate)
    import asyncio
    result = asyncio.run(
        service.generate_chapter({
            "user_request": "继续推进剧情",
            "project_context": "科幻小说",
            "continuation_context": "上一章结尾",
            "chapter_number": 3,
            "chapter_title": "新的开始",
            "target_chars": 1500,
        })
    )
    assert result.ok
    assert captured["request"].user_request is not None
    assert captured["request"].mode == "chapter"
    assert captured["request"].project_context == "科幻小说"


def test_continue_chapter_accepts_dict_request(monkeypatch: Any) -> None:
    """续写章节接口可接受 dict 形式的请求。"""

    captured: dict[str, NovelGenerationRequest] = {}
    service = NovelGenerationService(NovelWriterPlugin(NovelWriterConfig()))

    async def fake_generate(request: NovelGenerationRequest):
        captured["request"] = request
        return NovelGenerationResult(ok=True, body="续写正文")

    monkeypatch.setattr(service, "generate", fake_generate)
    import asyncio
    result = asyncio.run(
        service.continue_chapter({
            "user_request": "请续写",
            "project_context": "仙侠小说",
            "continuation_context": "主角醒来发现",
        })
    )
    assert result.ok
    assert captured["request"].user_request is not None
    assert captured["request"].project_context == "仙侠小说"
    assert captured["request"].continuation_context == "主角醒来发现"
