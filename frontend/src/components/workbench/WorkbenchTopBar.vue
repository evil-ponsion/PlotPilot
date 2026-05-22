<template>
  <div class="wb-topbar">
    <span class="wb-topbar-book">{{ novelTitle || '…' }}</span>
    <span class="wb-topbar-sep">·</span>
    <span class="wb-topbar-chapter">第 {{ chapterNumber || '?' }} 章</span>
    <span v-if="chapterTitle" class="wb-topbar-sep">·</span>
    <span v-if="chapterTitle" class="wb-topbar-title">{{ chapterTitle }}</span>
    <span class="wb-topbar-sep">·</span>
    <span class="wb-topbar-words">{{ formattedWords }}</span>
    <span class="wb-topbar-sep">·</span>
    <span class="wb-topbar-status" :class="statusClass">{{ statusLabel }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  novelTitle?: string
  chapterNumber?: number
  chapterTitle?: string
  wordCount?: number
  status?: string
}>()

const formattedWords = computed(() => {
  const w = props.wordCount || 0
  if (w >= 10000) return `${(w / 10000).toFixed(1)}万字`
  if (w >= 1000) return `${(w / 1000).toFixed(1)}千字`
  return `${w}字`
})

const statusLabel = computed(() => {
  switch (props.status) {
    case 'completed': return '✓'
    case 'draft': return '✏️'
    case 'generating': return '▶️'
    default: return '…'
  }
})

const statusClass = computed(() => {
  switch (props.status) {
    case 'completed': return 'status-ok'
    case 'draft': return 'status-draft'
    case 'generating': return 'status-running'
    default: return ''
  }
})
</script>

<style scoped>
.wb-topbar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 16px;
  height: 36px;
  background: var(--dag-toolbar-bg);
  border-bottom: 1px solid var(--app-border);
  font-size: 13px;
  flex-shrink: 0;
  user-select: none;
}

.wb-topbar-book {
  font-weight: 700;
  color: var(--app-text-primary);
}

.wb-topbar-sep {
  color: var(--app-text-muted);
  font-size: 10px;
}

.wb-topbar-chapter,
.wb-topbar-title {
  color: var(--app-text-secondary);
}

.wb-topbar-title {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wb-topbar-words {
  color: var(--app-text-muted);
  font-size: 12px;
}

.wb-topbar-status {
  font-weight: 700;
  font-size: 14px;
}
.status-ok { color: var(--color-success); }
.status-draft { color: var(--app-text-muted); }
.status-running { color: var(--color-brand); animation: pulse 1.5s ease-in-out infinite; }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
</style>
