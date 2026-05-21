"""DAG 初始状态构建器

从数据库读取小说的当前状态（章节号、大纲等），组装为 DAGEngine.run() 所需的
initial_state dict。各 Context 节点会在此基础上查询 DB 注入具体上下文数据。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class StateInitializer:
    """构建 DAG 引擎的初始状态

    用法:
        init = StateInitializer()
        state = await init.build(novel_id)
        result = await engine.run(dag, state, thread_id=novel_id)
    """

    async def build(self, novel_id: str, chapter_number: Optional[int] = None) -> Dict[str, Any]:
        """构建初始状态

        Args:
            novel_id: 小说 ID
            chapter_number: 指定章节号（None 则自动定位下一个待写章节）

        Returns:
            包含 novel_id, chapter_number, dag_run_id 等字段的初始状态 dict
        """
        dag_run_id = f"dag_{novel_id}_{int(time.time() * 1000)}"

        state: Dict[str, Any] = {
            "novel_id": novel_id,
            "dag_run_id": dag_run_id,
            "chapter_number": chapter_number or 1,
            "status": "ok",  # 初始无错误
            "drift_alert": False,
            "breaker_status": "closed",
            "review_approved": False,
            "retry_count": 0,
            "node_configs": {},
            "disabled_nodes": [],
        }

        # 如果没有指定章节号，自动定位下一个待写章节
        if chapter_number is None:
            ch = await self._find_next_chapter(novel_id)
            if ch is not None:
                state["chapter_number"] = ch

        # 加载章节大纲
        outline = await self._load_outline(novel_id, state["chapter_number"])
        if outline:
            state["outline"] = outline

        logger.info(
            "DAG 初始状态构建完成: novel=%s, chapter=%s, outline_len=%s",
            novel_id,
            state["chapter_number"],
            len(outline) if outline else 0,
        )
        return state

    async def _find_next_chapter(self, novel_id: str) -> Optional[int]:
        """查找下一个待写章节号"""
        try:
            from domain.novel.value_objects.novel_id import NovelId
            from infrastructure.persistence.database.connection import get_database
            from infrastructure.persistence.database.story_node_repository import StoryNodeRepository

            db = get_database()
            repo = StoryNodeRepository(db)
            nodes = await repo.get_by_novel(novel_id)
            chapter_nodes = sorted(
                [n for n in nodes if getattr(n, 'node_type', None) and str(n.node_type) == "chapter"],
                key=lambda n: n.number,
            )
            # 找到第一个未完成的章节
            for node in chapter_nodes:
                try:
                    from infrastructure.persistence.database.sqlite_chapter_repository import (
                        SqliteChapterRepository,
                    )
                    chapter_repo = SqliteChapterRepository(db)
                    existing = chapter_repo.get_by_novel_and_number(NovelId(novel_id), node.number)
                except Exception:
                    existing = None
                if existing is None or getattr(existing, 'status', '') != 'completed':
                    return node.number
            # 所有章节已完成，返回最后一章 + 1
            if chapter_nodes:
                return chapter_nodes[-1].number + 1
        except Exception as e:
            logger.warning("自动定位章节失败: %s", e)
        return None

    async def _load_outline(self, novel_id: str, chapter_number: int) -> str:
        """加载章节大纲"""
        try:
            from infrastructure.persistence.database.connection import get_database
            from infrastructure.persistence.database.story_node_repository import StoryNodeRepository

            db = get_database()
            repo = StoryNodeRepository(db)
            nodes = await repo.get_by_novel(novel_id)
            for node in nodes:
                if getattr(node, 'number', None) == chapter_number:
                    outline = node.outline or node.description or node.title or ""
                    return str(outline)
        except Exception as e:
            logger.warning("加载大纲失败: %s", e)
        return ""
