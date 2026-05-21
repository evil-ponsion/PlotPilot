"""Gateway 节点 — 网关与熔断（4 个节点）

- gw_circuit: 熔断保护
- gw_review: 审阅网关
- gw_condition: 条件路由
- gw_retry: 重试网关
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from application.engine.dag.models import (
    NodeCategory,
    NodeMeta,
    NodePort,
    NodeResult,
    NodeStatus,
    PortDataType,
)
from application.engine.dag.registry import BaseNode, NodeRegistry

logger = logging.getLogger(__name__)


# ─── gw_circuit: 熔断保护 ───


@NodeRegistry.register("gw_circuit")
class CircuitNode(BaseNode):
    """熔断保护 — CircuitBreaker"""

    meta = NodeMeta(
        node_type="gw_circuit",
        display_name="🔌 熔断保护",
        category=NodeCategory.GATEWAY,
        icon="🔌",
        color="#ef4444",
        input_ports=[
            NodePort(name="error_count", data_type=PortDataType.SCORE, required=False, default=0),
            NodePort(name="max_errors", data_type=PortDataType.SCORE, required=False, default=3),
        ],
        output_ports=[
            NodePort(name="breaker_status", data_type=PortDataType.TEXT),
        ],
        prompt_template="",
        prompt_variables=[],
        is_configurable=False,
        can_disable=False,
        default_timeout_seconds=5,
        cpms_node_key="circuit-breaker",
        description="CircuitBreaker 熔断保护网关",
        default_edges=["val_narrative"],
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()

        try:
            error_count = inputs.get("error_count", 0)
            thresholds = self._config.thresholds if self._config else {}
            max_errors = thresholds.get("max_errors", inputs.get("max_errors", 3))

            breaker_status = "open" if error_count >= max_errors else "closed"

            return NodeResult(
                outputs={"breaker_status": breaker_status},
                status=NodeStatus.WARNING if breaker_status == "open" else NodeStatus.SUCCESS,
                metrics={"error_count": float(error_count)},
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(outputs={"breaker_status": "open"}, status=NodeStatus.ERROR, duration_ms=int((time.time() - start) * 1000), error=str(e))

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return True


# ─── gw_review: 审阅网关 ───


@NodeRegistry.register("gw_review")
class ReviewNode(BaseNode):
    """审阅网关 — 产出结构化审阅报告

    从 shared state 中收集所有验证节点的结果，组装为可读的审阅报告。
    前端据此展示漂移片段、OOC 检测、张力评分、操作建议。
    """

    meta = NodeMeta(
        node_type="gw_review",
        display_name="⏸️ 审阅网关",
        category=NodeCategory.GATEWAY,
        icon="⏸️",
        color="#f59e0b",
        input_ports=[
            NodePort(name="content", data_type=PortDataType.TEXT, required=False),
            NodePort(name="metrics", data_type=PortDataType.JSON, required=False),
        ],
        output_ports=[
            NodePort(name="approved", data_type=PortDataType.BOOLEAN),
            NodePort(name="review_report", data_type=PortDataType.JSON),
            NodePort(name="issues_count", data_type=PortDataType.SCORE),
        ],
        prompt_template="",
        prompt_variables=[],
        is_configurable=False,
        can_disable=True,
        default_timeout_seconds=10,
        cpms_node_key="review-gateway",
        description="产出结构化审阅报告：漂移片段 + OOC 检测 + 张力评分",
        default_edges=[],
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()

        try:
            shared = context.get("shared_state", {}) if isinstance(context, dict) else {}
            report = {
                "approved": True,
                "sections": [],
                "summary": "",
            }
            issues = 0

            # ── 文风漂移 ──
            drift_alert = shared.get("drift_alert", False)
            drift_score = shared.get("drift_score", 0)
            if drift_alert:
                report["approved"] = False
                issues += 1
                report["sections"].append({
                    "type": "voice_drift",
                    "title": "🎭 文风漂移",
                    "severity": "warning",
                    "detail": f"声线相似度低于阈值 (当前: {drift_score}, 阈值: 0.68)",
                    "suggestion": "建议检查本章对话和描写是否符合角色设定声线",
                })

            # ── 张力 ──
            tension = shared.get("tension_composite", 50)
            tension_dims = shared.get("tension_dimensions", {})
            tension_status = "normal"
            if isinstance(tension, (int, float)):
                if tension < 30:
                    tension_status = "low"
                    issues += 1
                elif tension > 85:
                    tension_status = "high"
            report["sections"].append({
                "type": "tension",
                "title": "📈 张力评分",
                "severity": "info",
                "detail": f"综合张力: {tension}/100",
                "dimensions": tension_dims if isinstance(tension_dims, dict) else {},
                "status": tension_status,
            })

            # ── Anti-AI ──
            anti_ai_severity = shared.get("anti_ai_severity", 0)
            anti_ai_hits = shared.get("anti_ai_hits", [])
            if isinstance(anti_ai_severity, (int, float)) and anti_ai_severity > 0.3:
                issues += 1
                hits_list = anti_ai_hits if isinstance(anti_ai_hits, list) else []
                hit_details = [h.get("description", str(h)) if isinstance(h, dict) else str(h) for h in hits_list[:5]]
                report["sections"].append({
                    "type": "anti_ai",
                    "title": "🛡️ Anti-AI 检测",
                    "severity": "warning" if anti_ai_severity > 0.5 else "info",
                    "detail": f"AI 痕迹严重度: {anti_ai_severity}",
                    "hits": hit_details,
                })

            # ── 熔断 ──
            breaker = shared.get("breaker_status", "closed")
            if breaker == "open":
                report["approved"] = False
                issues += 1
                report["sections"].append({
                    "type": "circuit_breaker",
                    "title": "🔌 熔断保护已触发",
                    "severity": "error",
                    "detail": f"累计错误数超过阈值，生成已中断",
                })

            # ── 叙事同步 ──
            narrative_summary = shared.get("narrative_summary", "")
            narrative_events = shared.get("narrative_events", [])
            if narrative_summary:
                report["sections"].append({
                    "type": "narrative",
                    "title": "🧬 叙事同步",
                    "severity": "info",
                    "detail": narrative_summary[:500],
                    "event_count": len(narrative_events) if isinstance(narrative_events, list) else 0,
                })

            # ── 总结 ──
            if issues == 0:
                report["summary"] = "✅ 所有检查通过，建议自动审批"
            elif issues == 1:
                report["summary"] = f"⚠️ 发现 {issues} 个问题，建议人工审阅"
            else:
                report["summary"] = f"❌ 发现 {issues} 个问题，需要人工审阅"

            return NodeResult(
                outputs={
                    "approved": report["approved"],
                    "review_report": report,
                    "issues_count": float(issues),
                },
                status=NodeStatus.WARNING if issues > 0 else NodeStatus.SUCCESS,
                metrics={"issues": float(issues), "tension": float(tension) if isinstance(tension, (int, float)) else 0},
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                outputs={"approved": False, "review_report": {"approved": False, "sections": [], "summary": f"审阅异常: {e}"}, "issues_count": 1},
                status=NodeStatus.ERROR,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return True


# ─── gw_condition: 条件路由 ───


@NodeRegistry.register("gw_condition")
class ConditionNode(BaseNode):
    """条件路由 — 根据输入条件决定走哪条分支"""

    meta = NodeMeta(
        node_type="gw_condition",
        display_name="🔀 条件路由",
        category=NodeCategory.GATEWAY,
        icon="🔀",
        color="#3b82f6",
        input_ports=[
            NodePort(name="input", data_type=PortDataType.JSON, required=True),
        ],
        output_ports=[
            NodePort(name="output_true", data_type=PortDataType.JSON),
            NodePort(name="output_false", data_type=PortDataType.JSON),
        ],
        prompt_template="",
        prompt_variables=[],
        is_configurable=True,
        can_disable=False,
        default_timeout_seconds=5,
        cpms_node_key="condition-gateway",
        description="条件路由网关",
        default_edges=[],
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()

        try:
            input_data = inputs.get("input", {})

            # 简单条件判断：检查是否有异常标志
            condition_met = True
            if isinstance(input_data, dict):
                condition_met = not (
                    input_data.get("drift_alert", False) or
                    input_data.get("breaker_status") == "open" or
                    input_data.get("error")
                )

            return NodeResult(
                outputs={
                    "output_true": input_data if condition_met else None,
                    "output_false": input_data if not condition_met else None,
                },
                status=NodeStatus.SUCCESS,
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(outputs={"output_true": None, "output_false": None}, status=NodeStatus.ERROR, duration_ms=int((time.time() - start) * 1000), error=str(e))

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return "input" in inputs


# ─── gw_switch: 用户可配置条件分支网关 ───


@NodeRegistry.register("gw_switch")
class SwitchGatewayNode(BaseNode):
    """条件分支网关 — 用户可配置路由规则

    根据配置的 condition_field / condition_operator / condition_value 评估 state，
    将流量路由到对应的下游端口（case_a / case_b / case_default）。

    配置示例（NodeConfig.thresholds）：
        condition_field: "tension_composite"
        condition_operator: "gte"   # gte / lt / eq / contains
        condition_value: 60

    评估结果写入 outputs.switch_port = "case_a" | "case_b" | "case_default"
    下游通过 EdgeCondition.ON_SWITCH_PORT 条件边匹配路由。
    """

    meta = NodeMeta(
        node_type="gw_switch",
        display_name="🔀 分支网关",
        category=NodeCategory.GATEWAY,
        icon="🔀",
        color="#10b981",
        input_ports=[
            NodePort(name="input", data_type=PortDataType.JSON, required=False),
        ],
        output_ports=[
            NodePort(name="switch_port", data_type=PortDataType.TEXT),
            NodePort(name="case_data", data_type=PortDataType.JSON),
        ],
        prompt_template="",
        prompt_variables=[],
        is_configurable=True,
        can_disable=False,
        default_timeout_seconds=5,
        cpms_node_key="switch-gateway",
        description="用户可配置的条件分支网关，根据指定字段和条件决定下游路由",
        default_edges=[],
        default_dag_slot=None,
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()

        try:
            shared_state = context.get("shared_state", {}) if isinstance(context, dict) else {}

            # 从 config.thresholds 读取条件配置
            thresholds = self._config.thresholds if self._config else {}
            condition_field = thresholds.get("condition_field", "")
            condition_operator = thresholds.get("condition_operator", "gte")
            condition_value = thresholds.get("condition_value")

            # 从 shared_state 读取目标字段值
            field_value = shared_state.get(condition_field) if condition_field else None

            # 评估条件
            route = self._evaluate_condition(field_value, condition_operator, condition_value)

            return NodeResult(
                outputs={
                    "switch_port": route,
                    "case_data": {
                        "field": condition_field,
                        "value": field_value,
                        "route": route,
                    },
                },
                status=NodeStatus.SUCCESS,
                metrics={"field_value": float(field_value) if isinstance(field_value, (int, float)) else 0},
                duration_ms=int((time.time() - start) * 1000),
            )
        except Exception as e:
            return NodeResult(
                outputs={"switch_port": "case_default", "case_data": None},
                status=NodeStatus.ERROR,
                duration_ms=int((time.time() - start) * 1000),
                error=str(e),
            )

    def _evaluate_condition(self, field_value: Any, operator: str, target: Any) -> str:
        """根据操作符评估条件，返回路由端口名"""
        if operator == "eq":
            return "case_a" if field_value == target else "case_b"
        elif operator == "neq":
            return "case_a" if field_value != target else "case_b"
        elif operator == "gt":
            try:
                return "case_a" if float(field_value) > float(target) else "case_b"
            except (TypeError, ValueError):
                return "case_default"
        elif operator == "gte":
            try:
                return "case_a" if float(field_value) >= float(target) else "case_b"
            except (TypeError, ValueError):
                return "case_default"
        elif operator == "lt":
            try:
                return "case_a" if float(field_value) < float(target) else "case_b"
            except (TypeError, ValueError):
                return "case_default"
        elif operator == "lte":
            try:
                return "case_a" if float(field_value) <= float(target) else "case_b"
            except (TypeError, ValueError):
                return "case_default"
        elif operator == "contains":
            try:
                return "case_a" if str(target) in str(field_value) else "case_b"
            except Exception:
                return "case_default"
        elif operator == "is_truthy":
            return "case_a" if field_value else "case_b"
        elif operator == "is_falsy":
            return "case_a" if not field_value else "case_b"
        return "case_default"

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return True


# ─── gw_retry: 重试网关 ───


@NodeRegistry.register("gw_retry")
class RetryNode(BaseNode):
    """重试网关 — 文风检查失败时触发重写"""

    meta = NodeMeta(
        node_type="gw_retry",
        display_name="🔄 重写网关",
        category=NodeCategory.GATEWAY,
        icon="🔄",
        color="#8b5cf6",
        input_ports=[
            NodePort(name="input", data_type=PortDataType.JSON, required=True),
            NodePort(name="max_attempts", data_type=PortDataType.SCORE, required=False, default=2),
        ],
        output_ports=[
            NodePort(name="output", data_type=PortDataType.JSON),
            NodePort(name="attempts_used", data_type=PortDataType.SCORE),
        ],
        prompt_template="以下章节文风偏离角色声线，请重写...",
        prompt_variables=["content"],
        is_configurable=True,
        can_disable=False,
        default_timeout_seconds=10,
        cpms_node_key="retry-gateway",
        description="文风检查失败时触发重写的重试网关",
        default_edges=["exec_writer"],
    )

    async def execute(self, inputs: Dict[str, Any], context: Dict[str, Any]) -> NodeResult:
        import time
        start = time.time()

        try:
            input_data = inputs.get("input", {})
            max_attempts = inputs.get("max_attempts", 2)
            if self._config and self._config.max_retries:
                max_attempts = self._config.max_retries

            # 检查当前重试次数
            retry_count = context.get("shared_state", {}).get("retry_count", 0) if isinstance(context, dict) else 0

            if retry_count < max_attempts:
                # 允许重试
                return NodeResult(
                    outputs={"output": input_data, "attempts_used": retry_count + 1},
                    status=NodeStatus.SUCCESS,
                    metrics={"retry_count": float(retry_count + 1)},
                    duration_ms=int((time.time() - start) * 1000),
                )
            else:
                # 超出重试次数，标记警告但继续
                return NodeResult(
                    outputs={"output": input_data, "attempts_used": retry_count},
                    status=NodeStatus.WARNING,
                    metrics={"retry_count": float(retry_count)},
                    duration_ms=int((time.time() - start) * 1000),
                )
        except Exception as e:
            return NodeResult(outputs={"output": inputs.get("input"), "attempts_used": 0}, status=NodeStatus.ERROR, duration_ms=int((time.time() - start) * 1000), error=str(e))

    def validate_inputs(self, inputs: Dict[str, Any]) -> bool:
        return "input" in inputs
