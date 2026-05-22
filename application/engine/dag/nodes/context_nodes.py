"""Context 节点 — 上下文注入（5 个节点）

- ctx_blueprint: 剧本基建（世界规则、禁忌、氛围）
- ctx_foreshadow: 伏笔注入器
- ctx_voice: 角色声线注入
- ctx_memory: 记忆引擎
- ctx_debt: 叙事债务注入
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from application.engine.dag.models import (
    DefaultDagSlot,
    NodeCategory,
    NodeMeta,
    NodePort,
    NodeResult,
    NodeStatus,
    PortDataType,
)
from application.engine.dag.registry import BaseNode, NodeRegistry

logger = logging.getLogger(__name__)


# ─── ctx_blueprint: 剧本基建 ───


@NodeRegistry.register("ctx_blueprint")
class BlueprintNode(BaseNode):
    """剧本基建 — 从 BibleService 提取世界规则、禁忌、氛围"""

    meta = NodeMeta(
        node_type="ctx_blueprint",
        display_name="📋 剧本基建",
        category=NodeCategory.CONTEXT,
        icon="📋",
        color="#6366f1",
        input_ports=[
            NodePort(name="novel_id", data_type=PortDataType.TEXT, required=True),
        ],
        output_ports=[
            NodePort(name="world_rules", data_type=PortDataType.TEXT),
            NodePort(name="taboos", data_type=PortDataType.TEXT),
            NodePort(name="atmosphere", data_type=PortDataType.TEXT),
        ],
        prompt_template="提取以下小说的世界观规则和禁忌...",
        prompt_variables=["novel_id"],
        is_configurable=True,
        can_disable=False,
        default_timeout_seconds=30,
        cpms_node_key="context-blueprint",
        description="从 BibleService 提取世界规则、禁忌、氛围",
        default_edges=["ctx_memory", "exec_beat"],
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()
        novel_id = inputs.get("novel_id") or context.get("novel_id", "")

        try:
            world_rules = ""
            taboos = ""
            atmosphere = ""

            try:
                from application.paths import get_db_path
                from application.world.services.narrative_contract_text import build_ctx_blueprint_outputs
                from domain.novel.value_objects.novel_id import NovelId
                from infrastructure.persistence.database.connection import get_database
                from infrastructure.persistence.database.sqlite_bible_repository import SqliteBibleRepository
                from infrastructure.persistence.database.worldbuilding_repository import WorldbuildingRepository

                db = get_database()
                bible_repo = SqliteBibleRepository(db)
                bible = bible_repo.get_by_novel_id(NovelId(novel_id))
                wb_repo = WorldbuildingRepository(get_db_path())
                wb = wb_repo.get_by_novel_id(novel_id)
                out = build_ctx_blueprint_outputs(bible=bible, worldbuilding=wb)
                world_rules = out["world_rules"]
                taboos = out["taboos"]
                atmosphere = out["atmosphere"]
            except Exception as e:
                logger.warning(f"剧本基建(Bible/Worldbuilding)加载失败，使用空值: {e}")

            return NodeResult(
                outputs={"world_rules": world_rules, "taboos": taboos, "atmosphere": atmosphere},
                status=NodeStatus.SUCCESS,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                outputs={},
                status=NodeStatus.ERROR,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return "novel_id" in inputs or True  # novel_id 可从 context 获取


# ─── ctx_foreshadow: 伏笔注入器 ───


@NodeRegistry.register("ctx_foreshadow")
class ForeshadowNode(BaseNode):
    """伏笔注入器 — 从 ContextBudgetAllocator T0 槽提取伏笔信息"""

    meta = NodeMeta(
        node_type="ctx_foreshadow",
        display_name="🪝 伏笔注入器",
        category=NodeCategory.CONTEXT,
        icon="🪝",
        color="#f59e0b",
        input_ports=[
            NodePort(name="novel_id", data_type=PortDataType.TEXT, required=True),
            NodePort(name="chapter_number", data_type=PortDataType.SCORE, required=False),
        ],
        output_ports=[
            NodePort(name="foreshadowing_block", data_type=PortDataType.TEXT),
        ],
        prompt_template="整理以下小说中待回收的伏笔...",
        prompt_variables=["novel_id", "chapter_number"],
        is_configurable=True,
        can_disable=True,
        default_timeout_seconds=30,
        cpms_node_key="context-foreshadow",
        description="从 ContextBudgetAllocator T0 槽提取伏笔信息",
        default_edges=["exec_writer"],
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()
        novel_id = inputs.get("novel_id") or context.get("novel_id", "")

        try:
            foreshadowing_block = ""

            try:
                from domain.novel.repositories.foreshadowing_repository import ForeshadowingRepository
                from infrastructure.persistence.database.connection import get_database
                db = get_database()
                repo = ForeshadowingRepository(db)
                pending = repo.find_pending_by_novel(novel_id)
                if pending:
                    lines = []
                    for f in pending:
                        lines.append(f"【待回收】{f.description}（第{f.planted_chapter}章埋）")
                    foreshadowing_block = "\n".join(lines)
            except Exception as e:
                logger.warning(f"伏笔数据加载失败: {e}")

            return NodeResult(
                outputs={"foreshadowing_block": foreshadowing_block},
                status=NodeStatus.SUCCESS,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                outputs={"foreshadowing_block": ""},
                status=NodeStatus.ERROR,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return True


# ─── ctx_voice: 角色声线注入 ───


@NodeRegistry.register("ctx_voice")
class VoiceNode(BaseNode):
    """角色声线注入 — style_constraint_builder + character_state_vector"""

    meta = NodeMeta(
        node_type="ctx_voice",
        display_name="🎭 角色声线注入",
        category=NodeCategory.CONTEXT,
        icon="🎭",
        color="#ec4899",
        input_ports=[
            NodePort(name="novel_id", data_type=PortDataType.TEXT, required=True),
            NodePort(name="chapter_number", data_type=PortDataType.SCORE, required=False),
        ],
        output_ports=[
            NodePort(name="voice_block", data_type=PortDataType.TEXT),
            NodePort(name="nervous_habits", data_type=PortDataType.TEXT),
        ],
        prompt_template="提取以下章节涉及角色的声线特征...",
        prompt_variables=["novel_id", "chapter_number"],
        is_configurable=True,
        can_disable=True,
        default_timeout_seconds=30,
        cpms_node_key="voice-style-analysis",
        description="style_constraint_builder + character_state_vector",
        default_edges=["exec_writer"],
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()
        novel_id = inputs.get("novel_id") or context.get("novel_id", "")

        try:
            voice_block = ""
            nervous_habits = ""

            try:
                from application.engine.services.style_constraint_builder import build_style_summary
                voice_block = build_style_summary(novel_id)
            except Exception as e:
                logger.warning(f"style_constraint_builder 调用失败: {e}")

            return NodeResult(
                outputs={"voice_block": voice_block, "nervous_habits": nervous_habits},
                status=NodeStatus.SUCCESS,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                outputs={"voice_block": "", "nervous_habits": ""},
                status=NodeStatus.ERROR,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return True


# ─── ctx_memory: 记忆引擎 ───


@NodeRegistry.register("ctx_memory")
class MemoryNode(BaseNode):
    """记忆引擎 — ContextAssembler (feed-forward)"""

    meta = NodeMeta(
        node_type="ctx_memory",
        display_name="🧠 记忆引擎",
        category=NodeCategory.CONTEXT,
        icon="🧠",
        color="#8b5cf6",
        input_ports=[
            NodePort(name="novel_id", data_type=PortDataType.TEXT, required=True),
            NodePort(name="chapter_number", data_type=PortDataType.SCORE, required=False),
        ],
        output_ports=[
            NodePort(name="fact_lock", data_type=PortDataType.TEXT),
            NodePort(name="entity_memory", data_type=PortDataType.TEXT),
        ],
        prompt_template="整理以下小说已确立的事实锁...",
        prompt_variables=["novel_id", "chapter_number"],
        is_configurable=True,
        can_disable=True,
        default_timeout_seconds=30,
        cpms_node_key="context-memory",
        description="ContextAssembler (feed-forward) 记忆注入",
        default_edges=["exec_beat"],
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()
        novel_id = inputs.get("novel_id") or context.get("novel_id", "")

        try:
            fact_lock = ""
            entity_memory = ""

            try:
                from application.engine.services.context_assembler import ContextAssembler
                assembler = ContextAssembler()
                fact_lock = getattr(assembler, "build_fact_lock", lambda x: "")(novel_id)
            except Exception as e:
                logger.warning(f"ContextAssembler 调用失败: {e}")

            return NodeResult(
                outputs={"fact_lock": fact_lock, "entity_memory": entity_memory},
                status=NodeStatus.SUCCESS,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                outputs={"fact_lock": "", "entity_memory": ""},
                status=NodeStatus.ERROR,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return True


# ─── ctx_assembler: 上下文拼装 ───


@NodeRegistry.register("ctx_assembler")
class ContextAssemblerNode(BaseNode):
    """上下文拼装器 — 将所有上下文节点的产出按优先级 + Token 预算拼装为 {{context}}

    这是 DAG 中唯一不查询数据库的纯逻辑节点。
    它从 shared state 中收集所有 ctx_* 节点的输出，按 T0 > T1 > T2 优先级拼装，
    超出 Token 预算时按层级裁剪。

    Token 估算（中英文混合场景）：字符数 × 1.5 ≈ tokens
    """

    # 上下文拼装优先级
    T0_FIELDS = [
        ("world_rules", "【世界规则】"),
        ("taboos", "【禁忌】"),
        ("atmosphere", "【氛围】"),
        ("fact_lock", "【已确立事实】"),
        ("previously_on", "【前情提要】"),
        ("current_act_goal", "【当前幕目标】"),
        ("character_block", "【角色档案】"),
        ("foreshadowing_block", "【待回收伏笔】"),
        ("voice_block", "【角色声线】"),
        ("debt_due_block", "【叙事债务】"),
    ]
    T1_FIELDS = [
        ("storyline_block", "【主线进度】"),
        ("causal_chains", "【因果链】"),
    ]
    T2_FIELDS = [
        ("recent_summary", "【近期章节】"),
    ]

    DEFAULT_MAX_TOKENS = 20000

    meta = NodeMeta(
        node_type="ctx_assembler",
        display_name="🧩 上下文拼装",
        category=NodeCategory.CONTEXT,
        icon="🧩",
        color="#f59e0b",
        input_ports=[
            NodePort(name="world_rules", data_type=PortDataType.TEXT, required=False),
            NodePort(name="taboos", data_type=PortDataType.TEXT, required=False),
            NodePort(name="atmosphere", data_type=PortDataType.TEXT, required=False),
            NodePort(name="fact_lock", data_type=PortDataType.TEXT, required=False),
            NodePort(name="previously_on", data_type=PortDataType.TEXT, required=False),
            NodePort(name="current_act_goal", data_type=PortDataType.TEXT, required=False),
            NodePort(name="character_block", data_type=PortDataType.TEXT, required=False),
            NodePort(name="foreshadowing_block", data_type=PortDataType.TEXT, required=False),
            NodePort(name="voice_block", data_type=PortDataType.TEXT, required=False),
            NodePort(name="debt_due_block", data_type=PortDataType.TEXT, required=False),
            NodePort(name="storyline_block", data_type=PortDataType.TEXT, required=False),
            NodePort(name="causal_chains", data_type=PortDataType.TEXT, required=False),
            NodePort(name="recent_summary", data_type=PortDataType.TEXT, required=False),
            NodePort(name="outline", data_type=PortDataType.TEXT, required=False),
            NodePort(name="beats", data_type=PortDataType.LIST, required=False),
        ],
        output_ports=[
            NodePort(name="context", data_type=PortDataType.TEXT),
            NodePort(name="context_tokens", data_type=PortDataType.SCORE),
            NodePort(name="t0_sections", data_type=PortDataType.SCORE),
            NodePort(name="t1_sections", data_type=PortDataType.SCORE),
            NodePort(name="t2_sections", data_type=PortDataType.SCORE),
        ],
        prompt_template="",
        prompt_variables=[],
        is_configurable=True,
        can_disable=False,
        default_timeout_seconds=10,
        cpms_node_key="",
        description="将所有上下文拼装为 {{context}} 字符串，按 T0>T1>T2 优先级 + Token 预算裁剪",
        default_edges=["exec_writer"],
        default_dag_slot=DefaultDagSlot(
            instance_id="ctx_assembler",
            position={"x": 350, "y": 500},
            incoming_from=[
                "ctx_blueprint", "ctx_memory", "ctx_foreshadow", "ctx_voice",
                "ctx_debt", "ctx_characters", "ctx_recent", "ctx_storyline",
                "exec_beat",
            ],
            outgoing_to=["exec_writer"],
        ),
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()

        try:
            # 从 config.thresholds 读取 max_tokens
            max_tokens = self.DEFAULT_MAX_TOKENS
            if self._config and self._config.thresholds:
                max_tokens = int(self._config.thresholds.get("max_context_tokens", max_tokens))

            sections: list[str] = []
            ctx_tokens = 0
            t0_count = 0
            t1_count = 0
            t2_count = 0

            # T0: 强制槽 — 全部纳入，不裁剪
            for field, label in self.T0_FIELDS:
                text = str(inputs.get(field, "") or "").strip()
                if text:
                    sections.append(f"{label}\n{text}")
                    t0_count += 1

            # 估算当前 Token
            ctx_tokens = self._estimate_tokens("\n\n".join(sections))
            budget_remaining = max_tokens - ctx_tokens

            # T1: 可压缩槽 — 纳入但预算不足时截断
            t1_texts = []
            for field, label in self.T1_FIELDS:
                text = str(inputs.get(field, "") or "").strip()
                if text:
                    t1_texts.append(f"{label}\n{text}")
                    t1_count += 1

            for t1 in t1_texts:
                t1_tokens = self._estimate_tokens(t1)
                if budget_remaining > t1_tokens:
                    sections.append(t1)
                    ctx_tokens += t1_tokens
                    budget_remaining -= t1_tokens
                elif budget_remaining > 100:
                    # 截断纳入
                    truncated = self._truncate_text(t1, budget_remaining)
                    sections.append(truncated)
                    ctx_tokens += self._estimate_tokens(truncated)
                    budget_remaining = 0
                    break

            # T2: 可牺牲槽 — 预算充足时才纳入
            budget_remaining = max_tokens - ctx_tokens
            for field, label in self.T2_FIELDS:
                text = str(inputs.get(field, "") or "").strip()
                if text and budget_remaining > 500:
                    t2_text = f"{label}\n{text}"
                    t2_tokens = self._estimate_tokens(t2_text)
                    if budget_remaining > t2_tokens:
                        sections.append(t2_text)
                        ctx_tokens += t2_tokens
                        budget_remaining -= t2_tokens
                        t2_count += 1
                    else:
                        truncated = self._truncate_text(t2_text, budget_remaining)
                        sections.append(truncated)
                        ctx_tokens += self._estimate_tokens(truncated)
                        t2_count += 1
                        break

            # 拼接最终 context
            context_text = "\n\n".join(sections)

            return NodeResult(
                outputs={
                    "context": context_text,
                    "context_tokens": float(ctx_tokens),
                    "t0_sections": float(t0_count),
                    "t1_sections": float(t1_count),
                    "t2_sections": float(t2_count),
                },
                status=NodeStatus.SUCCESS,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                outputs={"context": "", "context_tokens": 0, "t0_sections": 0, "t1_sections": 0, "t2_sections": 0},
                status=NodeStatus.ERROR,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略估算 Token 数（中英文混合：字符数 × 1.5）"""
        return max(1, int(len(text) * 1.5))

    @staticmethod
    def _truncate_text(text: str, max_tokens: int) -> str:
        """按 Token 预算截断文本"""
        max_chars = max(50, int(max_tokens / 1.5))
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...(截断)"

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return True


