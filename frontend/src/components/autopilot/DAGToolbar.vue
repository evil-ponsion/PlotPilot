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

      <!-- 工作流信息 -->
      <n-button size="tiny" secondary @click="infoMode = 'edit'; showInfoDialog = true">📝 信息</n-button>

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

    <TemplateLoadDialog
      v-model:show="showTemplateDialog"
      @confirm="handleLoadTemplateFromList"
    />

    <!-- 工作流信息编辑弹窗（编辑 / 新建共用） -->
    <n-modal
      :show="showInfoDialog"
      preset="card"
      :title="infoMode === 'new' ? '新建工作流' : '工作流信息'"
      :style="{ maxWidth: '380px', width: '90vw' }"
      :bordered="true"
      @update:show="showInfoDialog = $event"
    >
      <div style="display:flex;flex-direction:column;gap:12px">
        <n-input v-model:value="infoName" placeholder="名称" maxlength="40" show-count />
        <n-input
          v-model:value="infoDescription"
          type="textarea"
          placeholder="简介（可选）"
          maxlength="200"
          :autosize="{ minRows: 2, maxRows: 4 }"
        />
      </div>
      <template #footer>
        <n-button size="small" @click="showInfoDialog = false">取消</n-button>
        <n-button size="small" type="primary" @click="handleSaveInfo">
          {{ infoMode === 'new' ? '创建' : '保存' }}
        </n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useDAGStore } from '@/stores/dagStore'
import { dagApi } from '@/api/dag'
import { useMessage } from 'naive-ui'
import TemplateLoadDialog from './TemplateLoadDialog.vue'

const dagStore = useDAGStore()
const message = useMessage()

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

const emit = defineEmits<{
  'switch-to-card': []
  'open-quality': []
  'dag-changed': []
}>()

// ─── 模板下拉选项 ───

const templateOptions = computed(() => [
  { key: 'save-as-template', label: '💾 保存为模板...' },
  { key: 'load-template', label: '📂 从模板加载...' },
])

// ─── 编辑模式 ───

async function handleToggleEdit() {
  if (editMode.value) {
    await handleSave()
    dagStore.setEditMode(false)
  } else {
    dagStore.setEditMode(true)
  }
}

async function handleSave() {
  if (isSaving.value) return  // 防重复调用
  isSaving.value = true
  try {
    const result = await dagStore.saveDAG(props.novelId)
    message.success(`DAG 已保存（v${result.version}）`)
    emit('dag-changed')
  } catch {
    message.error('保存失败')
  } finally {
    isSaving.value = false
  }
}

// ─── 新建空白 DAG ───

function handleNewBlank() {
  infoMode.value = 'new'
  showInfoDialog.value = true
}

// ─── 模板操作 ───

async function handleTemplateAction(key: string) {
  if (key === 'save-as-template') {
    await handleSaveAsTemplate()
  } else if (key === 'load-template') {
    showTemplateDialog.value = true
  }
}

async function handleSaveAsTemplate() {
  const dag = dagStore.dagDefinition
  if (!dag) { message.warning('没有可保存的 DAG'); return }
  const name = dag.name || '自定义工作流'
  try {
    await dagApi.saveTemplate({ name, nodes: dag.nodes as any, edges: dag.edges as any, description: dag.description || '' })
    message.success(`模板「${name}」已保存`)
    emit('dag-changed')
  } catch { message.error('保存模板失败') }
}

const showTemplateDialog = ref(false)

// ─── 工作流信息编辑（新建 / 编辑共用） ───
const showInfoDialog = ref(false)
const infoName = ref('')
const infoDescription = ref('')
const infoMode = ref<'new' | 'edit'>('edit')

watch(showInfoDialog, (v) => {
  if (!v) return
  if (infoMode.value === 'edit') {
    infoName.value = dagStore.dagDefinition?.name || ''
    infoDescription.value = dagStore.dagDefinition?.description || ''
  } else {
    infoName.value = '自定义工作流'
    infoDescription.value = ''
  }
})

async function handleSaveInfo() {
  const name = infoName.value.trim()
  if (!name) { message.warning('请输入名称'); return }

  if (infoMode.value === 'new') {
    // 新建工作流
    try {
      await dagApi.newBlankDAG(props.novelId, name)
      await dagStore.loadDAG(props.novelId)
      const dag = dagStore.dagDefinition
      if (dag) dag.description = infoDescription.value.trim() || dag.description
      dagStore.setEditMode(true)
      await dagStore.saveDAG(props.novelId)
      showInfoDialog.value = false
      message.success(`已创建「${name}」`)
      emit('dag-changed')
    } catch {
      message.error('创建失败')
    }
  } else {
    // 编辑工作流信息
    const dag = dagStore.dagDefinition
    if (!dag) return
    dag.name = name
    dag.description = infoDescription.value.trim()
    showInfoDialog.value = false
    try {
      await dagStore.saveDAG(props.novelId)
      message.success('工作流信息已更新')
      emit('dag-changed')
    } catch {
      message.error('保存失败')
    }
  }
}

async function handleLoadTemplateFromList(name: string) {
  try {
    await dagApi.applyTemplate(props.novelId, name)
    await dagStore.loadDAG(props.novelId)
    message.success(`已加载模板「${name}」`)
    emit('dag-changed')
  } catch { message.error('加载模板失败') }
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
