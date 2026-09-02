import { get, post, del } from './index'

// ── 风控统计 & 状态 ──────────────────────────────────────────

export function getRiskStats() {
  return get('/v1/risk/stats')
}

export function getRiskStatus() {
  return get('/v1/risk/status')
}

export function resumeSending() {
  return post('/v1/risk/resume')
}

// ── 黑名单管理 ──────────────────────────────────────────────

export function getBlacklist(params?: {
  page?: number
  page_size?: number
}) {
  return get('/v1/risk/blacklist', params)
}

export function addBlacklist(data: {
  user_uid: string
  reason?: string
}) {
  return post('/v1/risk/blacklist', data)
}

export function removeBlacklist(userUid: string) {
  return del(`/v1/risk/blacklist/${userUid}`)
}

// ── 事件记录(webhook) ───────────────────────────────────────

export function reportEvent(data: {
  event_type: string
  user_uid?: string
  count?: number
}) {
  return post('/v1/risk/report-event', data)
}
