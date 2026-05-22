<template>
  <div
    class="dag-canvas"
    :class="{ 'dag-canvas--edit': editMode }"
    @dragover.prevent="handleDragOver"
  >
    <!-- 编辑模式下的节点面板 -->
    <NodePalette v-if="editMode" />

    <VueFlow
      v-model:nodes="flowNodes"
      v-model:edges="flowEdges"
      :default-viewport="{ zoom: 0.8, x: 0, y: 0 }"
      :min-zoom="0.3"
      :max-zoom="2"
      :connect-on-click="false"
      :nodes-draggable="editMode"
      :nodes-connectable="editMode"
      :edges-deletable="editMode"
      :elements-selectable="editMode"
      :connection-mode="'loose'"
      fit-view-on-init
      @node-click="handleNodeClick"
      @node-context-menu="handleNodeContextMenu as any"
      @node-drag-stop="handleNodeDragStop"
      @connect="handleConnect"
      @edges-change="handleEdgesChange"
    >
      <!-- ★ 坐标转换助手（在 Vue Flow 内部才能拿到 viewport 上下文） -->
      <FlowDropHelper v-if="editMode" @flow-drop="handleFlowDrop" />

      <!-- 自定义节点类型 -->
      <template #node-dagCustom="nodeProps">
        <CustomNode v-bind="nodeProps" @contextmenu="handleCustomNodeContextmenu" />
      </template>

      <!-- 自定义边 -->
      <template #edge-custom="edgeProps">
        <CustomEdge v-bind="edgeProps" />
      </template>

      <!-- 背景 -->
      <Background :gap="20" :size="1" :style="{ backgroundColor: 'transparent' }" />
      <!-- 控制面板 -->
      <Controls position="bottom-right" />
      <!-- 小地图 -->
      <MiniMap position="bottom-left" :pannable="true" :zoomable="true" />
    </VueFlow>

    <!-- 编辑模式提示 -->
    <div v-if="editMode" class="edit-mode-badge">
      ✏️ 编辑模式 — 从左侧拖入节点、连线后点击「保存」
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed, defineComponent, h, onMounted, onUnmounted } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import type { Edge, Node, Connection } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import '@vue-flow/controls/dist/style.css'
import '@vue-flow/minimap/dist/style.css'

import { useDAGStore } from '@/stores/dagStore'
import CustomNode from './CustomNode.vue'
import CustomEdge from './CustomEdge.vue'
import NodePalette from './NodePalette.vue'

// ═══════════════════════════════════════════════════
// FlowDropHelper — Vue Flow 内部的坐标转换助手
// 在 <VueFlow> 内部才能拿到 useVueFlow() 的 viewport 上下文
// ═══════════════════════════════════════════════════
const FlowDropHelper = defineComponent({
  name: 'FlowDropHelper',
  emits: ['flowDrop'],
  setup(_props, { emit }) {
    const { screenToFlowCoordinate } = useVueFlow()

    function onDocumentDrop(e: DragEvent) {
      const nodeType = e.dataTransfer?.getData('application/dag-node-type')
      if (!nodeType) return
      e.preventDefault()
      const pos = screenToFlowCoordinate({ x: e.clientX, y: e.clientY })
      emit('flowDrop', { nodeType, position: pos })
    }

    // 挂载全局 drop 监听（因为 drop 可能发生在 Vue Flow 画布内的任何元素上）
    onMounted(() => document.addEventListener('drop', onDocumentDrop))
    onUnmounted(() => document.removeEventListener('drop', onDocumentDrop))

    return () => null // 不可见组件
  },
})

const props = defineProps<{
  novelId: string
}>()

const emit = defineEmits<{
  contextmenu: [event: MouseEvent, nodeId: string, enabled: boolean]
  nodeDetail: [nodeId: string]
}>()

const dagStore = useDAGStore()
const editMode = computed(() => dagStore.editMode)

/** Vue Flow v-model 绑定的可写 ref */
const flowNodes = ref<Node[]>([])
const flowEdges = ref<Edge[]>([])

function cloneNodesForFlow(nodes: Node[]): Node[] {
  return nodes.map((n) => ({
    ...n,
    position: { ...n.position },
    data: n.data != null && typeof n.data === 'object' ? { ...(n.data as object) } : n.data,
  }))
}

function cloneEdgesForFlow(edges: Edge[]): Edge[] {
  return edges.map((e) => ({
    ...e,
    style: e.style != null && typeof e.style === 'object' ? { ...(e.style as object) } : e.style,
    data: e.data != null && typeof e.data === 'object' ? { ...(e.data as object) } : e.data,
  }))
}

