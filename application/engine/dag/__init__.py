"""DAG 工作流引擎 — 节点化 DAG 编排系统

核心模块：
- models: DAG 定义、节点/边模型、执行结果
- registry: 节点类型注册表（工厂模式）
- engine: DAG 执行引擎（LangGraph 编排 + 拓扑并行）
- validator: DAG 校验引擎（环检测、端口兼容性、可达性分析）
- version_manager: DAG 版本管理（保存/回滚/对比）
- daemon_runner: DAG 守护进程运行器（替代 AutopilotDaemon 隐式状态机）
- ipc_adapter: LangGraph 节点与现有 IPC 通道的适配器
- event_aggregator: SSE 节点事件聚合器（节流 + 批量推送）
- error_classifier: 节点错误分类器
- prompt_validator: Prompt 模板安全校验器
- nodes: V1 首批 19 个节点实现
"""

# 核心模型
from application.engine.dag.models import (
    DAGDefinition,
    DAGMetadata,
    DAGRunResult,
    EdgeCondition,
    EdgeDefinition,
    NodeCategory,
    NodeConfig,
    NodeDefinition,
    NodeEvent,
    NodeMeta,
    NodePort,
    NodeResult,
    NodeRunState,
    NodeStatus,
    NovelWorkflowState,
    PortDataType,
    get_default_dag,
)

# 核心组件
from application.engine.dag.registry import BaseNode, NodeRegistry
from application.engine.dag.engine import DAGEngine, DAGExecutionError
from application.engine.dag.validator import DAGValidator, ValidationResult
from application.engine.dag.version_manager import DAGVersionManager
from application.engine.dag.event_aggregator import NodeEventAggregator
from application.engine.dag.error_classifier import NodeErrorClassifier, ErrorClassification, ErrorLevel, RetryStrategy
from application.engine.dag.ipc_adapter import IPCAdapter
from application.engine.dag.daemon_runner import DAGDaemonRunner, EngineSelector
from application.engine.dag.prompt_validator import PromptTemplateValidator

__all__ = [
    # 模型
    "DAGDefinition",
    "DAGMetadata",
    "DAGRunResult",
    "EdgeCondition",
    "EdgeDefinition",
    "NodeCategory",
    "NodeConfig",
    "NodeDefinition",
    "NodeEvent",
    "NodeMeta",
    "NodePort",
    "NodeResult",
    "NodeRunState",
    "NodeStatus",
    "NovelWorkflowState",
    "PortDataType",
    "get_default_dag",
    # 核心组件
    "BaseNode",
    "NodeRegistry",
    "DAGEngine",
    "DAGExecutionError",
    "DAGValidator",
    "ValidationResult",
    "DAGVersionManager",
    "NodeEventAggregator",
    "NodeErrorClassifier",
    "ErrorClassification",
    "ErrorLevel",
    "RetryStrategy",
    "IPCAdapter",
    "DAGDaemonRunner",
    "EngineSelector",
    "PromptTemplateValidator",
]

# ─── 流水线回调钩子 ───
# 节点在 execute() 中通过此钩子向外部（API/SSE）发射事件
# 用法：
#   from application.engine.dag import pipeline_hook
#   pipeline_hook.emit("beat_complete", {"beat_index": 1, "content": "..."})


class PipelineHook:
    """DAG 执行流水线回调钩子

    允许节点在执行过程中发射事件，供外部（SSE、日志、监控）消费。
    """

    def __init__(self):
        self._handlers: dict[str, list] = {}

    def on(self, event: str, handler):
        """注册事件处理器"""
        self._handlers.setdefault(event, []).append(handler)

    def off(self, event: str, handler):
        """移除事件处理器"""
        if event in self._handlers:
            try:
                self._handlers[event].remove(handler)
            except ValueError:
                pass

    def emit(self, event: str, data: dict | None = None):
        """发射事件"""
        handlers = self._handlers.get(event, [])
        for h in handlers:
            try:
                h(data or {})
            except Exception:
                pass


pipeline_hook = PipelineHook()

