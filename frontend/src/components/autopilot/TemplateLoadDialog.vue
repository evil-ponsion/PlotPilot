<template>
  <n-modal
    :show="show"
    preset="card"
    title="从模板加载"
    :style="{ maxWidth: '440px', width: '90vw' }"
    :bordered="true"
    @update:show="$emit('update:show', $event)"
  >
    <div v-if="loading" style="text-align:center;padding:20px"><n-spin size="medium" /></div>
    <div v-else-if="templates.length === 0" style="text-align:center;padding:20px;color:var(--app-text-muted)">
      暂无模板，请先保存一个工作流为模板
    </div>
    <div v-else class="template-list">
      <div
        v-for="t in templates"
        :key="t.name"
        class="template-item"
        @click="select(t.name)"
      >
        <div class="template-left">
          <n-tag size="tiny" round :type="t.builtin ? 'info' : 'default'">
            {{ t.node_count }} 节点
          </n-tag>
          <span class="template-name">{{ t.name }}</span>
        </div>
        <n-button
          size="tiny"
          quaternary
          type="error"
          class="template-delete"
          @click.stop="confirmDelete(t)"
        >
          🗑️
        </n-button>
      </div>
    </div>
    <template #footer>
      <n-button size="small" @click="$emit('update:show', false)">取消</n-button>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { dagApi } from '@/api/dag'
import { useMessage } from 'naive-ui'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{
  'update:show': [boolean]
  confirm: [name: string]
}>()

const message = useMessage()
const loading = ref(false)
const templates = ref<Array<{ name: string; description: string; node_count: number; builtin?: boolean }>>([])

watch(() => props.show, async (s) => {
  if (!s) { templates.value = []; return }
  loading.value = true
  templates.value = []
  try {
    const res: any = await dagApi.listTemplates()
    templates.value = res?.templates || []
  } catch (e) {
    console.error('[TemplateLoadDialog] 加载失败:', e)
    templates.value = []
  } finally {
    loading.value = false
  }
})

function select(name: string) {
  emit('confirm', name)
  emit('update:show', false)
}

async function confirmDelete(t: { name: string; builtin?: boolean }) {
  if (t.builtin) { message.warning('内置模板不可删除'); return }
  try {
    // 模板可能有多个版本，逐个删
    const res: any = await dagApi.listTemplates()
    const tmpls = res?.templates || []
    const versions = tmpls.filter((x: any) => x.name === t.name).map((x: any) => x.version)
    for (const v of versions) {
      await dagApi.deleteVersion(`@tmpl:${t.name}`, v).catch(() => {})
    }
    message.success(`已删除模板「${t.name}」`)
    const res2: any = await dagApi.listTemplates()
    templates.value = res2?.templates || []
  } catch { message.error('删除失败') }
}
</script>

<style scoped>
.template-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.template-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: background .15s;
}

.template-item:hover {
  background: var(--app-hover-bg, rgba(0,0,0,.04));
}

.template-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.template-name {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.template-delete {
  opacity: 0;
  transition: opacity .15s;
  flex-shrink: 0;
}

.template-item:hover .template-delete {
  opacity: 1;
}
</style>
