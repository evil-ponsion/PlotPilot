<template>
  <div class="wb-toolbar">
    <div class="toolbar-group">
      <n-button size="tiny" :type="isRunning ? 'warning' : 'primary'" @click="$emit('run')">
        {{ isRunning ? '⏸️ 暂停' : '▶️ 运行' }}
      </n-button>
    </div>

    <div class="toolbar-group">
      <n-button size="tiny" quaternary @click="$emit('search')">
        🔍
      </n-button>
      <n-button size="tiny" quaternary @click="$emit('replace')">
        🔄
      </n-button>
    </div>

    <div class="toolbar-spacer" />

    <div class="toolbar-group">
      <n-button size="tiny" secondary @click="$emit('save')">
        💾 保存
      </n-button>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ isRunning?: boolean }>()
defineEmits<{
  run: []
  search: []
  replace: []
  save: []
}>()
</script>

<style scoped>
.wb-toolbar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-bottom: 1px solid var(--app-divider-light);
  background: var(--app-surface-subtle);
  flex-shrink: 0;
  height: 32px;
}

.toolbar-group {
  display: flex;
  gap: 2px;
}

.toolbar-spacer {
  flex: 1;
}
</style>
