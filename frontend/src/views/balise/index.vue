<template>
  <section class="page" data-module="balise">
    <header class="page-head">
      <div>
        <h2>应答器管理</h2>
        <p class="page-desc">维护应答器，围绕应答器编号、所在位置、报文版本、激活距离做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记应答器</button>
        <button class="btn" type="button" @click="exportRows">导出应答器清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <button v-if="column === '报文版本'" class="link" type="button" @click="openDetail(row)">
              {{ row[column] ?? '—' }}
            </button>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">详情</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :disabled="isReplaced(row)"
              :title="isReplaced(row) ? '已更换的应答器不再参与固定状态变更' : ''"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无应答器数据，可先登记应答器</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条应答器记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="successMessage" class="success-text">{{ successMessage }}</span>
    </footer>

    <div v-if="detailVisible" class="dialog-mask" @click.self="closeDetail">
      <div class="dialog" role="dialog" aria-modal="true" aria-label="应答器详情">
        <div class="dialog-head">
          <h3>应答器详情 · {{ form.应答器编号 }}</h3>
          <button class="btn ghost" type="button" @click="closeDetail">关闭</button>
        </div>
        <dl class="detail-grid">
          <template v-for="field in readonlyFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ form[field] ?? '—' }}</dd>
          </template>
          <dt>应答器状态</dt>
          <dd>{{ form.status ?? '—' }}</dd>
        </dl>
        <form class="edit-form" @submit.prevent="saveDetail">
          <label class="filter-item">
            <span>报文版本</span>
            <input v-model="form.报文版本" placeholder="请输入报文版本" />
          </label>
          <label class="filter-item">
            <span>激活距离（米）</span>
            <input v-model="form.激活距离" placeholder="允许范围 0.5~10 米" inputmode="decimal" />
          </label>
          <p v-if="detailError" class="error-text">{{ detailError }}</p>
          <div class="dialog-actions">
            <button class="btn" type="button" @click="closeDetail">取消</button>
            <button class="btn primary" type="submit" :disabled="saving">
              {{ saving ? '保存中…' : '保存' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/balise'
const columns = ["应答器编号", "所在位置", "报文版本", "激活距离", "接收电平", "安装方式", "固定状态", "应答器状态"]
const actions = ["登记异常", "重新固定", "办理更换"]
const filterFields = ["应答器编号", "所在位置", "报文版本"]
const readonlyFields = ["应答器编号", "所在位置", "接收电平", "安装方式", "固定状态"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const filters = ref<Record<string, string>>({})

const stats = computed(() => [
  { label: "正常应答器", value: rows.value.filter((row) => row.status === '正常').length },
  { label: "异常应答器", value: rows.value.filter((row) => row.status === '报文异常').length },
  { label: "偏移应答器", value: rows.value.filter((row) => row.status === '松动偏移').length },
])

const detailVisible = ref(false)
const saving = ref(false)
const detailError = ref('')
const form = reactive<Row>({})

function isReplaced(row: Row) {
  return row.status === '已更换'
}

function flashError(message: string) {
  successMessage.value = ''
  errorMessage.value = message
}

function flashSuccess(message: string) {
  errorMessage.value = ''
  successMessage.value = message
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  flashError('应答器登记入口尚未接入审批流')
}

function openDetail(row: Row) {
  detailError.value = ''
  Object.keys(form).forEach((key) => delete form[key])
  Object.assign(form, row)
  detailVisible.value = true
}

function closeDetail() {
  if (saving.value) return
  detailVisible.value = false
  detailError.value = ''
}

async function saveDetail() {
  detailError.value = ''
  saving.value = true
  try {
    const response = await request(`${ENDPOINT}/${form.id}`, {
      method: 'PUT',
      body: JSON.stringify({
        values: {
          version: form.version,
          报文版本: form.报文版本,
          激活距离: form.激活距离,
        },
      }),
    })
    const payload = await response.json().catch(() => null) as { ok?: boolean; message?: string } | null
    if (response.status === 409) {
      // 并发冲突：不保留本地输入覆盖服务端，刷新列表让原值（对方已保存的值）可见
      detailVisible.value = false
      await reload()
      flashError(payload?.message ?? '该应答器已被他人修改，请刷新后重新打开详情再保存')
      return
    }
    if (!response.ok || !payload?.ok) {
      detailError.value = payload?.message ?? '报文版本保存失败，原有数据未改动'
      return
    }
    detailVisible.value = false
    await reload()
    flashSuccess(payload.message ?? '报文版本已保存')
  } catch (error) {
    detailError.value = error instanceof Error ? error.message : '报文版本保存失败，原有数据未改动'
  } finally {
    saving.value = false
  }
}

async function runAction(action: string, row: Row) {
  flashError('')
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null) as { ok?: boolean; message?: string } | null
    if (!response.ok || !payload?.ok) {
      flashError(payload?.message ?? '应答器动作未生效，请稍后重试')
      return
    }
    await reload()
    flashSuccess(payload.message ?? '操作已生效')
  } catch (error) {
    flashError(error instanceof Error ? error.message : '应答器操作失败')
  }
}

async function reload() {
  errorMessage.value = ''
  successMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('应答器列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    flashError(error instanceof Error ? error.message : '应答器列表读取失败')
  }
}

onMounted(reload)
</script>

<style scoped>
.success-text { color: #067647; }
.dialog-mask {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.dialog {
  background: #fff;
  border-radius: 10px;
  width: 560px;
  max-width: calc(100vw - 32px);
  padding: 16px 20px;
  box-shadow: 0 12px 32px rgba(16, 24, 40, 0.2);
}
.dialog-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.dialog-head h3 { margin: 0; font-size: 15px; }
.detail-grid {
  display: grid;
  grid-template-columns: 110px 1fr 110px 1fr;
  gap: 6px 10px;
  margin: 0 0 12px;
  font-size: 13px;
}
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
.edit-form {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-end;
  border-top: 1px solid var(--border);
  padding-top: 12px;
}
.dialog-actions { margin-left: auto; display: flex; gap: 8px; }
.link:disabled { color: var(--muted); cursor: not-allowed; text-decoration: none; }
</style>
