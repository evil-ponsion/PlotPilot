"""DAG 管理 REST API — 节点编排层路由

设计原则：
- DAG 支持完整的 CRUD：用户可保存/加载/编辑自定义 DAG 拓扑
- 节点注册是代码行为，写一个节点就注册一个
- 执行权在全托管模式，DAG 定义由用户编排
- DAG 定义持久化到 SQLite dag_versions 表（支持版本历史 + 回滚）

路由分组：
- 健康检查: GET /dag/health/dag
- 节点类型注册表: GET /dag/registry/types, /dag/registry/types/{node_type}
- DAG↔CPMS 联动内核: GET /dag/registry/linkage
- SSE 事件流: GET /dag/events?novel_id=xxx
- DAG 定义: GET /dag/{novel_id}（读取）, PUT /dag/{novel_id}（保存）
- DAG 版本历史: GET /dag/{novel_id}/versions
- 节点详情: GET /dag/{novel_id}/nodes/{node_id}
- 节点启禁用: POST /dag/{novel_id}/nodes/{node_id}/toggle
- 运行状态: GET /dag/{novel_id}/status
- 提示词来源: GET /dag/{novel_id}/nodes/{node_id}/prompt-live

注意：静态路由（registry, health, events）必须定义在参数化路由（/{novel_id}）之前，
否则 FastAPI 会将 "registry", "health", "events" 当作 novel_id 参数匹配。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from application.engine.dag.models import (
    DAGDefinition,
    EdgeCondition,
    EdgeDefinition,
    NodeConfig,
    NodeDefinition,
    NodeMeta,
    NodeRunState,
    NodeStatus,
    get_default_dag,
)
from application.engine.dag.registry import NodeRegistry
from application.engine.narrative_projection.dag_runtime_projection import (
    node_states_to_sse_events,
    project_node_states,
    snapshot_from_shared,
)
from application.engine.narrative_projection.linkage_kernel import linkage_bundle
from interfaces.api.dependencies import get_dag_version_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dag", tags=["DAG 工作流"])

# ─── 全局单例 ───

# SSE 事件订阅者管理
_sse_subscribers: Dict[str, List[asyncio.Queue]] = {}  # novel_id -> [Queue]


def _get_dag_for_novel(novel_id: str) -> DAGDefinition:
    """获取小说的 DAG 定义（DB 优先，降级到默认 DAG）"""
    try:
        repo = get_dag_version_repository()
        dag = repo.get_latest(novel_id)
        if dag is not None:
            return dag
    except Exception as e:
        logger.warning(f"读取 DAG 版本失败（novel={novel_id}），降级到默认 DAG: {e}")
    return get_default_dag()


def _save_dag_for_novel(novel_id: str, dag: DAGDefinition) -> int:
    """持久化 DAG 定义到数据库，返回新版本号"""
    repo = get_dag_version_repository()
    return repo.save(novel_id, dag)


def publish_sse_event(novel_id: str, event_data: dict):
    """向指定小说的 SSE 订阅者推送事件"""
    subscribers = _sse_subscribers.get(novel_id, [])
    dead_queues = []
    for queue in subscribers:
        try:
            queue.put_nowait(event_data)
        except asyncio.QueueFull:
            dead_queues.append(queue)
    # 清理满队列
    for q in dead_queues:
        subscribers.remove(q)


# ─── Request/Response Models ───


class DAGStatusResponse(BaseModel):
    """DAG 运行状态响应"""
    novel_id: str
    dag_enabled: bool
    current_version: int
    node_states: Dict[str, Dict[str, Any]]


# ═══════════════════════════════════════════════════════════════
# 静态路由 — 必须在 /{novel_id} 参数化路由之前定义
# ═══════════════════════════════════════════════════════════════


# ─── 健康检查 ───


@router.get("/health/dag")
async def dag_health_check():
    """DAG 引擎健康检查"""
    checks = {}

    # 节点注册表
    checks["node_registry"] = {
        "registered_types": len(NodeRegistry.all_types()),
        "types": sorted(NodeRegistry.all_types()),
    }

    # SSE 订阅者统计
    total_subscribers = sum(len(qs) for qs in _sse_subscribers.values())
    checks["sse"] = {
        "active_novels": len(_sse_subscribers),
        "total_subscribers": total_subscribers,
    }

    overall = "ok" if all(
        c.get("status") != "error" for c in checks.values()
    ) else "degraded"

    return {"status": overall, "checks": checks}


# ─── 节点类型注册表 ───


@router.get("/registry/types")
async def list_node_types():
    """获取所有已注册的节点类型"""
    metas = NodeRegistry.all_meta()
    return {
        "types": {
            node_type: meta.model_dump(mode="json")
            for node_type, meta in metas.items()
        }
    }


@router.get("/registry/types/{node_type}")
async def get_node_type_meta(node_type: str):
    """获取单个节点类型的元数据"""
    try:
        meta = NodeRegistry.get_meta(node_type)
        return meta.model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail=f"节点类型 '{node_type}' 未注册")


@router.get("/registry/linkage")
async def get_dag_registry_linkage():
    """DAG 默认画布与 CPMS 一一对应表 + 全类型 CPMS 索引（单一联动内核导出）。"""
    return linkage_bundle()


# ─── SSE 事件流 ───


@router.get("/events")
async def dag_event_stream(novel_id: str = Query(..., description="小说 ID")):
    """SSE 事件流 — 前端实时接收节点状态变更"""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    # 注册订阅者
    if novel_id not in _sse_subscribers:
        _sse_subscribers[novel_id] = []
    _sse_subscribers[novel_id].append(queue)

    async def event_generator():
        try:
            from interfaces.main import get_shared_novel_state

            # 发送初始连接确认
            yield f"event: connected\ndata: {json.dumps({'novel_id': novel_id, 'timestamp': time.time()})}\n\n"

            prev_proj: Dict[str, Dict[str, Any]] = {}
            projection_bootstrapped = False
            idle_ticks = 0

            while True:
                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    idle_ticks = 0
                    event_type = event_data.get("type", "message")
                    yield f"event: {event_type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    idle_ticks += 1
                    event_data = None

                dag = _get_dag_for_novel(novel_id)
                shared = get_shared_novel_state(novel_id)
                snap = snapshot_from_shared(novel_id, shared)
                node_ids = [(n.id, n.type, n.enabled) for n in dag.nodes]
                new_proj = project_node_states(node_ids, snap)
                if not projection_bootstrapped:
                    prev_proj = new_proj
                    projection_bootstrapped = True
                else:
                    for ev in node_states_to_sse_events(novel_id, prev_proj, new_proj):
                        et = ev.get("type", "node_status_change")
                        yield f"event: {et}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
                    prev_proj = new_proj
                if idle_ticks >= 30:
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': time.time()})}\n\n"
                    idle_ticks = 0
        except asyncio.CancelledError:
            pass
        finally:
            if novel_id in _sse_subscribers:
                try:
                    _sse_subscribers[novel_id].remove(queue)
                    if not _sse_subscribers[novel_id]:
                        del _sse_subscribers[novel_id]
                except ValueError:
                    pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════════════════════════
# 参数化路由 — /{novel_id}
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# DAG 模板市场 — 保存/加载/应用可复用的 DAG 模板
# ═══════════════════════════════════════════════════════════════

TEMPLATE_NOVEL_PREFIX = "@tmpl:"  # 不含 SQL LIKE 通配符 (_ % )


class SaveTemplateRequest(BaseModel):
    """保存 DAG 模板请求"""
    name: str = Field(..., description="模板名称（唯一标识）", pattern=r"^[a-zA-Z0-9_\-\u4e00-\u9fff]+$")
    nodes: List[Dict[str, Any]] = Field(..., description="节点定义列表")
    edges: List[Dict[str, Any]] = Field(default_factory=list, description="边定义列表")
    description: Optional[str] = Field(default="", description="模板描述")
    category: Optional[str] = Field(default="custom", description="分类: custom / genre / workflow")


@router.post("/templates")
async def save_template(request: SaveTemplateRequest):
    """保存 DAG 为可复用模板"""
    template_id = f"{TEMPLATE_NOVEL_PREFIX}{request.name}"

    nodes = []
    for n in request.nodes:
        try:
            nodes.append(NodeDefinition(**n))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"节点 '{n.get('id', '?')}' 解析失败: {e}")

    edges = []
    for e in request.edges:
        try:
            edges.append(EdgeDefinition(**e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"边 '{e.get('id', '?')}' 解析失败: {e}")

    dag = DAGDefinition(
        id=f"dag_template_{request.name}",
        name=request.name,
        description=request.description or "",
        nodes=nodes,
        edges=edges,
    )

    try:
        repo = get_dag_version_repository()
        version = repo.save(template_id, dag)
        return {"status": "saved", "name": request.name, "version": version}
    except Exception as e:
        logger.error(f"模板保存失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存模板失败: {e}")


@router.get("/templates")
async def list_templates():
    """列出所有 DAG 模板（内置默认模板 + 用户保存的模板）"""
    try:
        repo = get_dag_version_repository()

        # ★ 内置默认模板始终可用
        default_dag = get_default_dag()
        result = [{
            "name": "默认全流程",
            "description": "内置单幕全流程 DAG，含 17 个节点（ctx → exec → val → gw）",
            "node_count": len(default_dag.nodes),
            "edge_count": len(default_dag.edges),
            "version": 0,
            "updated_at": "",
            "builtin": True,
        }]

        # 用户保存的模板
        from infrastructure.persistence.database.connection import get_database
        db = get_database()
        rows = db.fetch_all(
            "SELECT DISTINCT novel_id, version, name, description, updated_at FROM dag_versions "
            "WHERE novel_id LIKE ? ORDER BY updated_at DESC",
            (f"{TEMPLATE_NOVEL_PREFIX}%",)
        )
        seen = {"默认全流程"}
        for row in rows:
            name = row["novel_id"][len(TEMPLATE_NOVEL_PREFIX):]
            if name in seen:
                continue
            seen.add(name)
            dag = repo.get_latest(row["novel_id"])
            result.append({
                "name": name,
                "description": row.get("description", "") or (dag.description if dag else ""),
                "node_count": len(dag.nodes) if dag else 0,
                "edge_count": len(dag.edges) if dag else 0,
                "version": row["version"],
                "updated_at": row["updated_at"],
                "builtin": False,
            })
        return {"templates": result}
    except Exception as e:
        logger.error(f"获取模板列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取模板列表失败: {e}")


@router.get("/templates/{name}")
async def get_template(name: str):
    """获取指定模板的完整定义"""
    try:
        if name == "默认全流程":
            dag = get_default_dag()
        else:
            template_id = f"{TEMPLATE_NOVEL_PREFIX}{name}"
            repo = get_dag_version_repository()
            dag = repo.get_latest(template_id)
            if dag is None:
                raise HTTPException(status_code=404, detail=f"模板 '{name}' 不存在")
        return dag.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取模板失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取模板失败: {e}")


@router.post("/{novel_id}/apply-template/{template_name}")
async def apply_template(novel_id: str, template_name: str):
    """将模板应用到指定小说（覆盖当前 DAG，保存为新版本）"""
    try:
        repo = get_dag_version_repository()

        # ★ 内置模板「默认全流程」直接走 get_default_dag()
        if template_name == "默认全流程":
            template = get_default_dag()
        else:
            template_id = f"{TEMPLATE_NOVEL_PREFIX}{template_name}"
            template = repo.get_latest(template_id)
            if template is None:
                raise HTTPException(status_code=404, detail=f"模板 '{template_name}' 不存在")

        dag = DAGDefinition(
            id=f"dag_novel_{novel_id}",
            name=f"从模板「{template_name}」加载",
            description=f"基于模板 {template_name}",
            nodes=template.nodes,
            edges=template.edges,
        )

        version = repo.save(novel_id, dag)
        return {"status": "applied", "novel_id": novel_id, "template": template_name, "version": version}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"应用模板失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"应用模板失败: {e}")


# ─── DAG 定义（读写） ───


@router.post("/{novel_id}/new")
async def new_blank_dag(novel_id: str, name: str = "空白画布"):
    """创建空白 DAG（覆盖已有 DAG，保存为新版本）

    前端点击「新建」时调用，生成一个空节点/边的 DAG 作为编辑起点。
    可选 ?name=xxx 指定工作流名称。
    """
    dag = DAGDefinition(
        id=f"dag_novel_{novel_id}",
        name=name or "空白画布",
        description="从零开始编排",
        nodes=[],
        edges=[],
    )
    try:
        version = _save_dag_for_novel(novel_id, dag)
        return {"status": "created", "novel_id": novel_id, "version": version}
    except Exception as e:
        logger.error(f"创建空白 DAG 失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"创建失败: {e}")


@router.get("/{novel_id}")
async def get_dag(novel_id: str):
    """获取当前 DAG 定义"""
    dag = _get_dag_for_novel(novel_id)
    return dag.model_dump(mode="json")


class SaveDAGRequest(BaseModel):
    """保存 DAG 定义请求"""
    nodes: List[Dict[str, Any]] = Field(..., description="节点定义列表")
    edges: List[Dict[str, Any]] = Field(default_factory=list, description="边定义列表")
    name: Optional[str] = Field(default=None, description="DAG 名称")
    description: Optional[str] = Field(default="", description="DAG 描述")


@router.put("/{novel_id}")
async def save_dag(novel_id: str, request: SaveDAGRequest):
    """保存 DAG 定义（完整拓扑 + 节点配置）

    前端画布编辑完成后调用此接口保存整个 DAG 拓扑。
    自动递增版本号，fingerprint 去重（结构无变化时不创建新版本）。
    """
    # 反序列化节点
    nodes = []
    for n in request.nodes:
        try:
            nodes.append(NodeDefinition(**n))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"节点 '{n.get('id', '?')}' 解析失败: {e}")

    # 反序列化边
    edges = []
    for e in request.edges:
        try:
            edges.append(EdgeDefinition(**e))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"边 '{e.get('id', '?')}' 解析失败: {e}")

    # 构建 DAG 定义
    dag = DAGDefinition(
        id=f"dag_novel_{novel_id}",
        name=request.name or f"自定义 DAG — {novel_id}",
        description=request.description or "",
        nodes=nodes,
        edges=edges,
    )

    # 校验（空 DAG 跳过）
    if dag.nodes or dag.edges:
        from application.engine.dag.engine import DAGEngine
        engine = DAGEngine()
        errors = engine.validate(dag)
        if errors:
            raise HTTPException(status_code=400, detail={"message": "DAG 校验失败", "errors": errors})

    # 持久化
    try:
        version = _save_dag_for_novel(novel_id, dag)
        logger.info(f"DAG 保存成功: novel={novel_id}, version={version}")
        return {"status": "saved", "novel_id": novel_id, "version": version}
    except Exception as e:
        logger.error(f"DAG 保存失败: novel={novel_id}, error={e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"保存失败: {e}")


# ─── DAG 版本历史 ───


@router.get("/{novel_id}/versions")
async def list_dag_versions(novel_id: str):
    """列出可用工作流"""
    try:
        repo = get_dag_version_repository()
        versions = repo.list_versions(novel_id)

        # v0：默认全流程 21 节点
        default = get_default_dag()
        versions.insert(0, {
            "version": 0,
            "name": "默认全流程",
            "node_count": len(default.nodes),
            "updated_at": "",
        })

        # v-1：精简全流程 17 节点（去掉 P1 新增的 ctx_characters/ctx_recent/ctx_storyline）
        compact = _build_compact_dag()
        versions.insert(0, {
            "version": -1,
            "name": "精简全流程（16节点）",
            "node_count": len(compact.nodes),
            "updated_at": "",
        })

        return {"novel_id": novel_id, "versions": versions}
    except Exception as e:
        logger.error(f"获取 DAG 版本列表失败: novel={novel_id}, error={e}")
        raise HTTPException(status_code=500, detail=f"获取版本列表失败: {e}")


def _build_compact_dag() -> DAGDefinition:
    """16 节点精简版 — 21 节点去掉 ctx_characters/ctx_recent/ctx_storyline/ctx_assembler"""
    dag = DAGDefinition(
        id="dag_compact_16",
        name="单幕全流程（16节点）",
        version=1,
        nodes=[
            NodeDefinition(id="ctx_blueprint", type="ctx_blueprint", label="📋 剧本基建", position={"x": 100, "y": 100}),
            NodeDefinition(id="ctx_memory", type="ctx_memory", label="🧠 记忆引擎", position={"x": 100, "y": 250}),
            NodeDefinition(id="ctx_foreshadow", type="ctx_foreshadow", label="🪝 伏笔注入器", position={"x": 100, "y": 400}),
            NodeDefinition(id="ctx_voice", type="ctx_voice", label="🎭 角色声线注入", position={"x": 100, "y": 550}),
            NodeDefinition(id="ctx_debt", type="ctx_debt", label="💰 叙事债务", position={"x": 100, "y": 700}),
            NodeDefinition(id="exec_beat", type="exec_beat", label="🥁 节拍放大器", position={"x": 500, "y": 200}),
            NodeDefinition(id="exec_writer", type="exec_writer", label="✍️ 剧情引擎", position={"x": 800, "y": 300},
                config=NodeConfig(prompt_template="写作姿态：回忆并讲述这段事；避免写成交差用的说明文。\n\n{{context}}\n{{outline}}\n{{voice_block}}",
                    prompt_variables={"context": "", "outline": "", "voice_block": ""})),
            NodeDefinition(id="val_style", type="val_style", label="🎭 文风警报器", position={"x": 1200, "y": 100},
                config=NodeConfig(thresholds={"drift_warning": 0.5, "drift_critical": 0.75})),
            NodeDefinition(id="val_tension", type="val_tension", label="📈 张力评估器", position={"x": 1200, "y": 300},
                config=NodeConfig(thresholds={"tension_floor": 30, "tension_ceiling": 85})),
            NodeDefinition(id="val_anti_ai", type="val_anti_ai", label="🛡️ Anti-AI 审计", position={"x": 1200, "y": 500}),
            NodeDefinition(id="gw_circuit", type="gw_circuit", label="🔌 熔断保护", position={"x": 1500, "y": 300},
                config=NodeConfig(thresholds={"max_errors": 3})),
            NodeDefinition(id="gw_retry", type="gw_retry", label="🔄 重写网关", position={"x": 1500, "y": 100},
                config=NodeConfig(max_retries=2)),
            NodeDefinition(id="val_narrative", type="val_narrative", label="🧬 叙事同步", position={"x": 1800, "y": 200}),
            NodeDefinition(id="val_foreshadow", type="val_foreshadow", label="📖 伏笔雷达", position={"x": 1800, "y": 400}),
            NodeDefinition(id="val_kg_infer", type="val_kg_infer", label="🕸️ KG推断", position={"x": 1800, "y": 600}),
            NodeDefinition(id="gw_review", type="gw_review", label="⏸️ 审阅网关", position={"x": 2100, "y": 400}),
        ],
        edges=[
            # ctx → exec_beat → exec_writer
            EdgeDefinition(id="edge_01", source="ctx_blueprint", target="exec_beat", source_port="world_rules"),
            EdgeDefinition(id="edge_02", source="ctx_memory", target="exec_beat", source_port="fact_lock"),
            # ctx 直连 exec_writer（无 assembler）
            EdgeDefinition(id="edge_03", source="ctx_foreshadow", target="exec_writer", source_port="foreshadowing_block"),
            EdgeDefinition(id="edge_04", source="ctx_voice", target="exec_writer", source_port="voice_block"),
            EdgeDefinition(id="edge_05", source="ctx_debt", target="exec_writer", source_port="debt_due_block"),
            EdgeDefinition(id="edge_06", source="exec_beat", target="exec_writer", source_port="beats"),
            # exec_writer → 验证层
            EdgeDefinition(id="edge_07", source="exec_writer", target="val_style", source_port="content"),
            EdgeDefinition(id="edge_08", source="exec_writer", target="val_tension", source_port="content"),
            EdgeDefinition(id="edge_09", source="exec_writer", target="val_anti_ai", source_port="content"),
            # 网关层
            EdgeDefinition(id="edge_10", source="val_style", target="gw_circuit", condition=EdgeCondition.ON_NO_DRIFT),
            EdgeDefinition(id="edge_11", source="val_style", target="gw_retry", condition=EdgeCondition.ON_DRIFT_ALERT, animated=True),
            EdgeDefinition(id="edge_12", source="val_tension", target="gw_circuit"),
            EdgeDefinition(id="edge_13", source="val_anti_ai", target="gw_circuit"),
            EdgeDefinition(id="edge_14", source="gw_circuit", target="val_narrative", condition=EdgeCondition.ON_BREAKER_CLOSED),
            EdgeDefinition(id="edge_15", source="gw_retry", target="exec_writer", animated=True),
            EdgeDefinition(id="edge_16", source="val_narrative", target="val_foreshadow"),
            EdgeDefinition(id="edge_17", source="val_foreshadow", target="val_kg_infer"),
            EdgeDefinition(id="edge_18", source="val_kg_infer", target="gw_review"),
        ],
    )
    return dag


@router.delete("/{novel_id}/versions/{version}")
async def delete_dag_version(novel_id: str, version: int):
    """删除指定版本的 DAG"""
    if version <= 0:
        raise HTTPException(status_code=400, detail="内置工作流不可删除")
    try:
        from infrastructure.persistence.database.connection import get_database
        db = get_database()
        db.execute("DELETE FROM dag_versions WHERE novel_id = ? AND version = ?", (novel_id, version))
        db.commit()
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"删除版本失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")


@router.get("/{novel_id}/versions/{version}")
async def get_dag_version(novel_id: str, version: int):
    """获取指定版本的 DAG 定义"""
    try:
        # 内置 DAG
        if version == 0:
            return get_default_dag().model_dump(mode="json")
        if version == -1:
            return _build_compact_dag().model_dump(mode="json")

        repo = get_dag_version_repository()

        # 模板版本（10000+偏移，已废弃但保留兼容）
        if version >= 10000:
            from infrastructure.persistence.database.connection import get_database
            db = get_database()
            row = db.fetch_one(
                "SELECT novel_id FROM dag_versions WHERE novel_id LIKE ? AND version = ?",
                ("@tmpl:%", version - 10000)
            )
            if row:
                dag = repo.get_by_version(row["novel_id"], version - 10000)
                if dag:
                    return dag.model_dump(mode="json")

        # 普通版本
        dag = repo.get_by_version(novel_id, version)
        if dag is None:
            raise HTTPException(status_code=404, detail=f"版本 {version} 不存在")
        return dag.model_dump(mode="json")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取 DAG 版本失败: novel={novel_id}, version={version}, error={e}")
        raise HTTPException(status_code=500, detail=f"获取版本失败: {e}")


# ═══════════════════════════════════════════════════════════════
# 质量体系 — 章节质量概览 + A/B 对比
# ═══════════════════════════════════════════════════════════════


@router.get("/{novel_id}/quality-overview")
async def quality_overview(novel_id: str):
    """章节质量概览 — 全章节张力/文风/字数趋势 + 异常检测

    返回每章的：张力分、文风相似度、字数、DAG 版本
    以及汇总：均值、趋势、异常章节标记
    """
    try:
        from infrastructure.persistence.database.connection import get_database
        db = get_database()

        # 章节基础数据
        chapters = db.fetch_all(
            "SELECT number, word_count, status, tension_score, dag_version_id, dag_fingerprint, created_at "
            "FROM chapters WHERE novel_id = ? ORDER BY number",
            (novel_id,),
        )

        # 文风数据
        style_rows = db.fetch_all(
            "SELECT chapter_number, similarity_score, adjective_density, avg_sentence_length, sentence_count "
            "FROM chapter_style_scores WHERE novel_id = ? ORDER BY chapter_number",
            (novel_id,),
        )
        style_map = {r["chapter_number"]: dict(r) for r in style_rows}

        # 组装
        chapter_metrics = []
        tension_values = []
        similarity_values = []
        word_counts = []

        for ch in chapters:
            num = ch["number"]
            style = style_map.get(num, {})
            metrics = {
                "chapter_number": num,
                "word_count": ch["word_count"] or 0,
                "status": ch["status"] or "draft",
                "tension_score": ch["tension_score"] or 0,
                "similarity_score": style.get("similarity_score"),
                "adjective_density": style.get("adjective_density"),
                "avg_sentence_length": style.get("avg_sentence_length"),
                "dag_version": ch["dag_version_id"],
                "dag_fingerprint": (ch.get("dag_fingerprint") or "")[:8],
            }
            chapter_metrics.append(metrics)

            if ch["tension_score"]:
                tension_values.append(float(ch["tension_score"]))
            if style.get("similarity_score") is not None:
                similarity_values.append(float(style["similarity_score"]))
            if ch["word_count"]:
                word_counts.append(int(ch["word_count"]))

        # 汇总
        def avg(vals): return round(sum(vals) / len(vals), 1) if vals else 0

        # 异常检测
        anomalies = []
        for i, m in enumerate(chapter_metrics):
            issues = []
            if m["tension_score"] and m["tension_score"] < 30:
                issues.append("tension_low")
            if m["tension_score"] and m["tension_score"] > 90:
                issues.append("tension_high")
            if m["similarity_score"] is not None and m["similarity_score"] < 0.65:
                issues.append("voice_drift")
            if i > 0:
                prev = chapter_metrics[i - 1]
                if m["tension_score"] and prev["tension_score"]:
                    jump = abs(m["tension_score"] - prev["tension_score"])
                    if jump > 30:
                        issues.append(f"tension_jump_{int(jump)}")
            if issues:
                anomalies.append({"chapter_number": m["chapter_number"], "issues": issues})

        return {
            "novel_id": novel_id,
            "total_chapters": len(chapter_metrics),
            "completed_chapters": sum(1 for m in chapter_metrics if m["status"] == "completed"),
            "summary": {
                "avg_tension": avg(tension_values),
                "avg_similarity": avg(similarity_values),
                "avg_word_count": avg(word_counts),
                "total_words": sum(word_counts),
            },
            "chapters": chapter_metrics,
            "anomalies": anomalies,
        }
    except Exception as e:
        logger.error(f"质量概览失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取质量概览失败: {e}")


@router.post("/{novel_id}/preview-context")
async def preview_context(novel_id: str, chapter_number: Optional[int] = Query(default=None)):
    """干跑所有上下文节点，返回上下文预览

    不执行生成，只运行 ctx_* 节点收集它们会产出的上下文数据。
    前端据此展示"本章将使用哪些上下文"。
    """
    from application.engine.dag.state_initializer import StateInitializer

    initializer = StateInitializer()
    state = await initializer.build(novel_id, chapter_number)

    # 收集所有 ctx_ 节点的类型
    ctx_types = [t for t in NodeRegistry.all_types() if t.startswith("ctx_")]
    preview: Dict[str, Any] = {
        "novel_id": novel_id,
        "chapter_number": state.get("chapter_number", 0),
        "sections": [],
        "total_estimated_tokens": 0,
    }

    # 逐个运行上下文节点（忽略拓扑依赖，ctx 节点之间独立）
    for node_type in ctx_types:
        try:
            meta = NodeRegistry.get_meta(node_type)
            instance = NodeRegistry.create_instance(node_type)
            inputs = {}
            for port in meta.input_ports:
                val = state.get(port.name)
                if val is not None:
                    inputs[port.name] = val
                elif port.default is not None:
                    inputs[port.name] = port.default

            context_data = {
                "novel_id": state.get("novel_id", ""),
                "chapter_number": state.get("chapter_number", 0),
                "dag_run_id": "preview",
                "shared_state": state,
                "config_overrides": {},
            }
            result = await instance.execute(inputs, context_data)
            outputs = result.outputs if hasattr(result, 'outputs') else {}

            for port in meta.output_ports:
                text = str(outputs.get(port.name, "") or "")
                if text.strip():
                    est_tokens = max(1, int(len(text) * 1.5))
                    preview["sections"].append({
                        "node_type": node_type,
                        "node_label": meta.display_name or node_type,
                        "port": port.name,
                        "content": text,
                        "estimated_tokens": est_tokens,
                    })
                    preview["total_estimated_tokens"] += est_tokens
        except Exception as e:
            logger.warning(f"预览上下文节点 {node_type} 失败: {e}")
            preview["sections"].append({
                "node_type": node_type,
                "node_label": node_type,
                "port": "error",
                "content": f"加载失败: {e}",
                "estimated_tokens": 0,
            })

    return preview


@router.post("/{novel_id}/preview-beats")
async def preview_beats(novel_id: str, chapter_number: Optional[int] = Query(default=None)):
    """干跑 exec_beat 节点，返回节拍规划

    不执行生成，只运行节拍放大逻辑，返回可编辑的节拍列表。
    """
    from application.engine.dag.state_initializer import StateInitializer

    initializer = StateInitializer()
    state = await initializer.build(novel_id, chapter_number)

    # 先跑 ctx_blueprint + ctx_memory（exec_beat 依赖它们）
    for dep_type in ["ctx_blueprint", "ctx_memory"]:
        try:
            if NodeRegistry.has(dep_type):
                instance = NodeRegistry.create_instance(dep_type)
                meta = NodeRegistry.get_meta(dep_type)
                inputs = {}
                for port in meta.input_ports:
                    val = state.get(port.name)
                    if val is not None:
                        inputs[port.name] = val
                ctx = {"novel_id": novel_id, "chapter_number": state.get("chapter_number", 0),
                       "dag_run_id": "preview", "shared_state": state, "config_overrides": {}}
                result = await instance.execute(inputs, ctx)
                if hasattr(result, 'outputs'):
                    state.update(result.outputs)
        except Exception as e:
            logger.warning(f"节拍预览依赖节点 {dep_type} 失败: {e}")

    # 跑 exec_beat
    if not NodeRegistry.has("exec_beat"):
        return {"novel_id": novel_id, "chapter_number": state.get("chapter_number", 0), "beats": []}

    try:
        instance = NodeRegistry.create_instance("exec_beat")
        meta = NodeRegistry.get_meta("exec_beat")
        inputs = {}
        for port in meta.input_ports:
            val = state.get(port.name)
            if val is not None:
                inputs[port.name] = val
        ctx = {"novel_id": novel_id, "chapter_number": state.get("chapter_number", 0),
               "dag_run_id": "preview", "shared_state": state, "config_overrides": {}}
        result = await instance.execute(inputs, ctx)
        outputs = result.outputs if hasattr(result, 'outputs') else {}

        beats = outputs.get("beats", []) or []
        beat_count = outputs.get("beat_count", 0) or len(beats)

        return {
            "novel_id": novel_id,
            "chapter_number": state.get("chapter_number", 0),
            "beats": beats if isinstance(beats, list) else [],
            "beat_count": beat_count,
        }
    except Exception as e:
        logger.error(f"节拍预览失败: {e}", exc_info=True)
        return {"novel_id": novel_id, "chapter_number": state.get("chapter_number", 0), "beats": [], "error": str(e)}


# ─── 节点详情（只读） ───


@router.get("/{novel_id}/nodes/{node_id}")
async def get_node(novel_id: str, node_id: str):
    """获取节点详情（只读展示）"""
    dag = _get_dag_for_novel(novel_id)

    node = dag.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"节点 '{node_id}' 不存在")

    # 附加节点元数据
    result = node.model_dump(mode="json")
    try:
        meta = NodeRegistry.get_meta(node.type)
        result["meta"] = meta.model_dump(mode="json")
    except KeyError:
        result["meta"] = None

    return result


# ─── 节点启禁用（唯一写操作） ───


@router.post("/{novel_id}/nodes/{node_id}/toggle")
async def toggle_node(novel_id: str, node_id: str):
    """切换启用/禁用"""
    dag = _get_dag_for_novel(novel_id)
    node = dag.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"节点 '{node_id}' 不存在")

    # 检查是否允许禁用
    try:
        meta = NodeRegistry.get_meta(node.type)
        if not meta.can_disable and node.enabled:
            raise HTTPException(status_code=400, detail=f"节点 '{node_id}' 不允许禁用")
    except KeyError:
        pass

    node.enabled = not node.enabled

    # 持久化变更
    try:
        _save_dag_for_novel(novel_id, dag)
    except Exception as e:
        logger.warning(f"toggle_node 持久化失败: {e}")

    return dag.model_dump(mode="json")


# ─── 运行状态（只读） ───


@router.get("/{novel_id}/status")
async def get_dag_status(novel_id: str):
    """获取运行状态（含所有节点状态）— 由全托管共享状态投影，与 DAG 定义节点 id 对齐。"""
    from interfaces.main import get_shared_novel_state

    dag = _get_dag_for_novel(novel_id)
    shared = get_shared_novel_state(novel_id)
    snap = snapshot_from_shared(novel_id, shared)
    node_ids = [(n.id, n.type, n.enabled) for n in dag.nodes]
    states = project_node_states(node_ids, snap)

    return DAGStatusResponse(
        novel_id=novel_id,
        dag_enabled=True,
        current_version=dag.version,
        node_states=states,
    )


# ─── 提示词来源（只读） ───


@router.get("/{novel_id}/nodes/{node_id}/prompt-live")
async def get_node_prompt_live(
    novel_id: str,
    node_id: str,
    node_type: Optional[str] = Query(default=None, description="节点类型（用于 DAG 中未找到节点时降级查询注册表）"),
):
    """获取节点当前的实时提示词

    优先从已保存的 DAG 中查找节点配置；若节点未保存（前端编辑中），
    通过 node_type 查询参数降级到注册表返回默认提示词信息。
    """
    dag = _get_dag_for_novel(novel_id)

    node_def = next((n for n in dag.nodes if n.id == node_id), None)

    # 降级：DAG 中找不到节点但传了 node_type，直接用注册表返回默认信息
    effective_type = node_def.type if node_def else node_type
    effective_config = node_def.config if node_def else NodeConfig()

    if not effective_type:
        raise HTTPException(status_code=404, detail=f"节点 {node_id} 不存在且未提供 node_type 参数")

    try:
        base_node = NodeRegistry.create_instance(effective_type, config=effective_config)
        prompt_dict = base_node.get_effective_prompt()

        cpms_node_key = ""
        if base_node.meta and base_node.meta.cpms_node_key:
            cpms_node_key = base_node.meta.cpms_node_key

        cpms_sub_keys = []
        if base_node.meta and base_node.meta.cpms_sub_keys:
            cpms_sub_keys = [
                {
                    "cpms_node_key": inj.cpms_node_key,
                    "target_variable": inj.target_variable,
                    "description": inj.description,
                    "required": inj.required,
                }
                for inj in base_node.meta.cpms_sub_keys
            ]

        prompt_mode = ""
        if base_node.meta and base_node.meta.prompt_mode:
            prompt_mode = base_node.meta.prompt_mode.value

        return {
            "node_id": node_id,
            "node_source": "dag" if node_def else "registry_fallback",
            "system": prompt_dict["system"],
            "user_template": prompt_dict["user_template"],
            "source": prompt_dict["source"],
            "cpms_node_key": cpms_node_key,
            "cpms_sub_keys": cpms_sub_keys,
            "prompt_mode": prompt_mode,
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"节点类型 {effective_type} 未注册")
    except Exception as e:
        logger.error(f"获取节点提示词失败: node={node_id}, type={effective_type}, error={e}", exc_info=True)
        return {
            "node_id": node_id,
            "node_source": "error",
            "system": "",
            "user_template": "",
            "source": "error",
            "cpms_node_key": "",
            "cpms_sub_keys": [],
            "prompt_mode": "",
        }


# ─── 渲染后 Prompt（只读预览） ───


@router.get("/{novel_id}/nodes/{node_id}/prompt")
async def get_rendered_prompt(novel_id: str, node_id: str):
    """获取渲染后的 Prompt（预览）"""
    dag = _get_dag_for_novel(novel_id)

    node = dag.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"节点 '{node_id}' 不存在")

    template = node.config.prompt_template or ""
    variables = node.config.prompt_variables or {}

    # 渲染模板
    rendered = template
    for key, value in variables.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))

    return {
        "node_id": node_id,
        "template": template,
        "variables": variables,
        "rendered": rendered,
    }


# ─── 节点配置更新（nodeEditorStore 使用） ───


class UpdateNodeConfigRequest(BaseModel):
    """更新节点配置请求"""
    prompt_template: Optional[str] = None
    prompt_variables: Optional[Dict[str, str]] = None
    thresholds: Optional[Dict[str, float]] = None
    model_override: Optional[str] = None
    max_retries: Optional[int] = Field(default=None, ge=0, le=5)
    timeout_seconds: Optional[int] = Field(default=None, ge=10, le=600)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=100, le=16000)


@router.put("/{novel_id}/nodes/{node_id}")
async def update_node_config(novel_id: str, node_id: str, request: UpdateNodeConfigRequest):
    """更新节点配置（运行参数）"""
    dag = _get_dag_for_novel(novel_id)
    node = dag.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"节点 '{node_id}' 不存在")

    # 应用配置更新
    updates = request.model_dump(exclude_none=True)
    if "prompt_template" in updates:
        node.config.prompt_template = updates["prompt_template"]
    if "prompt_variables" in updates:
        node.config.prompt_variables = updates["prompt_variables"]
    if "thresholds" in updates:
        node.config.thresholds.update(updates["thresholds"])
    if "model_override" in updates:
        node.config.model_override = updates["model_override"]
    if "max_retries" in updates:
        node.config.max_retries = updates["max_retries"]
    if "timeout_seconds" in updates:
        node.config.timeout_seconds = updates["timeout_seconds"]
    if "temperature" in updates:
        node.config.temperature = updates["temperature"]
    if "max_tokens" in updates:
        node.config.max_tokens = updates["max_tokens"]

    # 持久化变更
    try:
        _save_dag_for_novel(novel_id, dag)
    except Exception as e:
        logger.warning(f"update_node_config 持久化失败: {e}")

    return dag.model_dump(mode="json")


# ─── DAG 运行控制（dagRunStore 使用） ───


# ─── 运行中的 DAG 任务追踪 ───
_running_dag_tasks: Dict[str, asyncio.Task] = {}


@router.post("/{novel_id}/run")
async def run_dag(novel_id: str, chapter_number: Optional[int] = Query(default=None, description="指定章节号（不传则自动定位）")):
    """启动 DAG 运行 — 真正执行一章生成

    流程：
    1. 从 DB 读取 DAG 定义
    2. 构建初始状态（novel_id, chapter_number, outline）
    3. DAGEngine.run() 执行整个 DAG
    4. 执行过程中推送 SSE 事件
    5. 完成后保存章节内容到 DB
    """
    from application.engine.dag.engine import DAGEngine
    from application.engine.dag.state_initializer import StateInitializer

    # 检查是否已有任务在运行
    existing = _running_dag_tasks.get(novel_id)
    if existing and not existing.done():
        raise HTTPException(status_code=409, detail="该小说已有 DAG 任务在运行中")

    dag = _get_dag_for_novel(novel_id)

    # 构建初始状态
    initializer = StateInitializer()
    state = await initializer.build(novel_id, chapter_number)

    # 创建异步任务执行 DAG
    async def _execute():
        engine = DAGEngine()

        # ★ 注册流水线钩子 → SSE 转发（逐节拍事件实时推送前端）
        from application.engine.dag import pipeline_hook

        def on_beat_event(data: dict):
            publish_sse_event(novel_id, {
                "type": "node_status_change",
                "novel_id": novel_id,
                "node_id": data.get("node_id", "exec_writer"),
                "timestamp": time.time(),
                "status": "running",
                "metrics": {
                    "beat_index": data.get("beat_index", 0),
                    "total_beats": data.get("total_beats", 0),
                    "word_count": data.get("word_count", 0),
                    "accumulated_words": data.get("accumulated_words", 0),
                    "focus": data.get("focus", ""),
                },
                "outputs": {"content": data.get("content", "")} if data.get("content") else {},
                "subtype": data.get("type", ""),
            })

        pipeline_hook.on("beat_event", on_beat_event)

        try:
            # 推送开始事件
            publish_sse_event(novel_id, {
                "type": "node_status_change",
                "novel_id": novel_id,
                "node_id": "__dag_start__",
                "timestamp": time.time(),
                "status": "running",
                "metrics": {"phase": "start"},
            })

            # ★ 真正执行 DAG
            result = await engine.run(dag, state, thread_id=novel_id)

            # 推送每个节点的完成事件
            for node_id, node_result in result.node_results.items():
                publish_sse_event(novel_id, {
                    "type": "node_status_change",
                    "novel_id": novel_id,
                    "node_id": node_id,
                    "timestamp": time.time(),
                    "status": node_result.status.value if hasattr(node_result.status, 'value') else str(node_result.status),
                    "duration_ms": node_result.duration_ms,
                    "metrics": node_result.metrics,
                    "outputs": node_result.outputs,
                    "error": node_result.error,
                })

            # 推送完成事件
            publish_sse_event(novel_id, {
                "type": "node_status_change",
                "novel_id": novel_id,
                "node_id": "__dag_end__",
                "timestamp": time.time(),
                "status": "completed" if result.status == "completed" else "error",
                "metrics": {"total_duration_ms": result.total_duration_ms, "error_count": result.error_count},
            })

            logger.info(f"DAG 执行完成: novel={novel_id}, status={result.status}, duration={result.total_duration_ms}ms")

            # 保存章节内容
            await _save_chapter_from_dag_result(novel_id, state, result)

        except Exception as e:
            logger.error(f"DAG 执行异常: novel={novel_id}, error={e}", exc_info=True)
            publish_sse_event(novel_id, {
                "type": "node_status_change",
                "novel_id": novel_id,
                "node_id": "__dag_error__",
                "timestamp": time.time(),
                "status": "error",
                "error": str(e),
            })
        finally:
            pipeline_hook.off("beat_event", on_beat_event)

    # 启动后台任务
    task = asyncio.create_task(_execute())
    _running_dag_tasks[novel_id] = task

    return {
        "status": "started",
        "novel_id": novel_id,
        "dag_run_id": state.get("dag_run_id", ""),
        "chapter_number": state.get("chapter_number", 0),
        "message": f"DAG 执行已启动，章节 {state.get('chapter_number', 0)}",
    }


@router.post("/{novel_id}/stop")
async def stop_dag(novel_id: str):
    """停止 DAG 运行"""
    task = _running_dag_tasks.get(novel_id)
    if task and not task.done():
        task.cancel()
        logger.info(f"DAG 任务已取消: novel={novel_id}")
        return {"status": "cancelled", "novel_id": novel_id}
    return {"status": "not_running", "novel_id": novel_id}


async def _save_chapter_from_dag_result(novel_id: str, state: dict, result) -> None:
    """从 DAG 执行结果中提取章节内容并保存到 DB，同时记录 DAG 版本"""
    try:
        content = ""
        word_count = 0
        for node_id, node_result in result.node_results.items():
            outputs = node_result.outputs if hasattr(node_result, 'outputs') else {}
            if isinstance(outputs, dict):
                if outputs.get("content"):
                    content = str(outputs["content"])
                if outputs.get("word_count"):
                    word_count = int(outputs["word_count"])

        if not content:
            logger.warning("DAG 结果中未找到章节内容（exec_writer 输出），跳过保存")
            return

        chapter_number = state.get("chapter_number", 0)
        if not chapter_number:
            return

        from domain.novel.value_objects.novel_id import NovelId
        from infrastructure.persistence.database.sqlite_chapter_repository import SqliteChapterRepository
        from infrastructure.persistence.database.connection import get_database

        db = get_database()
        repo = SqliteChapterRepository(db)

        # ★ 获取当前 DAG 版本信息
        dag_version = 0
        dag_fingerprint = ""
        try:
            dag = _get_dag_for_novel(novel_id)
            dag_version = dag.version
            dag_fingerprint = dag.fingerprint()
        except Exception:
            pass

        existing = repo.get_by_novel_and_number(NovelId(novel_id), chapter_number)
        if existing:
            existing.content = content
            existing.word_count = word_count
            existing.status = "completed"
            repo.save(existing)
            # ★ 写入 DAG 版本追踪
            try:
                db.execute(
                    "UPDATE chapters SET dag_version_id = ?, dag_fingerprint = ? WHERE novel_id = ? AND number = ?",
                    (str(dag_version), dag_fingerprint, novel_id, chapter_number),
                )
                db.commit()
            except Exception:
                pass
        else:
            import uuid
            from domain.novel.entities.chapter import Chapter
            chapter = Chapter(
                id=str(uuid.uuid4()),
                novel_id=NovelId(novel_id),
                number=chapter_number,
                content=content,
                word_count=word_count,
                status="completed",
            )
            repo.save(chapter)
            try:
                db.execute(
                    "UPDATE chapters SET dag_version_id = ?, dag_fingerprint = ? WHERE novel_id = ? AND number = ?",
                    (str(dag_version), dag_fingerprint, novel_id, chapter_number),
                )
                db.commit()
            except Exception:
                pass

        logger.info(
            "章节已保存: novel=%s, chapter=%s, words=%s, dag=v%s (%s)",
            novel_id, chapter_number, word_count, dag_version, dag_fingerprint[:8],
        )
    except Exception as e:
        logger.error(f"保存章节失败: {e}", exc_info=True)
