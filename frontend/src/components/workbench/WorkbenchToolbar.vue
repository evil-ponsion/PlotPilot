<template>
  <div class="wb-toolbar">
    <div class="toolbar-group">
      <n-button size="tiny" :type="autopilotRunning ? 'warning' : 'primary'" @click="$emit('autopilot')">
        {{ autopilotRunning ? '⏸️ 托管中' : '🚀 启动全托管' }}
      </n-button>
    </div>

    <div class="toolbar-group">
      <n-button size="tiny" secondary @click="$emit('quickGenerate')">
        ⚡ 快速生成
      </n-button>
      <n-button size="tiny" secondary @click="$emit('regenerate')">
        🔄 重新生成
      </n-button>
      <n-button size="tiny" secondary @click="$emit('tensionDiagnosis')">
        🔍 张力诊断
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
defineProps<{ autopilotRunning?: boolean }>()
defineEmits<{
  autopilot: []
  quickGenerate: []
  regenerate: []
  tensionDiagnosis: []
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
