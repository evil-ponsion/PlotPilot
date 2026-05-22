<template>
  <div class="workbench">
    <StatsTopBar :slug="slug" @open-settings="appSettingsShell.open()" />

    <div class="workbench-main">
      <n-split
        direction="horizontal"
        :min="WORKBENCH_SPLIT.sidebarMin"
        :max="WORKBENCH_SPLIT.sidebarMax"
        :default-size="WORKBENCH_SPLIT.sidebarDefault"
      >
        <template #1>
          <ChapterList
            ref="chapterListRef"
            :slug="slug"
            :chapters="chapters"
            :current-chapter-id="currentChapterId"
            :generation-prefs="generationPrefs"
            @select="onSidebarChapterSelect"
            @back="goHome"
            @refresh="handleChapterUpdated"
            @plan-act="handlePlanAct"
          />
        </template>

        <template #2>
          <n-split
            direction="horizontal"
            :min="WORKBENCH_SPLIT.mainMin"
            :max="WORKBENCH_SPLIT.mainMax"
            :default-size="WORKBENCH_SPLIT.mainDefault"
          >
            <template #1>
              <div class="main-column">
                <WorkbenchToolbar
                  :is-running="dagRunStatus === 'running'"
                  @run="handleRunDAG"
                  @save="handleSaveChapter"
                />
                <WorkArea
                  ref="workAreaRef"
                  :slug="slug"
                  :book-title="bookTitle"
                  :chapters="chapters"
                  :current-chapter-id="currentChapterId"
                  :chapter-content="chapterContent"
                  :chapter-loading="chapterLoading"
                  :generation-prefs="generationPrefs"
                  @chapter-updated="handleChapterUpdated"
                />
                <div class="dag-resize-handle" @mousedown="startDAGResize" />
                <div class="dag-bottom" :style="{ height: dagHeight + 'px' }">
                  <div class="dag-bottom-head">
                    <n-select
                      v-model:value="activeWorkflow"
                      :options="workflowOptions"
                      size="tiny"
                      style="width: 220px"
                      @update:value="switchWorkflow"
                    />
                    <n-button size="tiny" secondary type="error" @click="deleteWorkflow">🗑️</n-button>
                  </div>
                  <div class="dag-bottom-body">
                    <AutopilotDAGView :novel-id="novelId" @dag-changed="loadWorkflowOptions" />
                  </div>
                </div>
              </div>
            </template>

            <template #2>
              <SettingsPanel
                :slug="slug"
                :current-panel="rightPanel"
                :current-chapter="currentChapter"
                :generation-prefs="generationPrefs"
                @update:current-panel="onSettingsPanelChange"
              />
            </template>
          </n-split>
        </template>
      </n-split>
    </div>

    <ActPlanningModal
      v-model:show="showActPlanning"
      :act-id="actPlanningId"
      :act-title="actPlanningTitle"
      @confirmed="handleChapterUpdated"
    />

  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, computed, ref, watch, type ComponentPublicInstance } from 'vue'
import { useRoute } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useWorkbench } from '../composables/useWorkbench'
import { useStatsStore } from '../stores/statsStore'
import { useWorkbenchRefreshStore } from '../stores/workbenchRefreshStore'
import { useAppSettingsShellStore } from '../stores/appSettingsShellStore'
import StatsTopBar from '../components/stats/StatsTopBar.vue'
import WorkbenchToolbar from '../components/workbench/WorkbenchToolbar.vue'
import ChapterList from '../components/workbench/ChapterList.vue'
import WorkArea from '../components/workbench/WorkArea.vue'
import SettingsPanel from '../components/workbench/SettingsPanel.vue'
import ActPlanningModal from '../components/workbench/ActPlanningModal.vue'
import AutopilotDAGView from '../components/autopilot/AutopilotDAGView.vue'
import { useDAGRunStore } from '../stores/dagRunStore'
import { useDAGStore } from '../stores/dagStore'
import { dagApi } from '../api/dag'

import {
  WORKBENCH_CHAPTER_DESK_CHANGE_EVENT,
  WORKBENCH_OPEN_SETTINGS_PANEL_EVENT,
  WORKBENCH_GENERATION_PREFS_UPDATED_EVENT,
  isWorkbenchSettingsPanelName,
} from '../workbench/deskEvents'
import { WORKBENCH_SPLIT } from '../design/layoutDensity'

const route = useRoute()
const message = useMessage()
const statsStore = useStatsStore()
const workbenchRefresh = useWorkbenchRefreshStore()
const appSettingsShell = useAppSettingsShellStore()
const dagRun = useDAGRunStore()
const dagStore = useDAGStore()
const dagRunStatus = computed(() => dagRun.runStatus)
const novelId = computed(() => slug.value)

