<template>
  <n-modal
    :show="show"
    preset="card"
    title="🥁 节拍规划"
    :style="{ maxWidth: '700px', width: '90vw', maxHeight: '80vh' }"
    :bordered="true"
    size="large"
    @update:show="$emit('update:show', $event)"
  >
    <div v-if="loading" class="planner-loading">
      <n-spin size="medium" />
      <n-text depth="3">正在生成节拍规划...</n-text>
    </div>

    <div v-else-if="error" class="planner-error">
      <n-text type="error">{{ error }}</n-text>
      <n-button size="small" @click="load" style="margin-top: 8px">重试</n-button>
    </div>

    <div v-else class="beat-planner">
      <div class="planner-summary">
        <n-text>
          第 {{ data?.chapter_number }} 章 · {{ beats.length }} 个节拍
        </n-text>
      </div>

      <div class="beat-list">
        <div
          v-for="(beat, i) in beats"
          :key="i"
          class="beat-card"
          :class="{ 'beat-card--editing': editingIndex === i }"
        >
          <div class="beat-header">
            <div class="beat-order">
              <n-button
                size="tiny"
                quaternary
                :disabled="i === 0"
                @click="moveBeat(i, -1)"
              >↑</n-button>
              <span class="beat-num">第{{ i + 1 }}拍</span>
              <n-button
                size="tiny"
                quaternary
                :disabled="i >= beats.length - 1"
                @click="moveBeat(i, 1)"
              >↓</n-button>
            </div>

            <div class="beat-meta" v-if="editingIndex !== i">
              <n-tag size="tiny" round>{{ beat.focus || 'mixed' }}</n-tag>
              <n-tag size="tiny" round type="info">{{ beat.target_words || 0 }} 字</n-tag>
            </div>

            <div class="beat-actions">
              <n-button size="tiny" quaternary @click="startEdit(i)">✏️</n-button>
              <n-button size="tiny" quaternary type="error" @click="removeBeat(i)">🗑️</n-button>
            </div>
          </div>

          <div v-if="editingIndex === i" class="beat-edit">
            <n-form label-placement="top" size="small">
              <n-form-item label="描述">
                <n-input v-model:value="editForm.description" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" />
              </n-form-item>
              <n-form-item label="焦点">
                <n-select
                  v-model:value="editForm.focus"
                  :options="focusOptions"
                  size="small"
                />
              </n-form-item>
              <n-form-item label="目标字数">
                <n-input-number v-model:value="editForm.target_words" :min="100" :max="5000" :step="100" size="small" />
              </n-form-item>
              <n-form-item label="过渡方式">
                <n-input v-model:value="editForm.transition_from_prev" size="small" placeholder="从上一拍如何过渡" />
              </n-form-item>
              <div style="display:flex;gap:8px">
                <n-button size="tiny" type="primary" @click="saveEdit">保存</n-button>
                <n-button size="tiny" @click="cancelEdit">取消</n-button>
              </div>
            </n-form>
          </div>

          <div v-else class="beat-preview">
            {{ beat.description || '(无描述)' }}
            <span v-if="beat.transition_from_prev" class="beat-transition">
              ← {{ beat.transition_from_prev }}
            </span>
          </div>
        </div>
      </div>

      <div class="planner-add">
        <n-button size="small" dashed @click="addBeat">+ 添加节拍</n-button>
      </div>
    </div>

    <template #footer>
      <div class="planner-footer">
        <n-button size="small" @click="load" :loading="loading">🔄 LLM 重新规划</n-button>
        <n-button size="small" type="primary" @click="$emit('update:show', false)">关闭</n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { dagApi } from '@/api/dag'

const props = defineProps<{
  show: boolean
  novelId: string
}>()

defineEmits<{ 'update:show': [boolean] }>()

interface Beat {
  description: string
  target_words: number
  focus: string
  transition_from_prev: string
  scene_goal: string
  location_id: string
  expansion_hints: string[]
}

const focusOptions = [
  { label: '感官描写', value: 'sensory' },
  { label: '对话', value: 'dialogue' },
  { label: '动作', value: 'action' },
  { label: '情绪', value: 'emotion' },
  { label: '混合', value: 'mixed' },
]

const loading = ref(false)
const error = ref('')
const data = ref<{ novel_id: string; chapter_number: number; beats: Beat[]; beat_count: number } | null>(null)
const beats = ref<Beat[]>([])
const editingIndex = ref(-1)
const editForm = ref<Beat>({ description: '', target_words: 600, focus: 'mixed', transition_from_prev: '', scene_goal: '', location_id: '', expansion_hints: [] })

async function load() {
  loading.value = true
  error.value = ''
  try {
    data.value = await dagApi.previewBeats(props.novelId)
    beats.value = [...(data.value?.beats || [])]
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function moveBeat(i: number, dir: number) {
  const j = i + dir
  if (j < 0 || j >= beats.value.length) return
  const arr = [...beats.value]
  ;[arr[i], arr[j]] = [arr[j], arr[i]]
  beats.value = arr
}

function removeBeat(i: number) {
  beats.value = beats.value.filter((_, idx) => idx !== i)
  if (editingIndex.value === i) cancelEdit()
}

function addBeat() {
  beats.value.push({ description: '', target_words: 600, focus: 'mixed', transition_from_prev: '', scene_goal: '', location_id: '', expansion_hints: [] })
  startEdit(beats.value.length - 1)
}

function startEdit(i: number) {
  editingIndex.value = i
  editForm.value = { ...beats.value[i] }
}

function saveEdit() {
  if (editingIndex.value >= 0) {
    beats.value[editingIndex.value] = { ...editForm.value }
  }
  editingIndex.value = -1
}

function cancelEdit() {
  editingIndex.value = -1
}

watch(() => props.show, (s) => { if (s) load() })
</script>

<style scoped>
.planner-loading, .planner-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 32px 0;
}

.planner-summary {
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--app-surface-subtle);
  border-radius: var(--app-radius-sm);
}

.beat-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.beat-card {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  padding: 8px 10px;
  transition: border-color .15s;
}

.beat-card--editing {
  border-color: var(--color-brand);
}

.beat-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.beat-order {
  display: flex;
  align-items: center;
  gap: 2px;
}

.beat-num {
  font-size: 11px;
  font-weight: 600;
  color: var(--app-text-secondary);
  min-width: 40px;
}

.beat-meta {
  display: flex;
  gap: 4px;
  flex: 1;
}

.beat-actions {
  display: flex;
  gap: 2px;
}

.beat-preview {
  font-size: 12px;
  color: var(--app-text);
  line-height: 1.5;
}

.beat-transition {
  display: block;
  font-size: 10px;
  color: var(--app-text-muted);
  margin-top: 2px;
}

.beat-edit {
  margin-top: 8px;
}

.planner-add {
  display: flex;
  justify-content: center;
}

.planner-footer {
  display: flex;
  justify-content: space-between;
}
</style>
