"""Fixed role definitions and hierarchy for RBAC."""
from enum import IntEnum


class Role(IntEnum):
    GUEST = 0
    VIEWER = 1
    MEMBER = 2
    ADMIN = 3
    OWNER = 4


ROLE_NAMES = {r.name.lower(): r for r in Role}
VALID_ROLES = set(ROLE_NAMES.keys())


def parse_role(role_str: str) -> Role:
    return ROLE_NAMES.get(role_str.lower(), Role.MEMBER)


def can_assign_role(assigner_role: str, target_role: str) -> bool:
    return parse_role(assigner_role) >= parse_role(target_role)


def has_min_role(user_role: str, min_role: str) -> bool:
    return parse_role(user_role) >= parse_role(min_role)
