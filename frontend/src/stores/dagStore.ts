/**
 * DAG 画布核心状态管理 — 支持浏览/编辑双模式
 *
 * 设计原则：
 * - 浏览模式：只读展示，节点状态 SSE 实时更新
 * - 编辑模式：可拖拽节点、连线、修改配置，手动保存到后端
 * - DAG 定义持久化到 SQLite dag_versions 表
 */
import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type {
  DAGDefinition,
  DagRegistryLinkageResponse,
  EdgeDefinition,
  NodeDefinition,
  NodeEvent,
  NodeMeta,
  NodePromptLive,
  NodeRunState,
  NodeStatus,
} from '@/types/dag'
import { dagApi } from '@/api/dag'

/** 创建唯一 ID（前端临时使用，保存时后端会重新校验） */
function uid(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export const useDAGStore = defineStore('dag', () => {
  // ─── DAG 定义（只读展示） ───
  const dagDefinition = ref<DAGDefinition | null>(null)
  const nodeTypeRegistry = ref<Record<string, NodeMeta>>({})
  /** 后端 linkage_kernel 导出：画布节点 ↔ CPMS 与管线顺序 */
  const registryLinkage = ref<DagRegistryLinkageResponse | null>(null)
  /** 默认 DAG 中未在 NodeRegistry 注册的类型（后端应保证为空） */
  const registryGaps = ref<Array<{ node_id: string; node_type: string }>>([])
  /** GET /dag/registry/linkage 失败时仅能用本地 types 推断缺口 */
  const registryLinkageFailed = ref(false)

  // ─── 节点运行时状态（SSE 推送） ───
  const nodeStates = ref<Map<string, NodeRunState>>(new Map())

  // ─── 边动画状态 ───
  const edgeFlows = ref<Map<string, { port: string; timestamp: number }>>(new Map())

  // ─── 节点提示词缓存 ───
  const nodePromptLive = ref<Map<string, NodePromptLive>>(new Map())

  // ─── 交互状态 ───
  const selectedNodeId = ref<string | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // ─── 视图切换（AutopilotDashboard 使用） ───
  const viewMode = ref<'card' | 'dag'>('card')

  // ─── 编辑模式 ───
  const editMode = ref(false)

  // ─── Vue Flow 可写节点/边（编辑模式下 Vue Flow v-model 需要可写 ref） ───
  const vueFlowNodes = ref<any[]>([])
  const vueFlowEdges = ref<any[]>([])

  /** 从 dagDefinition 重建 vueFlow 节点/边数据 */
  function rebuildFlowData() {
    const dag = dagDefinition.value
    if (!dag) {
      vueFlowNodes.value = []
      vueFlowEdges.value = []
      return
    }

    const reg = nodeTypeRegistry.value
    const regLoaded = Object.keys(reg).length > 0

    vueFlowNodes.value = dag.nodes.map(nodeDef => ({
      id: nodeDef.id,
      type: 'dagCustom',
      position: { ...nodeDef.position },
      data: {
        ...nodeDef,
        runState: nodeStates.value.get(nodeDef.id),
        isSelected: selectedNodeId.value === nodeDef.id,
        registryMissing: regLoaded && !reg[nodeDef.type],
      },
    }))

    vueFlowEdges.value = dag.edges.map(edgeDef => {
      const flowKey = `${edgeDef.source}->${edgeDef.target}`
      const flow = edgeFlows.value.get(flowKey)
      const isActive = flow && (Date.now() - flow.timestamp < 2000)

      return {
        id: edgeDef.id,
        source: edgeDef.source,
        target: edgeDef.target,
        sourceHandle: edgeDef.source_port || undefined,
        targetHandle: edgeDef.target_port || undefined,
        animated: edgeDef.animated || isActive,
        data: {
          condition: edgeDef.condition,
          isActive,
        },
        style: {
          strokeDasharray: edgeDef.condition !== 'always' ? '5 5' : undefined,
        },
      }
    })
  }

  // dagDefinition 变化时自动重建 flow 数据
  watch(dagDefinition, () => rebuildFlowData(), { deep: true, immediate: true })
  // nodeStates 变化时也刷新（SSE 状态更新需要反映到画布）
  watch(nodeStates, () => rebuildFlowData(), { deep: true })

  // ─── 计算属性：DAG 统计 ───
  const dagStats = computed(() => {
    const nodes = dagDefinition.value?.nodes ?? []
    const states = nodeStates.value
    return {
      total: nodes.length,
      enabled: nodes.filter(n => n.enabled).length,
      running: nodes.filter(n => states.get(n.id)?.status === 'running').length,
      success: nodes.filter(n => states.get(n.id)?.status === 'success').length,
      error: nodes.filter(n => states.get(n.id)?.status === 'error').length,
      bypassed: nodes.filter(n => states.get(n.id)?.status === 'bypassed').length,
      version: dagDefinition.value?.version ?? 0,
    }
  })

  // ─── Actions ───

  function computeRegistryGapsLocal() {
    const dag = dagDefinition.value
    const reg = nodeTypeRegistry.value
    if (!dag || Object.keys(reg).length === 0) {
      registryGaps.value = []
      return
    }
    registryGaps.value = dag.nodes
      .filter(n => !reg[n.type])
      .map(n => ({ node_id: n.id, node_type: n.type }))
  }

  /** 并行加载 DAG + 注册表 + linkage（首屏推荐） */
  async function hydrateDagForNovel(novelId: string) {
    isLoading.value = true
    error.value = null
    registryLinkageFailed.value = false
    try {
      const [dagR, typesR, linkR] = await Promise.allSettled([
        dagApi.getDAG(novelId),
        dagApi.listNodeTypes(),
        dagApi.getRegistryLinkage(),
      ])
      if (dagR.status === 'fulfilled' && dagR.value) {
        dagDefinition.value = dagR.value
        error.value = null
      } else {
        error.value = dagR.status === 'rejected'
          ? (dagR.reason instanceof Error ? dagR.reason.message : '加载 DAG 失败')
          : null
        // 兜底：API 失败也显示默认空 DAG，画布不空白
        if (!dagDefinition.value) {
          dagDefinition.value = {
            id: 'dag_fallback', name: '默认', version: 0, description: '',
            nodes: [], edges: [], metadata: { created_at: '', updated_at: '', created_by: '' }
          }
        }
      }
      if (typesR.status === 'fulfilled') {
        nodeTypeRegistry.value = typesR.value.types
      }
      if (linkR.status === 'fulfilled') {
        registryLinkage.value = linkR.value
        registryLinkageFailed.value = false
        const g = linkR.value.registry_gaps
        registryGaps.value = g?.missing?.length ? [...g.missing] : []
      } else {
        registryLinkage.value = null
        registryLinkageFailed.value = true
        if (dagR.status === 'fulfilled' && typesR.status === 'fulfilled') {
          computeRegistryGapsLocal()
        } else {
          registryGaps.value = []
        }
      }
    } finally {
      isLoading.value = false
    }
  }

  async function loadDAG(novelId: string) {
    isLoading.value = true
    error.value = null
    try {
      const dag = await dagApi.getDAG(novelId)
      if (dag) dagDefinition.value = dag
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '加载 DAG 失败'
    } finally {
      isLoading.value = false
      // 兜底：确保画布不空白
      if (!dagDefinition.value) {
        dagDefinition.value = {
          id: 'dag_fallback', name: '默认', version: 0, description: '',
          nodes: [], edges: [], metadata: { created_at: '', updated_at: '', created_by: '' }
        }
      }
    }
  }

  async function loadNodeTypeRegistry() {
    const [typesRes, linkRes] = await Promise.allSettled([
      dagApi.listNodeTypes(),
      dagApi.getRegistryLinkage(),
    ])
    if (typesRes.status === 'fulfilled') {
      nodeTypeRegistry.value = typesRes.value.types
    }
    if (linkRes.status === 'fulfilled') {
      registryLinkage.value = linkRes.value
      registryLinkageFailed.value = false
      const g = linkRes.value.registry_gaps
      registryGaps.value = g?.missing?.length ? [...g.missing] : []
    } else {
      registryLinkage.value = null
      registryLinkageFailed.value = true
      computeRegistryGapsLocal()
    }
  }

  async function toggleNode(novelId: string, nodeId: string) {
    try {
      const dag = await dagApi.toggleNode(novelId, nodeId)
      dagDefinition.value = dag
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '切换节点状态失败'
    }
  }

  // ─── SSE 事件处理 ───

  function handleSSEEvent(event: NodeEvent) {
    switch (event.type) {
      case 'node_status_change':
        if (event.node_id) {
          const existing = nodeStates.value.get(event.node_id)
          nodeStates.value.set(event.node_id, {
            node_id: event.node_id,
            status: (event.status ?? 'idle') as NodeStatus,
            duration_ms: existing?.duration_ms ?? 0,
            outputs: existing?.outputs ?? {},
            metrics: existing?.metrics ?? (event.metrics as Record<string, number>) ?? {},
            progress: existing?.progress ?? 0,
            error: event.error ?? null,
          })
        }
        break

      case 'node_output':
        if (event.node_id) {
          const existing = nodeStates.value.get(event.node_id)
          if (existing) {
            existing.outputs = event.outputs ?? {}
            existing.duration_ms = event.duration_ms ?? 0
          } else {
            nodeStates.value.set(event.node_id, {
              node_id: event.node_id,
              status: 'success',
              outputs: event.outputs ?? {},
              duration_ms: event.duration_ms ?? 0,
              metrics: (event.metrics as Record<string, number>) ?? {},
              progress: 1.0,
            })
          }
        }
        break

      case 'edge_data_flow':
        if (event.source_node && event.target_node) {
          edgeFlows.value.set(
            `${event.source_node}->${event.target_node}`,
            { port: event.port ?? '', timestamp: Date.now() }
          )
        }
        break
    }
  }

  function selectNode(nodeId: string | null) {
    selectedNodeId.value = nodeId
  }

  function switchView(mode: 'card' | 'dag') {
    viewMode.value = mode
  }

  // ─── 编辑模式 Actions ───

  function setEditMode(on: boolean) {
    editMode.value = on
  }

  /** 添加节点到画布 */
  function addNode(nodeType: string, position: { x: number; y: number }) {
    const dag = dagDefinition.value
    if (!dag) return

    const meta = nodeTypeRegistry.value[nodeType]
    const label = meta?.display_name ?? nodeType
    const nodeId = uid(nodeType.replace(/^[a-z]+_/, 'n_'))

    const newNode: NodeDefinition = {
      id: nodeId,
      type: nodeType,
      label,
      position,
      enabled: true,
      config: {
        temperature: 0.7,
        max_retries: meta?.default_max_retries ?? 1,
        timeout_seconds: meta?.default_timeout_seconds ?? 60,
      },
    }

    dagDefinition.value = {
      ...dag,
      nodes: [...dag.nodes, newNode],
    }
  }

  /** 删除节点及其关联的所有边 */
  function removeNode(nodeId: string) {
    const dag = dagDefinition.value
    if (!dag) return

    dagDefinition.value = {
      ...dag,
      nodes: dag.nodes.filter(n => n.id !== nodeId),
      edges: dag.edges.filter(e => e.source !== nodeId && e.target !== nodeId),
    }

    if (selectedNodeId.value === nodeId) {
      selectedNodeId.value = null
    }
  }

  /** 添加边 */
  function addEdge(source: string, target: string, condition: string = 'always') {
    const dag = dagDefinition.value
    if (!dag) return

    // 检查是否已存在相同边
    const exists = dag.edges.some(e => e.source === source && e.target === target)
    if (exists) return

    const edgeId = uid('edge')

    const newEdge: EdgeDefinition = {
      id: edgeId,
      source,
      source_port: '',
      target,
      target_port: '',
      condition: condition as any,
      animated: condition !== 'always',
    }

    dagDefinition.value = {
      ...dag,
      edges: [...dag.edges, newEdge],
    }
  }

  /** 删除边 */
  function removeEdge(edgeId: string) {
    const dag = dagDefinition.value
    if (!dag) return

    dagDefinition.value = {
      ...dag,
      edges: dag.edges.filter(e => e.id !== edgeId),
    }
  }

  /** 更新节点位置 */
  function updateNodePosition(nodeId: string, position: { x: number; y: number }) {
    const dag = dagDefinition.value
    if (!dag) return

    dagDefinition.value = {
      ...dag,
      nodes: dag.nodes.map(n =>
        n.id === nodeId ? { ...n, position } : n
      ),
    }
  }

  /** 保存 DAG 到后端 */
  async function saveDAG(novelId: string) {
    const dag = dagDefinition.value
    if (!dag) throw new Error('没有可保存的 DAG')

    isLoading.value = true
    error.value = null
    try {
      const result = await dagApi.saveDAG(novelId, {
        nodes: dag.nodes,
        edges: dag.edges,
        name: dag.name,
        description: dag.description,
      })
      // 更新版本号
      if (dagDefinition.value) {
        dagDefinition.value = {
          ...dagDefinition.value,
          version: result.version,
        }
      }
      return result
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '保存 DAG 失败'
      throw e
    } finally {
      isLoading.value = false
    }
  }

  /** 更新节点运行参数（NodeEditorDrawer 使用） */
  async function updateNodeConfig(novelId: string, nodeId: string, config: Record<string, unknown>) {
    try {
      // 调用后端 API 持久化
      await dagApi.updateNodeConfig(novelId, nodeId, config)
      // 刷新本地 DAG
      const dag = await dagApi.getDAG(novelId)
      dagDefinition.value = dag
    } catch (e: unknown) {
      error.value = e instanceof Error ? e.message : '更新节点配置失败'
    }
  }

  function resetNodeStates() {
    nodeStates.value.clear()
    edgeFlows.value.clear()
  }

  async function loadNodePromptLive(novelId: string, nodeId: string) {
    try {
      // 从本地 dagDefinition 查找节点类型，传给后端用于降级查询（未保存节点也能查注册表）
      const nodeDef = dagDefinition.value?.nodes.find(n => n.id === nodeId)
      const nodeType = nodeDef?.type
      const result = await dagApi.getNodePromptLive(novelId, nodeId, nodeType)
      nodePromptLive.value.set(nodeId, result)
      return result
    } catch {
      return null
    }
  }

  return {
    // State
    dagDefinition,
    nodeTypeRegistry,
    registryLinkage,
    registryGaps,
    registryLinkageFailed,
    nodeStates,
    edgeFlows,
    nodePromptLive,
    selectedNodeId,
    isLoading,
    error,
    viewMode,
    editMode,

    // Computed / Ref
    vueFlowNodes,
    vueFlowEdges,
    dagStats,

    // Actions — 浏览模式
    hydrateDagForNovel,
    loadDAG,
    loadNodeTypeRegistry,
    toggleNode,
    updateNodeConfig,
    handleSSEEvent,
    selectNode,
    switchView,
    resetNodeStates,
    loadNodePromptLive,

    // Actions — 编辑模式
    setEditMode,
    addNode,
    removeNode,
    addEdge,
    removeEdge,
    updateNodePosition,
    saveDAG,
    rebuildFlowData,
  }
})
