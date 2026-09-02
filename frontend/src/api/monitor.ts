import { get, post, put, del } from './index'
import service from './index'

export interface MonitorItem {
  id: number
  douyin_url: string
  douyin_uid: string
  nickname: string
  avatar: string
  status: string
  poll_interval_min: number
  ai_freshness_min: number
  high_intent_min: number
  created_by: number | null
  created_at: string
  source: string
  last_high_intent_at: string | null
  total_high_count: number
}

export interface MonitorAccountStats {
  monitor: {
    id: number
    nickname: string
    douyin_uid: string
  }
  days: number
  start_time: string
  end_time: string
  high_lead_count: number
  outbound_message_count: number
  communicated_lead_count: number
  sales_stats: {
    user_id: number
    username: string
    assigned_leads: number
    communicated_leads: number
    outbound_messages: number
  }[]
  leads: {
    lead_id: number
    user_nickname: string
    user_uid: string
    comment_content: string
    comment_time: string | null
    video_title: string
    ai_reason: string
    sales_name: string | null
    outbound_messages: number
  }[]
}

export function getMonitors(params?: any) {
  return get('/v1/monitors', params)
}

export function createMonitor(data: any) {
  return post('/v1/monitors', data)
}

export function batchImport(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  return service.post('/v1/monitors/batch-import', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function updateMonitor(id: number, data: any) {
  return put(`/v1/monitors/${id}`, data)
}

export function deleteMonitor(id: number) {
  return del(`/v1/monitors/${id}`)
}

export function batchDeleteMonitors(ids: number[]) {
  return post('/v1/monitors/batch-delete', { ids })
}

export function batchUpdateMonitorStatus(ids: number[], status: 'active' | 'paused') {
  return post('/v1/monitors/batch-status', { ids, status })
}

export function batchUpdateMonitorPollInterval(
  ids: number[],
  data: { poll_interval_min: number; ai_freshness_min: number; high_intent_min: number },
) {
  return post('/v1/monitors/batch-poll-interval', {
    ids,
    ...data,
  })
}

export function toggleMonitor(id: number) {
  return post(`/v1/monitors/${id}/toggle`)
}

export function runDiscovery() {
  return post('/v1/monitors/run-discovery')
}

export function runCleaning() {
  return post('/v1/monitors/run-cleaning')
}

export function getDiscoveryStats() {
  return get('/v1/monitors/discovery-stats')
}

export function getRemovedMonitors(params?: any) {
  return get('/v1/monitors/removed', params)
}

export function restoreMonitor(id: number) {
  return post(`/v1/monitors/${id}/restore`)
}

export function getMonitorAccountStats(id: number, days: number) {
  return get<{ code: number; data: MonitorAccountStats }>(`/v1/monitors/${id}/stats`, { days })
}

export function exportMonitorAccountStats(id: number, days: number) {
  return get<Blob>(`/v1/monitors/${id}/stats/export`, { days }, { responseType: 'blob' })
}
