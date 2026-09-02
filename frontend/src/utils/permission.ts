import { useUserStore } from '@/stores/user'
import { ROLES } from '@/constants/roles'

export function hasRole(role: string): boolean {
  const userStore = useUserStore()
  return userStore.role === role
}

export function hasAnyRole(roles: string[]): boolean {
  const userStore = useUserStore()
  return roles.includes(userStore.role)
}

export function isAdmin(): boolean {
  return hasRole(ROLES.ADMIN)
}

export function isCustomerServiceAdmin(): boolean {
  return hasRole(ROLES.CUSTOMER_SERVICE_ADMIN)
}
