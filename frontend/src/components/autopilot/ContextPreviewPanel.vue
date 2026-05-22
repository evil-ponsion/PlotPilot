<template>
  <n-modal
    :show="show"
    preset="card"
    title="📋 上下文预览"
    :style="{ maxWidth: '800px', width: '90vw', maxHeight: '80vh' }"
    :bordered="true"
    size="large"
    @update:show="$emit('update:show', $event)"
  >
    <div v-if="loading" class="preview-loading">
      <n-spin size="medium" />
      <n-text depth="3">正在收集上下文数据...</n-text>
    </div>

    <div v-else-if="error" class="preview-error">
      <n-text type="error">{{ error }}</n-text>
      <n-button size="small" @click="load" style="margin-top: 8px">重试</n-button>
    </div>

    <div v-else class="context-preview">
      <!-- 总览 -->
      <div class="preview-summary">
        <n-text>
          第 {{ data?.chapter_number }} 章上下文 —
          共 <strong>{{ data?.sections?.length || 0 }}</strong> 个来源，
          预估 <strong>{{ data?.total_estimated_tokens || 0 }}</strong> tokens
        </n-text>
        <n-progress
          type="line"
          :percentage="tokenPercent"
          :color="tokenColor"
          :height="6"
          style="margin-top: 6px"
        />
        <n-text depth="3" style="font-size: 11px">
          Token 预算 {{ maxTokens?.toLocaleString?.() || 0 }} / {{ data?.total_estimated_tokens || 0 }} 已用
        </n-text>
      </div>

      <!-- 分类层级 -->
      <div v-for="tier in tiers" :key="tier.key" class="preview-tier">
        <div class="tier-header" :style="{ borderLeftColor: tier.color }">
          <span class="tier-label">{{ tier.label }}</span>
          <n-text depth="3" style="font-size: 11px">{{ tier.desc }}</n-text>
        </div>

        <div
          v-for="section in tier.sections"
          :key="section.node_type + section.port"
          class="preview-section"
        >
          <div class="section-header" @click="section._expanded = !section._expanded">
            <span class="section-toggle">{{ section._expanded ? '▾' : '▸' }}</span>
            <span class="section-icon">{{ section._icon || '📄' }}</span>
            <span class="section-label">{{ section.node_label }} · {{ section.port }}</span>
            <n-tag size="tiny" round>{{ section.estimated_tokens }} tok</n-tag>
          </div>
          <div v-if="section._expanded" class="section-content">
            <n-input
              v-model:value="section.content"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 12 }"
              size="small"
            />
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="preview-footer">
        <n-button size="small" @click="load" :loading="loading">🔄 刷新</n-button>
        <n-button size="small" type="primary" @click="$emit('update:show', false)">关闭</n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { dagApi } from '@/api/dag'

const props = defineProps<{
  show: boolean
  novelId: string
}>()

defineEmits<{ 'update:show': [boolean] }>()

interface Section {
  node_type: string
  node_label: string
  port: string
  content: string
  estimated_tokens: number
  _icon?: string
  _expanded?: boolean
}

interface Tier {
  key: string
  label: string
  desc: string
  color: string
  sections: Section[]
}

const T0_PORTS = new Set(['world_rules','taboos','atmosphere','fact_lock','previously_on','current_act_goal','character_block','foreshadowing_block','voice_block','debt_due_block','context'])
const T1_PORTS = new Set(['storyline_block','causal_chains'])
const T2_PORTS = new Set(['recent_summary'])

const ICON_MAP: Record<string, string> = {
  world_rules: '📋', taboos: '🚫', atmosphere: '🌫️',
  fact_lock: '🧠', previously_on: '📖', current_act_goal: '🎯',
  character_block: '👤', foreshadowing_block: '🪝',
  voice_block: '🎭', debt_due_block: '💰',
  storyline_block: '🧭', causal_chains: '🔗', recent_summary: '📝',
  context: '🧩',
}

const loading = ref(false)
const error = ref('')
const data = ref<{ novel_id: string; chapter_number: number; sections: Section[]; total_estimated_tokens: number } | null>(null)
const maxTokens = 20000

const tokenPercent = computed(() => {
  if (!data.value) return 0
  return Math.min(100, Math.round(data.value.total_estimated_tokens / maxTokens * 100))
})

const tokenColor = computed(() => {
  const p = tokenPercent.value
  if (p < 50) return '#22c55e'
  if (p < 80) return '#f59e0b'
  return '#ef4444'
})

const tiers = computed((): Tier[] => {
  if (!data.value) return []
  const sections = (data.value.sections || []).map(s => ({
    ...s,
    _icon: ICON_MAP[s.port] || '📄',
    _expanded: false,
  }))

  const t0 = sections.filter(s => T0_PORTS.has(s.port))
  const t1 = sections.filter(s => T1_PORTS.has(s.port))
  const t2 = sections.filter(s => T2_PORTS.has(s.port))
  const rest = sections.filter(s => !T0_PORTS.has(s.port) && !T1_PORTS.has(s.port) && !T2_PORTS.has(s.port))

  const result: Tier[] = []
  if (t0.length) result.push({ key: 't0', label: 'T0 强制槽', desc: '绝不删减', color: '#ef4444', sections: t0 })
  if (t1.length) result.push({ key: 't1', label: 'T1 可压缩槽', desc: '预算不足时按比例压缩', color: '#f59e0b', sections: t1 })
  if (t2.length) result.push({ key: 't2', label: 'T2 动态水位', desc: '预算不足时归零', color: '#3b82f6', sections: t2 })
  if (rest.length) result.push({ key: 'other', label: '其他', desc: '', color: '#6b7280', sections: rest })
  return result
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await dagApi.previewContext(props.novelId)
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

watch(() => props.show, (s) => { if (s) load() })
</script>

<style scoped>
.preview-loading, .preview-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px 0;
}

.preview-summary {
  margin-bottom: 16px;
  padding: 12px;
  background: var(--app-surface-subtle);
  border-radius: var(--app-radius-sm);
}

.preview-tier {
  margin-bottom: 12px;
}

.tier-header {
  padding: 4px 8px;
  border-left: 3px solid;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.tier-label {
  font-weight: 700;
  font-size: 12px;
}

.preview-section {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-xs);
  margin-bottom: 4px;
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
}

.section-header:hover {
  background: var(--app-surface-subtle);
}

.section-toggle {
  width: 12px;
  font-size: 10px;
  color: var(--app-text-muted);
}

.section-icon { font-size: 14px; }
.section-label { flex: 1; font-weight: 500; }

.section-content {
  padding: 0 8px 8px;
}

.preview-footer {
  display: flex;
  justify-content: space-between;
}
</style>
