<template>
  <n-modal
    :show="show"
    preset="card"
    title="⏸️ 审阅报告"
    :style="{ maxWidth: '640px', width: '90vw', maxHeight: '80vh' }"
    :bordered="true"
    size="large"
    @update:show="$emit('update:show', $event)"
  >
    <div v-if="loading" class="review-loading">
      <n-spin size="medium" />
      <n-text depth="3">加载审阅报告...</n-text>
    </div>

    <div v-else-if="!report" class="review-empty">
      <n-text depth="3">暂无审阅报告（DAG 尚未运行或审阅节点被跳过）</n-text>
    </div>

    <div v-else class="review-report">
      <!-- 总结 -->
      <div class="review-summary" :class="report.approved ? 'summary-ok' : 'summary-issue'">
        {{ report.summary }}
      </div>

      <!-- 逐项 -->
      <div
        v-for="(section, i) in report.sections"
        :key="i"
        class="review-section"
        :class="`review-${section.severity}`"
      >
        <div class="review-section-header">
          <span class="review-section-title">{{ section.title }}</span>
          <n-tag
            size="tiny"
            :type="section.severity === 'error' ? 'error' : section.severity === 'warning' ? 'warning' : 'info'"
            round
          >
            {{ section.severity === 'error' ? '严重' : section.severity === 'warning' ? '注意' : '信息' }}
          </n-tag>
        </div>
        <div class="review-section-body">
          <p class="review-detail">{{ section.detail }}</p>

          <!-- 张力维度 -->
          <div v-if="section.type === 'tension' && section.dimensions" class="review-dimensions">
            <div v-for="(v, k) in section.dimensions" :key="k" class="dim-row">
              <span class="dim-label">{{ k }}</span>
              <n-progress type="line" :percentage="Number(v)" :height="4" :color="dimColor(Number(v))" style="flex:1" />
              <span class="dim-value">{{ v }}</span>
            </div>
          </div>

          <!-- Anti-AI hits -->
          <div v-if="section.hits && section.hits.length" class="review-hits">
            <div v-for="(hit, j) in section.hits" :key="j" class="hit-item">{{ hit }}</div>
          </div>

          <!-- 建议 -->
          <div v-if="section.suggestion" class="review-suggestion">
            💡 {{ section.suggestion }}
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="review-footer">
        <n-button size="small" @click="load" :loading="loading">🔄 刷新</n-button>
        <n-button size="small" type="primary" @click="$emit('update:show', false)">关闭</n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useDAGStore } from '@/stores/dagStore'

const props = defineProps<{
  show: boolean
  novelId: string
}>()

defineEmits<{ 'update:show': [boolean] }>()

const dagStore = useDAGStore()
const loading = ref(false)
const report = ref<any>(null)

function dimColor(v: number): string {
  if (v >= 70) return '#22c55e'
  if (v >= 40) return '#f59e0b'
  return '#ef4444'
}

async function load() {
  loading.value = true
  try {
    // 从 dagStore 读取 gw_review 节点的运行时输出
    const reviewNode = dagStore.dagDefinition?.nodes.find(n => n.type === 'gw_review')
    if (reviewNode) {
      const state = dagStore.nodeStates.get(reviewNode.id)
      const outputs = state?.outputs as any
      report.value = outputs?.review_report || null
    }
  } finally {
    loading.value = false
  }
}

watch(() => props.show, (s) => { if (s) load() })
</script>

<style scoped>
.review-loading, .review-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px 0;
}

.review-summary {
  padding: 12px;
  border-radius: var(--app-radius-sm);
  margin-bottom: 16px;
  font-weight: 600;
  font-size: 13px;
  text-align: center;
}
.summary-ok { background: var(--color-success-dim); color: var(--color-success); }
.summary-issue { background: var(--color-danger-dim); color: var(--color-danger); }

.review-section {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  padding: 10px 12px;
  margin-bottom: 8px;
}
.review-error { border-left: 3px solid var(--color-danger); }
.review-warning { border-left: 3px solid var(--color-warning); }
.review-info { border-left: 3px solid var(--color-info); }

.review-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.review-section-title { font-weight: 600; font-size: 13px; }

.review-detail { font-size: 12px; color: var(--app-text-secondary); margin: 0 0 6px; line-height: 1.5; }

.review-dimensions { margin: 8px 0; }
.dim-row { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.dim-label { font-size: 11px; width: 70px; flex-shrink: 0; }
.dim-value { font-size: 10px; width: 30px; text-align: right; color: var(--app-text-muted); }

.review-hits { margin: 6px 0; }
.hit-item { font-size: 11px; color: var(--app-text-secondary); padding: 2px 0; padding-left: 12px; border-left: 2px solid var(--app-divider); }

.review-suggestion { font-size: 11px; color: var(--color-brand); margin-top: 4px; }

.review-footer { display: flex; justify-content: space-between; }
</style>
