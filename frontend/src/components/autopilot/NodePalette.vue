<template>
  <div class="node-palette">
    <div class="palette-header">节点类型</div>
    <div class="palette-list">
      <div
        v-for="[type, meta] in nodeTypes"
        :key="type"
        class="palette-item"
        :style="{ '--node-color': meta.color || '#6366f1' }"
        draggable="true"
        @dragstart="handleDragStart($event, type)"
      >
        <span class="palette-icon">{{ meta.icon || '📦' }}</span>
        <span class="palette-label">{{ meta.display_name || type }}</span>
        <span class="palette-category">{{ CATEGORY_LABELS_SHORT[meta.category] || meta.category }}</span>
      </div>
    </div>
    <div v-if="nodeTypes.length === 0" class="palette-empty">
      加载节点类型中...
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useDAGStore } from '@/stores/dagStore'
import type { NodeCategory } from '@/types/dag'

const CATEGORY_LABELS_SHORT: Record<NodeCategory, string> = {
  context: '上下文',
  execution: '执行',
  validation: '校验',
  gateway: '网关',
}

const dagStore = useDAGStore()

const nodeTypes = computed(() => {
  const reg = dagStore.nodeTypeRegistry
  if (!reg) return []
  return Object.entries(reg).filter(([, meta]) => {
    // 过滤掉 INJECT 模式的节点（仅作为子提示词注入，不可独立放入画布）
    return (meta as any).prompt_mode !== 'inject'
  })
})

function handleDragStart(event: DragEvent, nodeType: string) {
  if (!event.dataTransfer) return
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('application/dag-node-type', nodeType)
}
</script>

<style scoped>
.node-palette {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 10;
  width: 200px;
  max-height: calc(100% - 60px);
  background: var(--dag-toolbar-bg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  box-shadow: var(--app-shadow-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.palette-header {
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 700;
  color: var(--app-text-secondary);
  border-bottom: 1px solid var(--app-divider);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.palette-list {
  overflow-y: auto;
  flex: 1;
  padding: 4px;
}

.palette-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: var(--app-radius-xs);
  cursor: grab;
  user-select: none;
  transition: background 0.15s;
  margin-bottom: 2px;
}

.palette-item:hover {
  background: var(--dag-menu-hover);
}

.palette-item:active {
  cursor: grabbing;
  background: var(--color-brand-light);
}

.palette-icon {
  font-size: 16px;
  width: 24px;
  text-align: center;
  flex-shrink: 0;
}

.palette-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--app-text);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.palette-category {
  font-size: 10px;
  color: var(--app-text-muted);
  background: var(--app-divider);
  padding: 1px 5px;
  border-radius: 3px;
  flex-shrink: 0;
}

.palette-empty {
  padding: 16px;
  text-align: center;
  font-size: 12px;
  color: var(--app-text-muted);
}
</style>
