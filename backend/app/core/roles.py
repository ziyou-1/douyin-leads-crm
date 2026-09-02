ROLE_ADMIN = "admin"
ROLE_CUSTOMER_SERVICE_ADMIN = "customer_service_admin"
ROLE_CUSTOMER_SERVICE = "customer_service"

ALL_ROLES = frozenset({
    ROLE_ADMIN,
    ROLE_CUSTOMER_SERVICE_ADMIN,
    ROLE_CUSTOMER_SERVICE,
})

ADMIN_CREATABLE_ROLES = frozenset({
    ROLE_ADMIN,
    ROLE_CUSTOMER_SERVICE_ADMIN,
    ROLE_CUSTOMER_SERVICE,
})

CS_ADMIN_MANAGEABLE_ROLES = frozenset({ROLE_CUSTOMER_SERVICE})


def is_admin(role: str) -> bool:
    return role == ROLE_ADMIN


def is_customer_service_admin(role: str) -> bool:
    return role == ROLE_CUSTOMER_SERVICE_ADMIN


def is_customer_service(role: str) -> bool:
    return role == ROLE_CUSTOMER_SERVICE


def can_manage_users(role: str) -> bool:
    return role in (ROLE_ADMIN, ROLE_CUSTOMER_SERVICE_ADMIN)


def cs_admin_can_manage_user(target_role: str) -> bool:
    return target_role == ROLE_CUSTOMER_SERVICE
