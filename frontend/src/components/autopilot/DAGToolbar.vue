<template>
  <div class="dag-toolbar">
    <div class="toolbar-left">
      <n-text strong class="toolbar-title-text">🧭 DAG 可视化</n-text>

      <!-- 节点统计（精简） -->
      <n-tag v-if="dagStats" size="small" round>
        {{ dagStats.total }} 节点 · {{ dagStats.enabled }} 启用
        <template v-if="dagStats.running > 0">
          · <n-text type="info">{{ dagStats.running }} 运行中</n-text>
        </template>
        <template v-if="dagStats.error > 0">
          · <n-text type="error">{{ dagStats.error }} 错误</n-text>
        </template>
      </n-tag>

      <!-- ★ 托管模式状态指示 -->
      <n-tag
        v-if="autopilotStatus === 'running'"
        size="small"
        type="info"
        round
        :bordered="false"
      >
        <template #icon>
          <n-spin :size="12" />
        </template>
        托管运行中
      </n-tag>
      <n-tag
        v-else-if="autopilotStatus === 'paused'"
        size="small"
        type="warning"
        round
        :bordered="false"
      >
        ⏸️ 等待审阅
      </n-tag>
      <n-tag
        v-else-if="autopilotStatus === 'completed'"
        size="small"
        type="success"
        round
        :bordered="false"
      >
        ✅ 全书完成
      </n-tag>
      <n-tag
        v-else-if="autopilotStatus === 'error'"
        size="small"
        type="error"
        round
        :bordered="false"
      >
        ❌ 托管异常
      </n-tag>

      <!-- SSE 连接状态 -->
      <n-tooltip trigger="hover">
        <template #trigger>
          <div class="sse-indicator" :class="{ connected: sseConnected }" />
        </template>
        {{ sseConnected ? 'SSE 实时连接正常' : 'SSE 连接断开（托管未运行时不会自动重连）' }}
      </n-tooltip>

      <n-tooltip v-if="registryGapCount > 0" trigger="hover">
        <template #trigger>
          <n-tag size="small" type="error" round>缺注册 {{ registryGapCount }}</n-tag>
        </template>
        画布上有节点类型未在引擎注册表中找到，详见上方提示条。
      </n-tooltip>
      <n-tooltip v-else-if="linkageFailed" trigger="hover">
        <template #trigger>
          <n-tag size="small" type="warning" round>联动</n-tag>
        </template>
        注册表联动接口未加载完成，广场映射可能不完整。
      </n-tooltip>
    </div>

    <div class="toolbar-right">
      <!-- 编辑模式开关 -->
      <n-button
        size="tiny"
        :type="editMode ? 'warning' : 'default'"
        secondary
        @click="handleToggleEdit"
      >
        {{ editMode ? '🔒 退出编辑' : '✏️ 编辑' }}
      </n-button>

      <!-- 保存按钮（仅编辑模式可见） -->
      <n-button
        v-if="editMode"
        size="tiny"
        type="primary"
        :loading="isSaving"
        @click="handleSave"
      >
        💾 保存
      </n-button>

      <!-- 新建空白 DAG -->
      <n-button
        size="tiny"
        secondary
        @click="handleNewBlank"
      >
        ➕ 新建
      </n-button>

      <!-- 质量概览 -->
      <n-button size="tiny" secondary @click="$emit('open-quality')">
        📊 质量
      </n-button>

      <!-- 模板操作下拉 -->
      <n-dropdown trigger="click" :options="templateOptions" @select="handleTemplateAction">
        <n-button size="tiny" secondary>
          📋 模板 ▾
        </n-button>
      </n-dropdown>

      <!-- 版本信息 -->
      <n-text depth="3" class="toolbar-version" v-if="dagStats">
        v{{ dagStats.version || 1 }}
      </n-text>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, h } from 'vue'
import { useDAGStore } from '@/stores/dagStore'
import { dagApi } from '@/api/dag'
import { useMessage, useDialog } from 'naive-ui'

const dagStore = useDAGStore()
const message = useMessage()
const dialog = useDialog()

const registryGapCount = computed(() => dagStore.registryGaps.length)
const linkageFailed = computed(() => dagStore.registryLinkageFailed)
const editMode = computed(() => dagStore.editMode)
const isSaving = ref(false)

