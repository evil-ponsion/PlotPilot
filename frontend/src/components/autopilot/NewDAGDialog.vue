<template>
  <n-modal
    :show="show"
    preset="card"
    title="新建工作流"
    :style="{ maxWidth: '380px', width: '90vw' }"
    :bordered="true"
    @update:show="$emit('update:show', $event)"
  >
    <div class="new-dag-form">
      <n-input
        ref="inputRef"
        v-model:value="name"
        placeholder="输入工作流名称"
        maxlength="40"
        show-count
        @keyup.enter="confirm"
      />
    </div>
    <template #footer>
      <n-button size="small" @click="$emit('update:show', false)">取消</n-button>
      <n-button size="small" type="primary" @click="confirm">创建</n-button>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{
  'update:show': [boolean]
  confirm: [name: string]
}>()

const name = ref('')
const inputRef = ref<any>(null)

watch(() => props.show, async (s) => {
  if (s) {
    name.value = '自定义工作流'
    await nextTick()
    inputRef.value?.focus?.()
    inputRef.value?.select?.()
  }
})

function confirm() {
  const trimmed = name.value.trim()
  if (!trimmed) return
  emit('confirm', trimmed)
  emit('update:show', false)
}
</script>

<style scoped>
.new-dag-form {
  padding: 4px 0;
}
</style>
