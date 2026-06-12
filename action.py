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
        "### 触发时机\n\n"
        "当用户表现出任何对同人文学创作的渴望、提供脑洞与设定、请求将想法转化为故事性文字时，"
        "立即触发本 action。用户意图不限于“写小说”这一明确指令，还包括大量口语化、圈内暗号、"
        "碎片化表达与上下文暗示。具体触发场景如下——\n\n"
        "**1. 明确创作指令**\n"
        "用户直接要求生成故事、小说、片段或叙事内容，例如：“写小说”“写故事”“编个故事”"
        "“创作一段”“续写”“扩写”“展开”“细化”“写个片段”“来段甜文/虐文/沙雕文”"
        "“写个短打/一发完”“给我一段心理描写”“写个开头/钩子”“试写三个版本的第一句话”"
        "“把大纲润色成叙事段落”“用你的文风写一段氛围铺垫”“给我个转场/蒙太奇/回忆杀片段”等。\n\n"
        "**2. 口语化脑洞与假设**\n"
        "用户以假设、幻想或感叹形式表达想看的内容，例如：“如果当时他选了另一条路……”"
        "“好想看他们一起逛超市”“想看xx哭”“假如他们被困在电梯里”“雨夜，公交站，只有一把伞”"
        "“如果xxx和xxx在同一所大学会怎样”“好适合xx的歌词，能不能写出来”“梦这个”"
        "“脑一个xx场景”“想到了一个梗：……”等。\n\n"
        "**3. 同人社区暗号与需求表达**\n"
        "用户使用圈内常用语表达对文字产出的渴望，即使未直接说“写”，例如：“来点饭”“产粮”"
        "“做饭”“太太饿饿”“有没有人写”“谁来建设一下”“代了”“代一下这个”“笔给你，你来写”"
        "“现在就要看”“好饿没粮”“求文”“能不能擦边写点”等。\n\n"
        "**4. 角色扮演中的叙事切换**\n"
        "在角色扮演对话中，用户突然要求将互动转化为小说形式，例如：“把刚才的对话写成小说体”"
        "“你能不能把这个写下来”“用旁白描述此刻的场景”“给我们这段加个文学转场”"
        "“以你的文风写xx此刻的心理活动”等。\n\n"
        "**5. 写作辅助与卡文救援**\n"
        "用户在创作过程中寻求帮助或样例，例如：“卡文了，你续一下”“帮我想个开头”"
        "“根据这个人设写一段登场”“展示一下xx的说话方式和神态”“这段大纲你写一段我看看效果”"
        "“写个符合设定的日常片段”等。\n\n"
        "**6. 多模态暗示与转化请求**\n"
        "用户提供图片、歌词、表格等非纯文本描述，并希望转化为小说，例如：发图后说“写这个”"
        "“看图说话”“这张图能不能变小说”；粘贴同人图描述后说“写出来”；提供人设卡或关系图后"
        "要求“生成一段互动”；扔来“捡手机”“拾手机”台词要求扩写成聊天记录体小说等。\n\n"
        "**7. 上下文续写与再创作**\n"
        "用户基于 Bot 之前的产出或当前 story 状态提出连续创作需求，例如：“续写上次那个”"
        "“接上次的梦”“再来一段”“不够看”“继续写”“把这段扩展成一个完整场景”"
        "“细化一下刚才的吻戏/打斗”等。\n\n"
        "**8. AU/设定接梗与世界观构建**\n"
        "用户给出特定 AU 设定或世界观后要求产出片段，例如：“来个哨向设定的初遇”"
        "“HP pa 写一段分院仪式”“现pa的日常甜饼”“古风AU里的对峙”“ABO设定下的易感期片段”等。\n\n"
        "**9. 情绪化与饥饿式需求**\n"
        "用户直接表达“想看文”的急切情绪，如：“我真的好想看xx和xx的互动”“谁给我做点xx饭啊”"
        "“这个梗不写天理难容”“不行了必须有人写一段”“我现在立刻就要看到他们接吻”等，"
        "即使未指明由 Bot 创作，也应主动响应。\n\n"
        "**10. 触发防御与主动邀约**\n"
        "当用户表达“不知道你能不能写”“你会写这个吗”“你真的会写同人吗”时，Bot 不仅应回答会，"
        "还应立刻主动输出一小段示例，展示能力，并邀请用户提出更具体需求。\n\n"
        "> **注意**：只要用户表现出“需要一段文字叙事”或“想让 Bot 根据当前人设与背景输出文学片段”，"
        "不论表达完整度如何，均应立即调用本 action。"
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
