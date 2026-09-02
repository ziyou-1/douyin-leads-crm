import { get, put } from './index'

// ── 配额 ──────────────────────────────────────────────────────

export function getQuotas() {
  return get('/v1/system/quotas')
}

// ── 告警 ──────────────────────────────────────────────────────

export function getAlerts(params?: {
  page?: number
  page_size?: number
  level?: string
  unread_only?: boolean
}) {
  return get('/v1/system/alerts', params)
}

export function markAlertRead(alertId: number) {
  return put(`/v1/system/alerts/${alertId}/read`)
}

export function markAllAlertsRead() {
  return put('/v1/system/alerts/read-all')
}

export function getUnreadAlertCount() {
  return get('/v1/system/alerts/unread-count')
}

// ── API调用日志 ──────────────────────────────────────────────

export function getApiLogs(params?: {
  page?: number
  page_size?: number
  api_type?: string
  success?: boolean
  date?: string
}) {
  return get('/v1/system/api-logs', params)
}

// ── 系统配置 ──────────────────────────────────────────

export function getSystemConfigs(params?: { category?: string }) {
  return get('/v1/system/configs', params)
}

export function updateSystemConfig(key: string, value: string) {
  return put(`/v1/system/configs/${key}`, { value })
}

export function batchUpdateSystemConfigs(configs: { key: string; value: string }[]) {
  return put('/v1/system/configs/batch', { configs })
}

export function getConfigChangeLogs(params?: {
  page?: number
  page_size?: number
  key?: string
}) {
  return get('/v1/system/config-logs', params)
}