const showDAG = ref(true)
const dagHeight = ref(300)
let dagResizeStart = 0
let dagResizeStartHeight = 0




function startDAGResize(e: MouseEvent) {
  dagResizeStart = e.clientY
  dagResizeStartHeight = dagHeight.value
  document.addEventListener('mousemove', onDAGResize)
  document.addEventListener('mouseup', stopDAGResize)
}

function onDAGResize(e: MouseEvent) {
  const delta = dagResizeStart - e.clientY
  dagHeight.value = Math.max(120, Math.min(window.innerHeight * 0.6, dagResizeStartHeight + delta))
}

function stopDAGResize() {
  document.removeEventListener('mousemove', onDAGResize)
  document.removeEventListener('mouseup', stopDAGResize)
}

function handleRunDAG() {
  if (dagRunStatus.value === 'running') {
    dagRun.stopRun(novelId.value)
  } else {
    dagRun.startRun(novelId.value)
  }
}

async function handleSaveChapter() {
  message.success('章节已保存')
}

// ─── 工作流下拉框 ───
const activeWorkflow = ref('')
const workflowOptions = ref<Array<{ label: string; value: string }>>([])

async function loadWorkflowOptions() {
  try {
    const verRes: any = await dagApi.listVersions(novelId.value)
    const versions: any[] = verRes?.versions || []
    workflowOptions.value = versions.map((v: any) => ({
      label: `${v.name} (${v.node_count}节点)`,
      value: String(v.version),
    }))

    // 自动选择：优先当前 dagStore 版本，否则第一个
    const cur = dagStore.dagDefinition?.version
    const match = workflowOptions.value.find(o => o.value === String(cur ?? ''))
    if (match) {
      activeWorkflow.value = match.value
    } else if (workflowOptions.value.length > 0) {
      activeWorkflow.value = workflowOptions.value[0].value
    }
  } catch { /* 静默 */ }
}

async function switchWorkflow(value: string) {
  const version = parseInt(value)
  if (isNaN(version)) return
  try {
    const dag = await dagApi.getDAGVersion(novelId.value, version)
    if (dag) dagStore.dagDefinition = dag
  } catch { /* 静默 */ }
}

async function deleteWorkflow() {
  const v = parseInt(activeWorkflow.value)
  if (isNaN(v) || v <= 0) { message.warning('内置工作流不可删除'); return }
  try {
    await dagApi.deleteVersion(novelId.value, v)
    await dagStore.loadDAG(novelId.value)
    loadWorkflowOptions()
    message.success('已删除')
  } catch { message.error('删除失败') }
}

const slug = computed(() => String(route.params.slug ?? ''))

const chapterListRef = ref<ComponentPublicInstance<{ refreshStoryTree: () => void }> | null>(null)
const workAreaRef = ref<ComponentPublicInstance<{ ensureAssistedMode: () => void }> | null>(null)

async function onSidebarChapterSelect(chapterId: number, title = '') {
  await handleChapterSelect(chapterId, title)
  workAreaRef.value?.ensureAssistedMode?.()
}

/** 合并短时间内的多次「整桌刷新」：全托管状态抖动 / 多源 emit 时只拉一次 API，减轻闪烁与日志刷屏 */
let chapterDeskReloadTimer: ReturnType<typeof setTimeout> | null = null
const CHAPTER_DESK_RELOAD_DEBOUNCE_MS = 1100

async function runChapterDeskReload() {
  await loadDesk()
  void statsStore.loadBookStats(slug.value, true).catch(() => {})
  window.dispatchEvent(new CustomEvent('plotpilot:bible-panel:soft-reload'))
  chapterListRef.value?.refreshStoryTree?.()
  workbenchRefresh.bumpAfterChapterDeskChange()
}

const handleChapterUpdated = () => {
  if (chapterDeskReloadTimer) clearTimeout(chapterDeskReloadTimer)
  chapterDeskReloadTimer = setTimeout(() => {
    chapterDeskReloadTimer = null
    void runChapterDeskReload()
  }, CHAPTER_DESK_RELOAD_DEBOUNCE_MS)
}

function onDeskChangeSignalFromPanels() {
  handleChapterUpdated()
}

function onOpenSettingsPanelFromChild(e: Event) {
  const panel = (e as CustomEvent<{ panel?: string }>).detail?.panel
  if (typeof panel === 'string' && isWorkbenchSettingsPanelName(panel)) {
    rightPanel.value = panel
  }
}

// 幕→章 规划弹层
const showActPlanning = ref(false)
const actPlanningId = ref('')
const actPlanningTitle = ref('')

const handlePlanAct = (actId: string, actTitle: string) => {
  actPlanningId.value = actId
  actPlanningTitle.value = actTitle
  showActPlanning.value = true
}

