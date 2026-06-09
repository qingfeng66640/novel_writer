"""novel_writer 插件配置。"""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


class NovelWriterConfig(BaseConfig):
    """小说创作插件配置。"""

    config_name: ClassVar[str] = "config"
    config_description: ClassVar[str] = "小说创作插件配置"

    @config_section("writer")
    class WriterSection(SectionBase):
        """小说创作行为配置。"""

        enabled: bool = Field(
            default=True,
            description="是否启用小说创作插件；false 时插件不注册生成 Service 与 write_novel Action。",
        )
        action_enabled: bool = Field(
            default=True,
            description="是否注册 write_novel Action；关闭后仍可保留 novel_generation Service 供其他插件调用。",
        )
        model_name: str = Field(
            default="",
            description=(
                "小说生成使用的自定义模型名称，填写 config/model.toml 中 [[models]].name 的值；"
                "留空时使用框架 model_tasks.actor。"
            ),
        )
        temperature: float = Field(
            default=0.9,
            description="小说生成温度参数，参考 config/model.toml 的 task temperature；数值越高越发散。",
        )
        max_tokens: int = Field(
            default=3000,
            description="小说生成最大输出 token 数，参考 config/model.toml 的 task max_tokens；过小会导致只输出很短内容。",
        )
        generation_timeout_seconds: int = Field(
            default=120,
            description="单次小说生成尝试的完整超时时间，单位秒；包含请求发送和响应正文读取。",
        )
        generation_max_retries: int = Field(
            default=1,
            description="小说生成失败或超时后的最大重试次数；0 表示不重试。",
        )
        generation_retry_interval_seconds: float = Field(
            default=1.0,
            description="小说生成失败、超时或质量检查失败后再次重试前等待的秒数。",
        )
        retry_on_quality_failure: bool = Field(
            default=True,
            description="质量检查失败时是否按 generation_max_retries 自动重试，例如正文过短、空正文、AI 自述或提示词泄漏。",
        )
        min_words: int = Field(
            default=1200,
            description="默认要求小说正文至少达到的中文字数；用户明确要求更短篇幅时仍会尊重用户要求。",
        )
        min_paragraphs: int = Field(
            default=8,
            description="默认要求小说正文至少包含的自然段数量；用于避免模型只输出一句话。",
        )
        managed_chapter_target_chars: int = Field(
            default=2200,
            description="供文章管理插件调用时的默认章节目标中文字符数。",
        )
        managed_chapter_min_chars: int = Field(
            default=1800,
            description="供文章管理插件调用时的默认章节最小中文字符数。",
        )
        managed_chapter_max_chars: int = Field(
            default=3200,
            description="供文章管理插件调用时的默认章节最大中文字符数。",
        )
        fallback_to_direct_send: bool = Field(
            default=True,
            description=(
                "当未检测到 forward_msg 依赖或合并转发发送失败时，是否直接发送小说正文；"
                "启用后会先提醒用户，小说内容过多可能导致刷屏。"
            ),
        )
        max_words_per_message: int = Field(
            default=500,
            description="合并转发单个 node 节点的最大文本长度，小说会按该值拆分为多条聊天记录。",
        )
        background_prompt_template: str = Field(
            default=(
                "以下是 Bot 的世界观背景知识，只作为创作依据，不要机械复述：\n"
                "{background_story}"
            ),
            description=(
                "背景知识提示词模板；{background_story} 会被替换为"
                "框架 CoreConfig personality.background_story 的内容。"
            ),
        )
        novel_prompt_template: str = Field(
            default=(
                "你需要以 Bot 的人设和背景为基础，为用户创作一篇小说。\n\n"
                "【Bot 人设】\n{bot_persona}\n\n"
                "【背景知识】\n{background_prompt}\n\n"
                "【项目上下文】\n{project_context}\n\n"
                "【续写上下文】\n{continuation_context}\n\n"
                "【用户要求】\n{user_request}"
            ),
            description=(
                "小说主提示词模板；{bot_persona} 会被替换为 CoreConfig personality 的昵称、别名、"
                "身份、核心人格、人格侧面、表达风格、安全准则、禁止行为和运行时上下文；"
                "{background_prompt} 会被替换为 background_prompt_template 渲染结果；"
                "{background_story} 会被替换为 CoreConfig personality.background_story；"
                "{project_context} 会被替换为作品或章节项目上下文；"
                "{continuation_context} 会被替换为续写上下文；"
                "{user_request} 会被替换为用户本次写作要求。"
            ),
        )

    writer: WriterSection = Field(default_factory=WriterSection)
