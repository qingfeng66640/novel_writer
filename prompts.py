"""novel_writer 提示词模板辅助函数。"""

from __future__ import annotations


def build_managed_chapter_instruction(
    *,
    user_request: str,
    project_context: str,
    continuation_context: str,
    chapter_number: int | None,
    chapter_title: str,
    target_chars: int | None,
) -> str:
    """构建文章管理插件调用的章节生成指令。"""

    parts = ["请生成可直接发布到小说平台的一章正文。"]
    if chapter_number is not None:
        parts.append(f"章节序号：第 {chapter_number} 章。")
    if chapter_title:
        parts.append(f"章节标题：{chapter_title}。")
    if target_chars:
        parts.append(f"目标长度：约 {target_chars} 个中文字符。")
    if project_context:
        parts.append(f"作品设定与管理上下文：\n{project_context}")
    if continuation_context:
        parts.append(f"续写上下文：\n{continuation_context}")
    parts.append(f"用户本次要求：\n{user_request}")
    parts.append("只输出章节正文，不要解释创作过程，不要出现 AI 自述或元说明。")
    return "\n\n".join(parts)
