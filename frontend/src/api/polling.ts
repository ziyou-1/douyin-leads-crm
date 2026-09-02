import { get, put } from './index'

export function getPollingConfig() {
  return get('/v1/polling/config')
}

export function updatePollingConfig(data: Record<string, unknown>) {
  return put('/v1/polling/config', data)
}

export function getPollingCallCounts() {
  return get('/v1/polling/call-counts')
}
