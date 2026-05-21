"""上下文节点独立测试 — 不依赖真实数据库，mock 验证输入输出"""
import pytest
from unittest.mock import patch, MagicMock
from application.engine.dag.nodes.context_nodes import (
    CharactersNode,
    RecentChaptersNode,
    StorylineNode,
    ContextAssemblerNode,
)
from application.engine.dag.models import NodeResult, NodeStatus


class TestCharactersNode:
    """ctx_characters 节点测试"""

    @pytest.mark.asyncio
    async def test_execute_with_bible_data(self):
        """有角色数据时产出 character_block"""
        mock_char = MagicMock()
        mock_char.name = "张三"
        mock_char.description = "主角，剑客"
        mock_char.mental_state = "ANGRY"
        mock_char.mental_state_reason = "宗门被灭"
        mock_char.verbal_tic = "哼"
        mock_char.idle_behavior = "摸剑柄"
        mock_char.core_belief = "力量即正义"
        mock_char.moral_taboos = ["不杀妇孺"]
        mock_char.active_wounds = [{"description": "左臂旧伤"}]
        mock_char.reveal_chapter = None
        mock_char.public_profile = "冷面剑客"
        mock_char.hidden_profile = ""
        mock_char.relationships = []
        mock_char.character_id = MagicMock()
        mock_char.character_id.value = "char_1"

        mock_bible = MagicMock()
        mock_bible.characters = [mock_char]

        # ★ 节点内部 inline import，需要 patch 源模块
        with (
            patch(
                "infrastructure.persistence.database.sqlite_bible_repository.SqliteBibleRepository"
            ) as mock_bible_repo,
            patch(
                "infrastructure.persistence.database.sqlite_character_state_repository.SqliteCharacterStateRepository"
            ) as mock_state_repo,
        ):
            mock_bible_repo.return_value.get_by_novel_id.return_value = mock_bible
            mock_state_repo.return_value.get_by_novel.return_value = []

            node = CharactersNode()
            result = await node.execute(
                {"novel_id": "test_novel"},
                {"novel_id": "test_novel", "chapter_number": 3},
            )

        assert isinstance(result, NodeResult)
        assert result.status == NodeStatus.SUCCESS
        assert "character_block" in result.outputs
        assert "张三" in result.outputs["character_block"]
        assert "宗门被灭" in result.outputs["character_block"]
        assert "哼" in result.outputs["character_block"]
        assert "力量即正义" in result.outputs["character_block"]
        assert result.outputs["character_count"] == 1

    @pytest.mark.asyncio
    async def test_execute_empty_bible(self):
        """无角色时不崩溃，返回空字符串"""
        mock_bible = MagicMock()
        mock_bible.characters = []

        with (
            patch("infrastructure.persistence.database.sqlite_bible_repository.SqliteBibleRepository") as mock_repo,
            patch("infrastructure.persistence.database.sqlite_character_state_repository.SqliteCharacterStateRepository") as mock_state,
        ):
            mock_repo.return_value.get_by_novel_id.return_value = mock_bible
            mock_state.return_value.get_by_novel.return_value = []

            node = CharactersNode()
            result = await node.execute(
                {"novel_id": "test_novel"},
                {"novel_id": "test_novel"},
            )

        assert result.status == NodeStatus.SUCCESS
        assert result.outputs["character_block"] == ""
        assert result.outputs["character_count"] == 0

    @pytest.mark.asyncio
    async def test_execute_db_error_graceful(self):
        """数据库异常时不崩溃"""
        with (
            patch("infrastructure.persistence.database.sqlite_bible_repository.SqliteBibleRepository") as mock_repo,
        ):
            mock_repo.return_value.get_by_novel_id.side_effect = RuntimeError("DB connection lost")

            node = CharactersNode()
            result = await node.execute(
                {"novel_id": "test_novel"},
                {"novel_id": "test_novel"},
            )

        # 内层 try/except 捕获 DB 异常，输出空值，状态 SUCCESS
        assert result.status == NodeStatus.SUCCESS


class TestContextAssemblerNode:
    """ctx_assembler 节点测试"""

    @pytest.mark.asyncio
    async def test_assembles_t0_fields(self):
        """T0 字段全部纳入 context"""
        node = ContextAssemblerNode()
        result = await node.execute(
            {
                "world_rules": "修真界等级：炼气→筑基",
                "fact_lock": "张三左臂受伤",
                "character_block": "【张三】\n  身份：剑客",
                "previously_on": "第2章：张三进入大殿",
            },
            {"novel_id": "test"},
        )

        assert result.status == NodeStatus.SUCCESS
        ctx = result.outputs["context"]
        assert "修真界等级" in ctx
        assert "张三左臂受伤" in ctx
        assert "剑客" in ctx
        assert "第2章" in ctx
        assert result.outputs["t0_sections"] >= 4
        assert result.outputs["context_tokens"] > 0

    @pytest.mark.asyncio
    async def test_empty_inputs_no_crash(self):
        """全空输入不崩溃"""
        node = ContextAssemblerNode()
        result = await node.execute({}, {"novel_id": "test"})

        assert result.status == NodeStatus.SUCCESS
        assert result.outputs["context"] == ""
        # _estimate_tokens("") returns max(1, 0) = 1
        assert result.outputs["context_tokens"] >= 0

    @pytest.mark.asyncio
    async def test_token_estimation(self):
        """Token 估算逻辑正确"""
        node = ContextAssemblerNode()
        assert node._estimate_tokens("hello") == 7
        assert node._estimate_tokens("你好世界") == 6
        assert node._estimate_tokens("") == 1


class TestRecentChaptersNode:
    """ctx_recent 节点测试"""

    @pytest.mark.asyncio
    async def test_no_summaries_graceful(self):
        """无章节摘要时不崩溃"""
        with patch(
            "infrastructure.persistence.database.connection.get_database"
        ) as mock_db:
            mock_db.return_value.fetch_all.return_value = []
            node = RecentChaptersNode()
            result = await node.execute(
                {"novel_id": "test_novel", "chapter_number": 5},
                {"novel_id": "test_novel", "chapter_number": 5},
            )

        assert result.status == NodeStatus.SUCCESS
        assert result.outputs["previously_on"] == ""


class TestStorylineNode:
    """ctx_storyline 节点测试"""

    @pytest.mark.asyncio
    async def test_no_data_graceful(self):
        """无故事线数据时不崩溃"""
        with patch(
            "infrastructure.persistence.database.connection.get_database"
        ) as mock_db:
            mock_db.return_value.fetch_all.return_value = []
            mock_db.return_value.fetch_one.return_value = None
            with patch(
                "infrastructure.persistence.database.sqlite_causal_edge_repository.SqliteCausalEdgeRepository"
            ) as mock_causal:
                mock_causal.return_value.find_unresolved_by_novel.return_value = []

                node = StorylineNode()
                result = await node.execute(
                    {"novel_id": "test_novel"},
                    {"novel_id": "test_novel"},
                )

            assert result.status == NodeStatus.SUCCESS