const props = defineProps<{
  novelId: string
  dagStats: {
    total: number
    enabled: number
    running: number
    success: number
    error: number
    bypassed: number
    version?: number
  }
  autopilotStatus: 'idle' | 'running' | 'paused' | 'completed' | 'error'
  sseConnected: boolean
}>()

defineEmits<{
  'switch-to-card': []
  'open-quality': []
}>()

// ─── 模板下拉选项 ───

const templateOptions = computed(() => [
  { key: 'save-as-template', label: '💾 保存为模板...' },
  { key: 'load-template', label: '📂 从模板加载...' },
])

// ─── 编辑模式 ───

function handleToggleEdit() {
  dagStore.setEditMode(!editMode.value)
  if (editMode.value) {
    message.info('已进入编辑模式，可拖拽节点、连线。完成后请点击保存。')
  } else {
    message.info('已退出编辑模式。')
  }
}

async function handleSave() {
  isSaving.value = true
  try {
    const result = await dagStore.saveDAG(props.novelId)
    message.success(`DAG 已保存（v${result.version}）`)
  } catch {
    message.error('保存失败，请检查节点和边的配置。')
  } finally {
    isSaving.value = false
  }
}

// ─── 新建空白 DAG ───

async function handleNewBlank() {
  try {
    await dagApi.newBlankDAG(props.novelId)
    await dagStore.loadDAG(props.novelId)
    dagStore.setEditMode(true)
    message.success('已创建空白画布，从左侧拖入节点开始编排')
  } catch {
    message.error('创建空白 DAG 失败')
  }
}

// ─── 模板操作 ───

async function handleTemplateAction(key: string) {
  if (key === 'save-as-template') {
    await handleSaveAsTemplate()
  } else if (key === 'load-template') {
    await handleLoadTemplate()
  }
}

async function handleSaveAsTemplate() {
  const dag = dagStore.dagDefinition
  if (!dag) {
    message.warning('没有可保存的 DAG')
    return
  }

  // 使用简单的 prompt 输入模板名
  const name = prompt('请输入模板名称（英文/数字/下划线/中文）：')
  if (!name) return
  if (name === '默认全流程') {
    message.warning('「默认全流程」是内置模板，请使用其他名称')
    return
  }

  try {
    const result = await dagApi.saveTemplate({
      name,
      nodes: dag.nodes,
      edges: dag.edges,
      description: dag.description || '',
    })
    message.success(`模板「${result.name}」已保存（v${result.version}）`)
  } catch {
    message.error('保存模板失败')
  }
}

async function handleLoadTemplate() {
  try {
    const { templates } = await dagApi.listTemplates()

    if (!templates || templates.length === 0) {
      message.info('暂无可用模板，请先编辑并保存一个 DAG 为模板。')
      return
    }

    const list = templates.map((t: any) => `  • ${t.name} — ${t.description || '无描述'} (${t.node_count}节点)`).join('\n')
    const choice = prompt(`可用模板：\n${list}\n\n输入要加载的模板名称：`)
    if (!choice) return

    const template = templates.find(t => t.name === choice.trim())
    if (!template) {
      message.warning(`模板「${choice}」不存在，请检查名称是否与列表中一致`)
      return
    }

    try {
      await dagApi.applyTemplate(props.novelId, template.name)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      message.error(`应用模板失败: ${msg}`)
      return
    }

    try {
      await dagStore.loadDAG(props.novelId)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      message.error(`刷新 DAG 失败: ${msg}`)
      return
    }

    message.success(`已应用模板「${template.name}」`)
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e)
    console.error('加载模板失败:', e)
    message.error(`加载模板失败: ${msg}`)
  }
}
</script>

<style scoped>
.dag-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 16px;
  border-bottom: 1px solid var(--dag-toolbar-border);
  background: var(--dag-toolbar-bg);
  gap: 12px;
  min-height: 40px;
  flex-wrap: wrap;
  row-gap: 8px;
  flex-shrink: 0;
  position: relative;
  z-index: 20;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-title-text {
  font-size: 14px;
  color: var(--app-text-primary);
}

.toolbar-version {
  font-size: 11px;
}

/* ── SSE 连接指示灯 ── */
.sse-indicator {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-danger);
  transition: background 0.3s;
  flex-shrink: 0;
}

.sse-indicator.connected {
  background: var(--color-success);
  animation: dag-pulse 2s ease-in-out infinite;
}

@keyframes dag-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>