# ─── ctx_storyline: 主线进度 ───


@NodeRegistry.register("ctx_storyline")
class StorylineNode(BaseNode):
    """主线进度 — 故事线里程碑 + 未闭环因果链

    告诉 LLM：主线走到哪了、当前幕的目标是什么、有哪些因果链还没收束。
    """

    meta = NodeMeta(
        node_type="ctx_storyline",
        display_name="🧭 主线进度",
        category=NodeCategory.CONTEXT,
        icon="🧭",
        color="#84cc16",
        input_ports=[
            NodePort(name="novel_id", data_type=PortDataType.TEXT, required=True),
            NodePort(name="chapter_number", data_type=PortDataType.SCORE, required=False),
        ],
        output_ports=[
            NodePort(name="storyline_block", data_type=PortDataType.TEXT),
            NodePort(name="causal_chains", data_type=PortDataType.TEXT),
            NodePort(name="current_act_goal", data_type=PortDataType.TEXT),
        ],
        prompt_template="",
        prompt_variables=[],
        is_configurable=True,
        can_disable=True,
        default_timeout_seconds=20,
        cpms_node_key="context-storyline",
        description="从 Storyline/PlotArc/CausalEdge 组装主线进度上下文",
        default_edges=["exec_writer"],
        # ctx_storyline 已在默认 DAG 中，无需 default_dag_slot
        default_dag_slot=None,
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()
        novel_id = inputs.get("novel_id") or context.get("novel_id", "")
        chapter_number = inputs.get("chapter_number") or context.get("chapter_number", 0)

        try:
            storyline_block = ""
            causal_chains = ""
            current_act_goal = ""

            # 1. 读取故事线里程碑
            try:
                from infrastructure.persistence.database.connection import get_database
                db = get_database()
                storylines = db.fetch_all(
                    "SELECT * FROM storylines WHERE novel_id = ? ORDER BY created_at",
                    (novel_id,),
                )
                if storylines:
                    lines = []
                    for sl in storylines[:3]:
                        sl_type = sl.get("storyline_type", "") or ""
                        status = sl.get("status", "") or ""
                        est_start = sl.get("estimated_chapter_start", 0)
                        est_end = sl.get("estimated_chapter_end", 0)
                        current_ms = sl.get("current_milestone_index", 0)

                        # 读里程碑
                        milestones = db.fetch_all(
                            "SELECT * FROM storyline_milestones WHERE storyline_id = ? ORDER BY milestone_order",
                            (sl["id"],),
                        )
                        ms_desc = ""
                        for ms in milestones:
                            if ms["milestone_order"] == current_ms:
                                ms_desc = ms.get("description", "") or ms.get("title", "")
                                break

                        status_map = {"active": "进行中", "completed": "已完成", "planned": "规划中"}
                        status_cn = status_map.get(status, status)
                        lines.append(
                            f"【{sl_type}】{status_cn} "
                            f"(第{est_start}-{est_end}章, 当前里程碑 #{current_ms}: {ms_desc})"
                        )
                    storyline_block = "\n".join(lines)
            except Exception as e:
                logger.warning(f"故事线加载失败: {e}")

            # 2. 读取当前幕目标
            try:
                from infrastructure.persistence.database.connection import get_database
                db = get_database()
                # 从 novels 表读当前 act
                novel = db.fetch_one(
                    "SELECT current_act, current_chapter_in_act FROM novels WHERE id = ?",
                    (novel_id,),
                )
                if novel:
                    act = novel.get("current_act", 0)
                    current_act_goal = f"第{act}幕，幕内第{novel.get('current_chapter_in_act', 0)}章"
            except Exception as e:
                logger.debug(f"读取当前幕失败: {e}")

            # 3. 读取未闭环因果链
            try:
                from infrastructure.persistence.database.sqlite_causal_edge_repository import (
                    SqliteCausalEdgeRepository,
                )
                from infrastructure.persistence.database.connection import get_database
                db = get_database()
                repo = SqliteCausalEdgeRepository(db)
                unresolved = repo.find_unresolved_by_novel(novel_id)
            except Exception as e:
                logger.warning(f"因果边加载失败: {e}")
                unresolved = []

            if unresolved:
                chain_lines = []
                for edge in unresolved[:10]:
                    src = getattr(edge, "source_event_summary", "") or ""
                    tgt = getattr(edge, "target_event_summary", "") or ""
                    ctype = getattr(edge, "causal_type", None)
                    ctype_cn = {
                        "causes": "导致", "motivates": "驱动",
                        "triggers": "触发", "prevents": "阻止", "resolves": "解决",
                    }.get(ctype.value if hasattr(ctype, 'value') else str(ctype), str(ctype))
                    src_ch = getattr(edge, "source_chapter", 0)
                    chain_lines.append(f"• {src}(第{src_ch}章) →[{ctype_cn}]→ {tgt}")
                causal_chains = "未闭环因果链：\n" + "\n".join(chain_lines) if chain_lines else ""

            return NodeResult(
                outputs={
                    "storyline_block": storyline_block,
                    "causal_chains": causal_chains,
                    "current_act_goal": current_act_goal,
                },
                status=NodeStatus.SUCCESS,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                outputs={"storyline_block": "", "causal_chains": "", "current_act_goal": ""},
                status=NodeStatus.ERROR,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return True


# ─── ctx_recent: 前情提要 ───


@NodeRegistry.register("ctx_recent")
class RecentChaptersNode(BaseNode):
    """前情提要 — 从最近 N 章摘要 + 章节内容组装"前文发生了什么"

    帮助 LLM 理解当前章节在整个叙事中的位置，避免情节断裂。
    """

    meta = NodeMeta(
        node_type="ctx_recent",
        display_name="📖 前情提要",
        category=NodeCategory.CONTEXT,
        icon="📖",
        color="#06b6d4",
        input_ports=[
            NodePort(name="novel_id", data_type=PortDataType.TEXT, required=True),
            NodePort(name="chapter_number", data_type=PortDataType.SCORE, required=False),
        ],
        output_ports=[
            NodePort(name="previously_on", data_type=PortDataType.TEXT),
            NodePort(name="recent_summary", data_type=PortDataType.TEXT),
        ],
        prompt_template="",
        prompt_variables=[],
        is_configurable=True,
        can_disable=True,
        default_timeout_seconds=20,
        cpms_node_key="context-recent",
        description="从最近章节摘要组装前情提要",
        default_edges=["exec_writer"],
        default_dag_slot=DefaultDagSlot(
            instance_id="ctx_recent",
            position={"x": 100, "y": 1000},
            outgoing_to=["exec_writer"],
        ),
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()
        novel_id = inputs.get("novel_id") or context.get("novel_id", "")
        chapter_number = inputs.get("chapter_number") or context.get("chapter_number", 0)

        try:
            recent_chapters = 3  # 默认取最近 3 章
            previously_on = ""
            recent_summary = ""

            # 1. 读取章节摘要 (chapter_summaries)
            try:
                from infrastructure.persistence.database.connection import get_database
                db = get_database()
                rows = db.fetch_all(
                    "SELECT cs.chapter_number, cs.summary, cs.key_events, cs.open_threads "
                    "FROM chapter_summaries cs "
                    "JOIN knowledge k ON cs.knowledge_id = k.id "
                    "WHERE k.novel_id = ? AND cs.chapter_number < ? "
                    "ORDER BY cs.chapter_number DESC LIMIT ?",
                    (novel_id, int(chapter_number) if chapter_number else 9999, recent_chapters),
                )
                rows = list(reversed(rows))  # 按章节号升序
            except Exception as e:
                logger.warning(f"章节摘要加载失败: {e}")
                rows = []

            # 2. 组装前情提要
            if rows:
                parts = []
                for row in rows:
                    ch_num = row["chapter_number"]
                    summary = row.get("summary", "") or ""
                    key_events = row.get("key_events", "") or ""
                    open_threads = row.get("open_threads", "") or ""

                    part = f"第{ch_num}章：{summary}"
                    if key_events:
                        part += f"\n  关键事件：{key_events}"
                    if open_threads:
                        part += f"\n  未解问题：{open_threads}"
                    parts.append(part)

                previously_on = "\n\n".join(parts)
                recent_summary = "\n".join(
                    f"第{row['chapter_number']}章：{row.get('summary', '')[:200]}"
                    for row in rows
                )

            return NodeResult(
                outputs={
                    "previously_on": previously_on,
                    "recent_summary": recent_summary,
                },
                status=NodeStatus.SUCCESS,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                outputs={"previously_on": "", "recent_summary": ""},
                status=NodeStatus.ERROR,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return True


# ─── ctx_characters: 角色档案注入 ───


@NodeRegistry.register("ctx_characters")
class CharactersNode(BaseNode):
    """角色档案注入 — 从 Bible + CharacterState 组装角色上下文

    产出包含每个角色的：
    - 姓名、身份描述
    - 当前心理状态 + 原因
    - 口头禅、习惯动作
    - 核心信念、道德禁忌
    - 活跃创伤、伤疤
    - 与其他角色的关系
    """

    meta = NodeMeta(
        node_type="ctx_characters",
        display_name="👤 角色档案",
        category=NodeCategory.CONTEXT,
        icon="👤",
        color="#a855f7",
        input_ports=[
            NodePort(name="novel_id", data_type=PortDataType.TEXT, required=True),
            NodePort(name="chapter_number", data_type=PortDataType.SCORE, required=False),
        ],
        output_ports=[
            NodePort(name="character_block", data_type=PortDataType.TEXT),
            NodePort(name="character_count", data_type=PortDataType.SCORE),
        ],
        prompt_template="整理以下小说中角色的档案信息...",
        prompt_variables=["novel_id"],
        is_configurable=True,
        can_disable=True,
        default_timeout_seconds=30,
        cpms_node_key="context-characters",
        description="从 Bible + CharacterState 组装角色档案上下文",
        default_edges=["exec_writer"],
        default_dag_slot=DefaultDagSlot(
            instance_id="ctx_characters",
            position={"x": 100, "y": 850},
            outgoing_to=["exec_writer"],
        ),
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()
        novel_id = inputs.get("novel_id") or context.get("novel_id", "")
        chapter_number = inputs.get("chapter_number") or context.get("chapter_number", 0)

        try:
            lines: list[str] = []
            character_count = 0

            # 1. 读取角色静态档案 (Bible)
            try:
                from domain.novel.value_objects.novel_id import NovelId
                from infrastructure.persistence.database.connection import get_database
                from infrastructure.persistence.database.sqlite_bible_repository import SqliteBibleRepository

                db = get_database()
                bible_repo = SqliteBibleRepository(db)
                bible = bible_repo.get_by_novel_id(NovelId(novel_id))
                characters = bible.characters if bible else []
            except Exception as e:
                logger.warning(f"角色档案(Bible)加载失败: {e}")
                characters = []

            # 2. 读取角色动态状态 (CharacterState)
            try:
                from infrastructure.persistence.database.sqlite_character_state_repository import (
                    SqliteCharacterStateRepository,
                )
                from infrastructure.persistence.database.connection import get_database
                db = get_database()
                state_repo = SqliteCharacterStateRepository(db)
                all_states = state_repo.get_by_novel(novel_id)
                state_map = {s.character_id: s for s in all_states}
            except Exception as e:
                logger.warning(f"角色状态加载失败: {e}")
                state_map = {}

            # 3. 组装每个角色的文本
            for ch in characters:
                try:
                    block = self._build_character_block(ch, state_map, chapter_number)
                    if block:
                        lines.append(block)
                        character_count += 1
                except Exception as e:
                    logger.debug(f"组装角色 {getattr(ch, 'name', '?')} 失败: {e}")

            character_block = "\n\n".join(lines) if lines else ""

            return NodeResult(
                outputs={
                    "character_block": character_block,
                    "character_count": float(character_count),
                },
                status=NodeStatus.SUCCESS,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                outputs={"character_block": "", "character_count": 0},
                status=NodeStatus.ERROR,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    def _build_character_block(self, ch, state_map: dict, chapter_number: int) -> str:
        """组装单个角色的上下文文本"""
        name = getattr(ch, "name", "") or ""
        if not name:
            return ""

        parts = [f"【{name}】"]

        # 身份描述
        desc = getattr(ch, "description", "") or ""
        if desc:
            parts.append(f"  身份：{desc}")

        # 公开/隐藏信息 (POV 防火墙)
        reveal = getattr(ch, "reveal_chapter", None)
        public = getattr(ch, "public_profile", "") or ""
        hidden = getattr(ch, "hidden_profile", "") or ""
        if public:
            parts.append(f"  公开形象：{public}")
        if hidden:
            if reveal is None or (chapter_number and int(chapter_number) >= int(reveal)):
                parts.append(f"  🔓隐藏身份（第{reveal}章揭示）：{hidden}")
            else:
                parts.append(f"  🔒隐藏身份（第{reveal}章揭示，当前不可见）")

        # 心理状态
        mental = getattr(ch, "mental_state", "") or ""
        mental_reason = getattr(ch, "mental_state_reason", "") or ""
        if mental and mental != "NORMAL":
            reason_str = f"（{mental_reason}）" if mental_reason else ""
            parts.append(f"  心理状态：{mental}{reason_str}")

        # 口头禅 / 习惯动作
        verbal = getattr(ch, "verbal_tic", "") or ""
        idle = getattr(ch, "idle_behavior", "") or ""
        if verbal:
            parts.append(f"  口头禅：{verbal}")
        if idle:
            parts.append(f"  习惯动作：{idle}")

        # 核心信念 / 道德禁忌
        belief = getattr(ch, "core_belief", "") or ""
        taboos = getattr(ch, "moral_taboos", None) or []
        if belief:
            parts.append(f"  核心信念：{belief}")
        if taboos:
            parts.append(f"  道德禁忌：{'、'.join(taboos)}")

        # 活跃创伤
        wounds = getattr(ch, "active_wounds", None) or []
        if wounds:
            wound_strs = []
            for w in wounds:
                if isinstance(w, dict):
                    wound_strs.append(w.get("description", str(w)))
                else:
                    wound_strs.append(str(w))
            parts.append(f"  创伤：{'；'.join(wound_strs)}")

        # 动态状态 (CharacterState)
        char_id = getattr(getattr(ch, "character_id", None), "value", None) or str(getattr(ch, "id", ""))
        state = state_map.get(char_id)
        if state:
            summary = getattr(state, "current_state_summary", "") or ""
            if summary:
                parts.append(f"  当前状态：{summary}")

            # 活跃伤疤
            try:
                active_scars = state.get_active_scars() if callable(getattr(state, "get_active_scars", None)) else []
                if active_scars:
                    scar_strs = [s.description if hasattr(s, "description") else str(s) for s in active_scars]
                    parts.append(f"  活跃伤疤：{'；'.join(scar_strs)}")
            except Exception:
                pass

            # 当前动机
            try:
                motivations = getattr(state, "motivations", None) or []
                active_motivations = [m for m in motivations if getattr(m, "active", True)]
                if active_motivations:
                    mot_strs = [m.description if hasattr(m, "description") else str(m) for m in active_motivations[:3]]
                    parts.append(f"  当前动机：{'；'.join(mot_strs)}")
            except Exception:
                pass

        # 关系
        relationships = getattr(ch, "relationships", None) or []
        if relationships:
            rel_strs = []
            for r in relationships:
                if isinstance(r, dict):
                    target = r.get("target_name", "") or r.get("name", "")
                    rel = r.get("relation", "") or r.get("description", "")
                    if target:
                        rel_strs.append(f"{target}({rel})" if rel else target)
                elif isinstance(r, str):
                    rel_strs.append(r)
            if rel_strs:
                parts.append(f"  关系：{'、'.join(rel_strs[:10])}")

        return "\n".join(parts)

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return True


# ─── ctx_debt: 叙事债务注入 ───


@NodeRegistry.register("ctx_debt")
class DebtNode(BaseNode):
    """叙事债务注入 — ContextAssembler DEBT_DUE 槽"""

    meta = NodeMeta(
        node_type="ctx_debt",
        display_name="💰 叙事债务",
        category=NodeCategory.CONTEXT,
        icon="💰",
        color="#f97316",
        input_ports=[
            NodePort(name="novel_id", data_type=PortDataType.TEXT, required=True),
        ],
        output_ports=[
            NodePort(name="debt_due_block", data_type=PortDataType.TEXT),
        ],
        prompt_template="整理以下小说中到期应还的叙事债务...",
        prompt_variables=["novel_id"],
        is_configurable=True,
        can_disable=True,
        default_timeout_seconds=20,
        cpms_node_key="context-debt",
        description="ContextAssembler DEBT_DUE 槽注入",
        default_edges=["exec_writer"],
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()
        novel_id = inputs.get("novel_id") or context.get("novel_id", "")

        try:
            debt_due_block = ""

            try:
                from domain.novel.repositories.narrative_debt_repository import NarrativeDebtRepository
                from infrastructure.persistence.database.connection import get_database
                db = get_database()
                repo = NarrativeDebtRepository(db)
                debts = repo.find_due_by_novel(novel_id)
                if debts:
                    lines = [f"【到期】{d.description}" for d in debts]
                    debt_due_block = "\n".join(lines)
            except Exception as e:
                logger.warning(f"叙事债务加载失败: {e}")

            return NodeResult(
                outputs={"debt_due_block": debt_due_block},
                status=NodeStatus.SUCCESS,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                outputs={"debt_due_block": ""},
                status=NodeStatus.ERROR,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return True
