export const ROLES = {
  ADMIN: 'admin',
  CUSTOMER_SERVICE_ADMIN: 'customer_service_admin',
  CUSTOMER_SERVICE: 'customer_service',
} as const

export const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  customer_service_admin: '客服管理员',
  customer_service: '客服',
}

export const ROLE_TAG_TYPES: Record<string, '' | 'success' | 'warning' | 'info' | 'danger'> = {
  admin: 'danger',
  customer_service_admin: 'warning',
  customer_service: 'info',
}

export function getRoleLabel(role: string): string {
  return ROLE_LABELS[role] || role
}

export function getDefaultRoute(role: string): string {
  if (role === ROLES.CUSTOMER_SERVICE_ADMIN) return '/monitor'
  return '/dashboard'
}

export function isAdminRole(role: string): boolean {
  return role === ROLES.ADMIN
}

export function isCustomerServiceAdminRole(role: string): boolean {
  return role === ROLES.CUSTOMER_SERVICE_ADMIN
}

export function canManageUsers(role: string): boolean {
  return role === ROLES.ADMIN || role === ROLES.CUSTOMER_SERVICE_ADMIN
}