// 同步 dagStore → 本地 flow refs
watch(
  () => dagStore.vueFlowNodes,
  (next) => { flowNodes.value = cloneNodesForFlow(next as Node[]) },
  { immediate: true },
)

watch(
  () => dagStore.vueFlowEdges,
  (next) => { flowEdges.value = cloneEdgesForFlow(next as Edge[]) },
  { immediate: true },
)

// ─── 编辑模式事件处理 ───

/** 允许 drop（HTML5 drag-and-drop 要求 dragover 中 preventDefault 才能触发 drop） */
function handleDragOver(event: DragEvent) {
  if (event.dataTransfer?.types.includes('application/dag-node-type')) {
    event.preventDefault()
    if (event.dataTransfer) {
      event.dataTransfer.dropEffect = 'copy'
    }
  }
}

/** 由 FlowDropHelper 发来的正确画布坐标 */
function handleFlowDrop(payload: { nodeType: string; position: { x: number; y: number } }) {
  dagStore.addNode(payload.nodeType, payload.position)
}

/** 拖拽节点后更新位置 */
function handleNodeDragStop(event: { node: { id: string; position: { x: number; y: number } } }) {
  dagStore.updateNodePosition(event.node.id, event.node.position)
}

/** 连线 */
function handleConnect(connection: Connection) {
  if (connection.source && connection.target) {
    dagStore.addEdge(connection.source, connection.target)
  }
}

/** 边变更（删除边） */
function handleEdgesChange(changes: any[]) {
  for (const change of changes) {
    if (change.type === 'remove') {
      dagStore.removeEdge(change.id)
    }
  }
}

// ─── 通用事件处理 ───

function handleNodeClick(event: { node: { id: string } }) {
  dagStore.selectNode(event.node.id)
  emit('nodeDetail', event.node.id)
}

function handleNodeContextMenu(event: any) {
  const node = dagStore.dagDefinition?.nodes.find(n => n.id === event.node.id)
  if (node) {
    emit('contextmenu', event.event, node.id, node.enabled)
  }
}

function handleCustomNodeContextmenu(_event: MouseEvent) {
  // CustomNode 内部触发 contextmenu 时的事件
}
</script>

<style scoped>
.dag-canvas {
  width: 100%;
  height: 100%;
  background: var(--dag-canvas-bg);
}

/* ── Vue Flow 画布主体 ── */
:deep(.vue-flow) {
  background: var(--dag-canvas-bg);
}

/* ── 背景网格点 ── */
:deep(.vue-flow__background) {
  background: transparent;
}
:deep(.vue-flow__background line) {
  stroke: var(--dag-canvas-grid);
}

/* ── 小地图 ── */
:deep(.vue-flow__minimap) {
  border-radius: var(--app-radius-sm);
  overflow: hidden;
  border: 1px solid var(--app-border);
  background: var(--dag-node-bg);
  box-shadow: var(--app-shadow-md);
}

/* ── 控制面板 ── */
:deep(.vue-flow__controls) {
  border-radius: var(--app-radius-sm);
  overflow: hidden;
  border: 1px solid var(--app-border);
  background: var(--dag-toolbar-bg);
  box-shadow: var(--app-shadow-md);
}
:deep(.vue-flow__controls-button) {
  background: var(--dag-toolbar-bg);
  border-bottom: 1px solid var(--app-divider);
  fill: var(--app-text-secondary);
}
:deep(.vue-flow__controls-button:hover) {
  background: var(--dag-menu-hover);
}
:deep(.vue-flow__controls-button svg) {
  fill: var(--app-text-secondary);
}

/* ── 连接桩（Handle） ── */
:deep(.vue-flow__handle) {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 2px solid var(--dag-node-bg);
}

/* ── 连线拖拽预览 ── */
:deep(.vue-flow__connection-line) {
  stroke: var(--color-brand);
  stroke-width: 2;
}

/* ── 选中框 ── */
:deep(.vue-flow__selection) {
  border: 1px dashed var(--color-brand);
  background: var(--color-brand-light);
}

/* ── 画布视口过渡 ── */
:deep(.vue-flow__transformationpane) {
  transition: none;
}

/* 控件/小地图沉在工具栏之下，避免与顶栏视觉上「叠在一起」 */
:deep(.vue-flow__panel) {
  z-index: 4;
}

/* ── 编辑模式 ── */
.dag-canvas--edit {
  border: 2px dashed var(--color-brand);
  border-radius: var(--app-radius-sm);
}

.edit-mode-badge {
  position: absolute;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  padding: 6px 16px;
  background: var(--color-brand);
  color: #fff;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  z-index: 10;
  box-shadow: var(--app-shadow-md);
  pointer-events: none;
}
</style>
