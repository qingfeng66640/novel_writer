"""novel_writer 插件入口点。"""

from __future__ import annotations

from src.app.plugin_system.base import BasePlugin, register_plugin

from .action import WriteNovelAction
from .command import NovelCommand
from .config import NovelWriterConfig
from .service import NovelGenerationService


@register_plugin
class NovelWriterPlugin(BasePlugin):
    """根据 Bot 人设与背景创作小说的插件。"""

    plugin_name = "novel_writer"
    plugin_description = "根据 Bot 人设与背景自动创作小说，并通过合并转发消息发送。（我去了我蝶终于能写小说了😭😭😭）"
    plugin_version = "1.3.0"

    configs = [NovelWriterConfig]

    def get_components(self) -> list[type]:
        """返回插件组件类。"""

        if isinstance(self.config, NovelWriterConfig) and not self.config.writer.enabled:
            return []
        if isinstance(self.config, NovelWriterConfig) and not self.config.writer.action_enabled:
            return [NovelGenerationService]
        return [NovelGenerationService, WriteNovelAction, NovelCommand]
