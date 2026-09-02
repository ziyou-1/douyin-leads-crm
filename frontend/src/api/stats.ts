import { get } from './index'

export function getDashboard() {
  return get('/v1/stats/dashboard')
}

export function getSalesPerformance(params?: { start_date?: string; end_date?: string }) {
  return get('/v1/stats/sales-performance', params)
}

export function getMonitorStats(params?: { start_date?: string; end_date?: string }) {
  return get('/v1/stats/monitor-stats', params)
}

export function getTrend(days = 7) {
  return get('/v1/stats/trend', { days })
}

export function exportLeads(params?: {
  status?: string
  assigned_to?: number
  start_date?: string
  end_date?: string
}) {
  return get<Blob>('/v1/stats/export', params, { responseType: 'blob' })
}
