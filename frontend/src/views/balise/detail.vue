<template>
  <section class="page" data-module="balise-detail">
    <header class="page-head">
      <div>
        <h2>应答器详情</h2>
        <p class="page-desc">核对应答器台账并维护报文版本；激活距离超出允许范围时不允许保存。</p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/balise">返回列表</RouterLink>
      </div>
    </header>

    <div v-if="loadError" class="detail-error">
      <span>{{ loadError }}</span>
      <button class="btn" type="button" @click="load">重新加载</button>
    </div>

    <template v-else-if="entry">
      <article class="detail-card">
        <h3 class="detail-title">基础信息</h3>
        <dl class="detail-grid">
          <div v-for="field in readonlyFields" :key="field" class="detail-item">
            <dt>{{ field }}</dt>
            <dd>{{ displayValue(field) }}</dd>
          </div>
          <div class="detail-item">
            <dt>数据版本</dt>
            <dd>第 {{ entry.version ?? 1 }} 版</dd>
          </div>
        </dl>
      </article>

      <article class="detail-card">
        <h3 class="detail-title">报文版本维护</h3>
        <p v-if="isReplaced" class="error-text">该应答器已办理更换，报文版本与固定状态均不再允许变更。</p>
        <form v-else class="edit-form" @submit.prevent="save">
          <label class="filter-item">
            <span>报文版本</span>
            <input v-model="form.报文版本" placeholder="如 MSG-V1.3" />
          </label>
          <label class="filter-item">
            <span>激活距离（毫米，允许 200～1000）</span>
            <input v-model="form.激活距离" inputmode="numeric" placeholder="200～1000" />
          </label>
          <div class="form-actions">
            <button class="btn primary" type="submit" :disabled="saving">
              {{ saving ? '保存中…' : '保存报文版本' }}
            </button>
            <button class="btn ghost" type="button" @click="resetForm">重置为当前值</button>
          </div>
        </form>
        <p v-if="message" :class="conflict ? 'warn-text' : saveOk ? 'ok-text' : 'error-text'">
          {{ message }}
        </p>
        <div v-if="conflict && latest" class="conflict-panel">
          <span>服务端最新值（你的输入已保留，可对照后刷新再提交）：</span>
          <span>报文版本：{{ latest['报文版本'] }}　激活距离：{{ latest['激活距离'] }} 毫米（第 {{ latest.version ?? 1 }} 版）</span>
          <button class="btn" type="button" @click="adoptLatest">按最新值重新编辑</button>
        </div>
      </article>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import { request } from '@/api/client'

type BaliseEntry = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/balise'
const readonlyFields = [
  '应答器编号',
  '所在位置',
  '接收电平',
  '安装方式',
  '固定状态',
  '应答器状态',
]

const route = useRoute()
const entryId = Number(route.params.id)

const entry = ref<BaliseEntry | null>(null)
const loadError = ref('')
const form = reactive<{ 报文版本: string; 激活距离: string }>({
  报文版本: '',
  激活距离: '',
})
const saving = ref(false)
const saveOk = ref(false)
const conflict = ref(false)
const latest = ref<BaliseEntry | null>(null)
const message = ref('')

const isReplaced = computed(() => entry.value?.['应答器状态'] === '已更换')

function displayValue(field: string): string | number {
  const value = entry.value?.[field]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function fillForm(source: BaliseEntry) {
  form.报文版本 = String(source['报文版本'] ?? '')
  form.激活距离 = String(source['激活距离'] ?? '')
}

async function load() {
  loadError.value = ''
  try {
    const response = await request(`${ENDPOINT}/${entryId}`)
    if (response.status === 404) {
      loadError.value = `应答器 ${entryId} 不存在或已归档`
      return
    }
    if (!response.ok) {
      throw new Error(`接口返回 ${response.status}`)
    }
    entry.value = (await response.json()) as BaliseEntry
    fillForm(entry.value)
    // 重新加载意味着以最新数据为基准，清掉上一轮的冲突提示。
    conflict.value = false
    latest.value = null
    message.value = ''
    saveOk.value = false
  } catch (error) {
    loadError.value = error instanceof Error ? error.message : '应答器详情读取失败'
  }
}

function resetForm() {
  if (entry.value) {
    fillForm(entry.value)
  }
  message.value = ''
  conflict.value = false
}

function adoptLatest() {
  if (latest.value) {
    entry.value = { ...latest.value }
    fillForm(latest.value)
    conflict.value = false
    latest.value = null
    message.value = ''
  }
}

async function save() {
  saving.value = true
  message.value = ''
  conflict.value = false
  latest.value = null
  saveOk.value = false
  try {
    const response = await request(`${ENDPOINT}/${entryId}`, {
      method: 'PUT',
      body: JSON.stringify({
        values: {
          报文版本: form.报文版本,
          激活距离: form.激活距离,
          // 带上打开详情时的版本号：别人先改过，这个号就对不上，保存会被拒绝。
          version: entry.value?.version ?? 1,
        },
      }),
    })
    const payload = (await response.json().catch(() => null)) as
      | { ok?: boolean; message?: string; entry?: BaliseEntry; latest?: BaliseEntry }
      | null
    if (response.status === 409) {
      // 并发冲突：服务端未覆盖任何数据；表单保留用户输入，同时展示最新值。
      conflict.value = true
      latest.value = payload?.latest ?? null
      message.value = payload?.message ?? '该应答器已被他人修改，请刷新后重试'
      if (payload?.latest) {
        entry.value = { ...payload.latest }
      }
      return
    }
    if (!response.ok || !payload?.ok) {
      // 校验失败（激活距离超范围等）：表单原样保留，后端数据也未改动。
      message.value = payload?.message ?? '报文版本保存失败，请检查填写内容'
      return
    }
    if (payload.entry) {
      entry.value = payload.entry
      fillForm(payload.entry)
    }
    saveOk.value = true
    message.value = payload.message || '报文版本保存成功'
  } catch (error) {
    message.value = error instanceof Error ? error.message : '报文版本保存失败，请稍后重试'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.detail-card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.detail-title {
  margin: 0 0 12px;
  font-size: 15px;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px 18px;
  margin: 0;
}
.detail-item dt {
  font-size: 12px;
  color: var(--muted);
}
.detail-item dd {
  margin: 2px 0 0;
  font-size: 13px;
}
.edit-form {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
}
.edit-form .filter-item {
  min-width: 220px;
}
.edit-form input {
  width: 100%;
  margin-top: 2px;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.form-actions {
  display: flex;
  gap: 8px;
}
.detail-error {
  display: flex;
  gap: 10px;
  align-items: center;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  color: #b42318;
}
.ok-text {
  color: #067647;
}
.warn-text {
  color: #b54708;
}
.conflict-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid #fedf89;
  background: #fffaeb;
  border-radius: 6px;
  font-size: 13px;
  color: #b54708;
}
.conflict-panel .btn {
  align-self: flex-start;
}
</style>
