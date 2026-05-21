<template>
  <div class="streaming-panel" v-if="visible">
    <div class="streaming-header">
      <span class="streaming-title">✍️ 生成监控</span>
      <n-tag v-if="status === 'running'" type="info" size="small" round>
        <template #icon><n-spin :size="12" /></template>
        生成中
      </n-tag>
      <n-tag v-else-if="status === 'completed'" type="success" size="small" round>✅ 完成</n-tag>
      <n-tag v-else-if="status === 'error'" type="error" size="small" round>❌ 错误</n-tag>
    </div>

    <!-- 进度条 -->
    <div v-if="totalBeats > 0" class="streaming-progress">
      <n-progress
        type="line"
        :percentage="progressPercent"
        :height="4"
        :color="'#3b82f6'"
      />
      <n-text depth="3" style="font-size: 11px; margin-top: 2px">
        节拍 {{ currentBeat }} / {{ totalBeats }} · 累计 {{ accumulatedWords }} 字
      </n-text>
    </div>

    <!-- 节拍列表 -->
    <div class="beat-stream-list">
      <div
        v-for="(beat, i) in beats"
        :key="i"
        class="beat-stream-item"
        :class="{ 'beat-stream-item--active': i === currentBeat - 1, 'beat-stream-item--done': i < currentBeat - 1 }"
      >
        <div class="beat-stream-status">
          <span v-if="i < currentBeat - 1" class="status-dot done">✓</span>
          <span v-else-if="i === currentBeat - 1 && status === 'running'" class="status-dot running"><n-spin :size="10" /></span>
          <span v-else class="status-dot pending">·</span>
        </div>
        <div class="beat-stream-content">
          <div class="beat-stream-meta">
            <span class="beat-num">第{{ i + 1 }}拍</span>
            <n-tag size="tiny" round>{{ beat.focus || 'mixed' }}</n-tag>
          </div>
          <div class="beat-stream-text" v-if="beat.content">
            {{ beat.content.slice(0, 200) }}{{ beat.content.length > 200 ? '...' : '' }}
          </div>
        </div>
      </div>
    </div>

    <!-- 累积输出 -->
    <div v-if="accumulatedContent" class="streaming-output">
      <div class="output-header">
        <span>📝 累积输出</span>
        <n-text depth="3" style="font-size: 11px">{{ accumulatedWords }} 字</n-text>
      </div>
      <div class="output-text">{{ accumulatedContent }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  novelId: string
}>()

const visible = ref(false)
const status = ref<'idle' | 'running' | 'completed' | 'error'>('idle')
const currentBeat = ref(0)
const totalBeats = ref(0)
const accumulatedWords = ref(0)

interface BeatItem {
  focus?: string
  content?: string
  words?: number
}

const beats = ref<BeatItem[]>([])

const progressPercent = computed(() =>
  totalBeats.value > 0 ? Math.round((currentBeat.value / totalBeats.value) * 100) : 0
)

const accumulatedContent = computed(() =>
  beats.value
    .filter(b => b.content)
    .map(b => b.content)
    .join('\n\n')
)

// ─── SSE 事件处理（由父组件调用）───

function handleBeatEvent(event: any) {
  const subtype = event.subtype || event.type || ''
  const metrics = event.metrics || {}
  const outputs = event.outputs || {}

  if (subtype === 'beat_start' || subtype === 'generation_start') {
    if (!visible.value) {
      visible.value = true
      status.value = 'running'
      beats.value = []
    }
    currentBeat.value = metrics.beat_index || 0
    totalBeats.value = metrics.total_beats || 0
    if (subtype === 'beat_start') {
      beats.value.push({ focus: metrics.focus || 'mixed' })
    }
  } else if (subtype === 'beat_complete') {
    const idx = (metrics.beat_index || 1) - 1
    if (idx >= 0 && idx < beats.value.length) {
      beats.value[idx] = {
        ...beats.value[idx],
        content: outputs.content || '',
        words: metrics.word_count || 0,
      }
    }
    accumulatedWords.value = metrics.accumulated_words || 0
  } else if (subtype === 'generation_complete') {
    accumulatedWords.value = metrics.word_count || 0
  }
}

function handleDAGEnd() {
  if (status.value === 'running') {
    status.value = 'completed'
  }
}

function handleDAGError() {
  status.value = 'error'
}

function reset() {
  visible.value = false
  status.value = 'idle'
  currentBeat.value = 0
  totalBeats.value = 0
  accumulatedWords.value = 0
  beats.value = []
}

defineExpose({ handleBeatEvent, handleDAGEnd, handleDAGError, reset })
</script>

<style scoped>
.streaming-panel {
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 15;
  width: 320px;
  max-height: calc(100% - 40px);
  background: var(--dag-toolbar-bg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  box-shadow: var(--app-shadow-lg);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.streaming-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--app-divider);
}

.streaming-title {
  font-size: 13px;
  font-weight: 700;
  flex: 1;
}

.streaming-progress {
  padding: 8px 12px 4px;
}

.beat-stream-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.beat-stream-item {
  display: flex;
  gap: 8px;
  padding: 6px 4px;
  border-radius: var(--app-radius-xs);
  margin-bottom: 4px;
}

.beat-stream-item--active {
  background: var(--color-brand-light);
}

.beat-stream-item--done {
  opacity: 0.7;
}

.beat-stream-status {
  flex-shrink: 0;
  width: 18px;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 2px;
}

.status-dot.done { color: var(--color-success); font-weight: 700; }
.status-dot.running { color: var(--color-brand); }
.status-dot.pending { color: var(--app-text-muted); }

.beat-stream-content {
  flex: 1;
  min-width: 0;
}

.beat-stream-meta {
  display: flex;
  gap: 4px;
  align-items: center;
  margin-bottom: 2px;
}

.beat-num {
  font-size: 11px;
  font-weight: 600;
}

.beat-stream-text {
  font-size: 11px;
  color: var(--app-text-secondary);
  line-height: 1.4;
  word-break: break-all;
}

.streaming-output {
  border-top: 1px solid var(--app-divider);
  padding: 8px 12px;
  max-height: 200px;
  overflow-y: auto;
}

.output-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
  font-size: 11px;
  font-weight: 600;
}

.output-text {
  font-size: 11px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--app-text);
}
</style>
