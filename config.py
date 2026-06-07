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
            description="是否启用小说创作插件；false 时插件不注册 write_novel Action，不会响应写小说请求。",
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
        min_words: int = Field(
            default=1200,
            description="默认要求小说正文至少达到的中文字数；用户明确要求更短篇幅时仍会尊重用户要求。",
        )
        min_paragraphs: int = Field(
            default=8,
            description="默认要求小说正文至少包含的自然段数量；用于避免模型只输出一句话。",
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
                "【用户要求】\n{user_request}\n\n"
                "请输出完整小说正文。篇幅要求：\n"
                "1. 除非用户明确要求极短篇幅，否则正文至少 {min_words} 字、至少 {min_paragraphs} 个自然段；\n"
                "2. 每段都要推进场景、动作、心理或对话，不要只写一句总结；\n"
                "3. 保持 Bot 的性格、身份、表达风格和背景一致；\n"
                "4. 优先满足用户提出的题材、情节、篇幅、风格要求；\n"
                "5. 不要解释创作过程，不要输出标题以外的元说明；\n"
                "6. 内容适合被拆分为多条聊天记录发送。"
            ),
            description=(
                "小说主提示词模板；{bot_persona} 会被替换为 CoreConfig personality 的昵称、别名、"
                "身份、核心人格、人格侧面、表达风格、安全准则、禁止行为和运行时上下文；"
                "{background_prompt} 会被替换为 background_prompt_template 渲染结果；"
                "{background_story} 会被替换为 CoreConfig personality.background_story；"
                "{user_request} 会被替换为用户本次写作要求；"
                "{min_words} 会被替换为 writer.min_words；"
                "{min_paragraphs} 会被替换为 writer.min_paragraphs。"
            ),
        )

    writer: WriterSection = Field(default_factory=WriterSection)
