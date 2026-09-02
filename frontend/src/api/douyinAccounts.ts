import { get, post, put, del } from './index'
import type { ApiResponse } from './auth'

export interface DouyinAccountInfo {
  id: number
  douyin_uid: string
  nickname: string
  login_status: string
  assigned_to_user_id: number | null
  assigned_to_username: string | null
  last_active_at: string | null
  created_at: string | null
}

export function getAccounts() {
  return get<ApiResponse<DouyinAccountInfo[]>>('/v1/douyin-accounts')
}

export function addAccount(data: { douyin_uid: string; nickname: string; cookie_data: string; proxy_url?: string; nurture_enabled?: boolean }) {
  return post<ApiResponse>('/v1/douyin-accounts', data)
}

export function assignAccount(id: number, userId: number) {
  return put<ApiResponse>(`/v1/douyin-accounts/${id}/assign`, { user_id: userId })
}

export function unassignAccount(id: number) {
  return put<ApiResponse>(`/v1/douyin-accounts/${id}/unassign`)
}

export function updateCookie(id: number, cookieData: string) {
  return put<ApiResponse>(`/v1/douyin-accounts/${id}/cookie`, { cookie_data: cookieData })
}

export function checkAccountStatus(id: number) {
  return get<ApiResponse>(`/v1/douyin-accounts/${id}/status`)
}

export function deleteAccount(id: number) {
  return del<ApiResponse>(`/v1/douyin-accounts/${id}`)
}

export interface QrLoginStartInfo {
  login_session_id: string
  qr_image_base64: string
  expires_in: number
}

export interface QrLoginStatusInfo {
  status: 'pending' | 'confirmed' | 'expired' | 'need_verification'
  cookie_data: string | null
  qr_image_base64: string | null
  verify_message?: string | null
  verify_image_base64?: string | null
}

export function startQrLogin() {
  // 真实Playwright模式下需要启动浏览器并打开抖音首页等二维码渲染出来，
  // 浏览器冷启动时更慢，这里放宽到90秒，避免刚够不着后端最长等待时间。
  return post<ApiResponse<QrLoginStartInfo>>(
    '/v1/douyin-accounts/qr-login/start', undefined, { timeout: 90000 }
  )
}

export function pollQrLogin(loginSessionId: string) {
  return get<ApiResponse<QrLoginStatusInfo>>(
    `/v1/douyin-accounts/qr-login/${loginSessionId}/status`, undefined, { timeout: 20000 }
  )
}

export function submitQrVerification(loginSessionId: string, code: string) {
  return post<ApiResponse<QrLoginStatusInfo>>(
    `/v1/douyin-accounts/qr-login/${loginSessionId}/verify`, { code }, { timeout: 30000 }
  )
}
