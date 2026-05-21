<template>
  <n-modal
    :show="show"
    preset="card"
    title="📊 章节质量概览"
    :style="{ maxWidth: '800px', width: '90vw', maxHeight: '85vh' }"
    :bordered="true"
    size="large"
    @update:show="$emit('update:show', $event)"
  >
    <div v-if="loading" class="dash-loading">
      <n-spin size="medium" />
    </div>

    <div v-else-if="error" class="dash-error">
      <n-text type="error">{{ error }}</n-text>
    </div>

    <div v-else-if="data" class="quality-dashboard">
      <!-- 概览卡片 -->
      <div class="overview-cards">
        <div class="overview-card">
          <div class="card-value">{{ data.summary.avg_tension }}</div>
          <div class="card-label">均张力</div>
        </div>
        <div class="overview-card">
          <div class="card-value">{{ data.summary.avg_similarity }}</div>
          <div class="card-label">均声线相似度</div>
        </div>
        <div class="overview-card">
          <div class="card-value">{{ (data.summary.avg_word_count / 1000).toFixed(1) }}k</div>
          <div class="card-label">均字数</div>
        </div>
        <div class="overview-card">
          <div class="card-value">{{ data.total_words.toLocaleString() }}</div>
          <div class="card-label">总字数 · {{ data.completed_chapters }}/{{ data.total_chapters }}章</div>
        </div>
      </div>

      <!-- 异常提醒 -->
      <div v-if="data.anomalies.length > 0" class="anomaly-bar">
        <n-alert type="warning" show-icon :bordered="false">
          <template #header>
            检测到 {{ data.anomalies.length }} 个异常章节
          </template>
          <span v-for="a in data.anomalies" :key="a.chapter_number" class="anomaly-tag">
            第{{ a.chapter_number }}章: {{ a.issues.map(labelIssue).join('、') }}
          </span>
        </n-alert>
      </div>

      <!-- 章节列表 -->
      <div class="chapter-table-wrap">
        <table class="chapter-table">
          <thead>
            <tr>
              <th>章</th>
              <th>字数</th>
              <th>张力</th>
              <th>声线</th>
              <th>句长</th>
              <th>DAG 版本</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="ch in data.chapters"
              :key="ch.chapter_number"
              :class="{ 'row-anomaly': isAnomaly(ch.chapter_number) }"
            >
              <td class="col-num">{{ ch.chapter_number }}</td>
              <td>{{ (ch.word_count / 1000).toFixed(1) }}k</td>
              <td>
                <span :style="{ color: tensionColor(ch.tension_score) }">
                  {{ ch.tension_score || '-' }}
                </span>
              </td>
              <td>
                <span :style="{ color: similarityColor(ch.similarity_score) }">
                  {{ ch.similarity_score?.toFixed(2) || '-' }}
                </span>
              </td>
              <td>{{ ch.avg_sentence_length?.toFixed(0) || '-' }}</td>
              <td>
                <n-text depth="3" style="font-size:10px">
                  v{{ ch.dag_version || '-' }} {{ ch.dag_fingerprint || '' }}
                </n-text>
              </td>
              <td>
                <n-tag size="tiny" :type="ch.status === 'completed' ? 'success' : 'default'" round>
                  {{ ch.status === 'completed' ? '✓' : '···' }}
                </n-tag>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 趋势图（简易文字版） -->
      <div class="trend-section">
        <div class="section-title">张力趋势</div>
        <div class="trend-bar">
          <div
            v-for="ch in data.chapters"
            :key="'t'+ch.chapter_number"
            class="trend-col"
            :title="`第${ch.chapter_number}章: ${ch.tension_score || 0}`"
          >
            <div
              class="trend-fill"
              :style="{
                height: Math.max(2, (ch.tension_score || 0)) + '%',
                background: tensionColor(ch.tension_score),
              }"
            />
            <span class="trend-label">{{ ch.chapter_number }}</span>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <n-button size="small" @click="load" :loading="loading">🔄 刷新</n-button>
      <n-button size="small" type="primary" @click="$emit('update:show', false)">关闭</n-button>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { apiClient } from '@/api/config'

const props = defineProps<{ show: boolean; novelId: string }>()
defineEmits<{ 'update:show': [boolean] }>()

const loading = ref(false)
const error = ref('')
const data = ref<any>(null)

function tensionColor(v: number | null): string {
  if (!v) return 'var(--app-text-muted)'
  if (v < 30) return '#ef4444'
  if (v > 85) return '#f59e0b'
  return '#22c55e'
}
function similarityColor(v: number | null | undefined): string {
  if (v == null) return 'var(--app-text-muted)'
  if (v < 0.65) return '#ef4444'
  if (v < 0.75) return '#f59e0b'
  return '#22c55e'
}

function isAnomaly(ch: number): boolean {
  return data.value?.anomalies?.some((a: any) => a.chapter_number === ch) ?? false
}

function labelIssue(code: string): string {
  const map: Record<string, string> = {
    tension_low: '张力偏低', tension_high: '张力偏高',
    voice_drift: '声线漂移',
  }
  if (code.startsWith('tension_jump_')) return `张力跳变(${code.split('_')[2]})`
  return map[code] || code
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await apiClient.get(`/dag/${props.novelId}/quality-overview`)
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

watch(() => props.show, s => { if (s) load() })
</script>

<style scoped>
.dash-loading, .dash-error {
  display: flex; justify-content: center; padding: 40px 0;
}

.overview-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-bottom: 16px;
}
.overview-card {
  background: var(--app-surface-subtle);
  border-radius: var(--app-radius-sm);
  padding: 14px 12px;
  text-align: center;
}
.card-value { font-size: 22px; font-weight: 700; }
.card-label { font-size: 11px; color: var(--app-text-muted); margin-top: 2px; }

.anomaly-bar { margin-bottom: 12px; }
.anomaly-tag { display: inline-block; margin: 2px 6px 2px 0; font-size: 11px; }

.chapter-table-wrap { max-height: 300px; overflow-y: auto; margin-bottom: 16px; }
.chapter-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.chapter-table th { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--app-divider); color: var(--app-text-muted); font-size: 10px; text-transform: uppercase; }
.chapter-table td { padding: 5px 8px; border-bottom: 1px solid var(--app-divider-light); }
.row-anomaly { background: var(--color-warning-dim); }
.col-num { font-weight: 600; width: 36px; }

.trend-section { margin-bottom: 8px; }
.section-title { font-size: 11px; font-weight: 600; margin-bottom: 6px; color: var(--app-text-secondary); }
.trend-bar { display: flex; align-items: flex-end; gap: 3px; height: 80px; padding: 0 4px; }
.trend-col { flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; justify-content: flex-end; }
.trend-fill { width: 100%; border-radius: 2px 2px 0 0; min-height: 2px; transition: height .3s; }
.trend-label { font-size: 9px; color: var(--app-text-muted); margin-top: 2px; }
</style>