const {
  bookTitle,
  chapters,
  generationPrefs,
  rightPanel,
  pageLoading,
  bookMeta,
  currentJobId,
  currentChapterId,
  chapterContent,
  chapterLoading,
  setRightPanel,
  loadDesk,
  reloadDeskForSlugChange,
  goHome,
  goToChapter,
  handleChapterSelect,
} = useWorkbench({ slug })

const currentChapter = computed(() => {
  if (!currentChapterId.value) return null
  return chapters.value.find(ch => ch.id === currentChapterId.value) || null
})

function onSettingsPanelChange(panel: string) {
  rightPanel.value = panel
}

function parseChapterQuery(q: unknown): number | null {
  if (q == null || q === '') return null
  const raw = Array.isArray(q) ? q[0] : q
  const n = Number(raw)
  return !Number.isNaN(n) && n >= 1 ? n : null
}

async function syncChapterFromRoute() {
  const n = parseChapterQuery(route.query.chapter)
  if (n != null) {
    await goToChapter(n)
  }
}

function onGenerationPrefsUpdated() {
  void loadDesk()
  chapterListRef.value?.refreshStoryTree?.()
}

onMounted(async () => {
  window.addEventListener(WORKBENCH_CHAPTER_DESK_CHANGE_EVENT, onDeskChangeSignalFromPanels)
  window.addEventListener(WORKBENCH_OPEN_SETTINGS_PANEL_EVENT, onOpenSettingsPanelFromChild)
  window.addEventListener(WORKBENCH_GENERATION_PREFS_UPDATED_EVENT, onGenerationPrefsUpdated)
  try {
    await loadDesk()
    await syncChapterFromRoute()
    dagStore.loadDAG(slug.value).catch(() => {})
    loadWorkflowOptions()
  } catch {
    message.error('加载失败，请检查网络与后端是否已启动')
    bookTitle.value = slug.value
  } finally {
    pageLoading.value = false
  }
})

onUnmounted(() => {
  window.removeEventListener(WORKBENCH_CHAPTER_DESK_CHANGE_EVENT, onDeskChangeSignalFromPanels)
  window.removeEventListener(WORKBENCH_OPEN_SETTINGS_PANEL_EVENT, onOpenSettingsPanelFromChild)
  window.removeEventListener(WORKBENCH_GENERATION_PREFS_UPDATED_EVENT, onGenerationPrefsUpdated)
  if (chapterDeskReloadTimer) {
    clearTimeout(chapterDeskReloadTimer)
    chapterDeskReloadTimer = null
  }
})

watch(
  () => route.query.chapter,
  () => {
    void syncChapterFromRoute()
  }
)

watch(() => dagStore.dagDefinition?.version, () => {
  loadWorkflowOptions()
})

watch(
  slug,
  async (next, prev) => {
    if (!next || prev === next) return
    try {
      await reloadDeskForSlugChange()
      await syncChapterFromRoute()
      void statsStore.loadBookStats(next, true).catch(() => {})
      chapterListRef.value?.refreshStoryTree?.()
      workbenchRefresh.bumpAfterChapterDeskChange()
      dagStore.loadDAG(next).catch(() => {})
      loadWorkflowOptions()
    } catch {
      message.error('切换作品失败，请检查网络与后端是否已启动')
      bookTitle.value = next
    }
  }
)
</script>

<style scoped>
.workbench {
  height: 100vh;
  overflow: hidden;
  background: var(--app-page-bg, #f0f2f8);
  display: flex;
  flex-direction: column;
}

.workbench-main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.workbench-main :deep(.n-split) {
  height: 100%;
}

.workbench-main :deep(.n-split-pane-1),
.workbench-main :deep(.n-split-pane-2) {
  min-height: 0;
  overflow: hidden;
}

.main-column {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.main-column > :nth-child(2) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.dag-resize-handle {
  height: 2px;
  cursor: row-resize;
  background: var(--app-border);
  flex-shrink: 0;
  transition: background .15s;
}
.dag-resize-handle:hover {
  background: var(--color-brand);
}

.dag-bottom {
  min-height: 120px;
  border-top: 2px solid var(--app-border);
  overflow: hidden;
  background: var(--dag-canvas-bg);
  display: flex;
  flex-direction: column;
}

.dag-bottom-head {
  display: flex;
  align-items: center;
  padding: 4px 8px;
  border-bottom: 1px solid var(--app-divider-light);
  background: var(--dag-toolbar-bg);
  flex-shrink: 0;
}

.dag-bottom-body {
  flex: 1;
  min-height: 0;
  position: relative;
}

.dag-bottom-body > :deep(.dag-view-container) {
  position: absolute;
  inset: 0;
}

</style>
