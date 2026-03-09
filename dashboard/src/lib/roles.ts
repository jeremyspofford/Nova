export const ROLE_HIERARCHY = ['guest', 'viewer', 'member', 'admin', 'owner'] as const
export type Role = typeof ROLE_HIERARCHY[number]

export function hasMinRole(userRole: Role, minRole: Role): boolean {
  return ROLE_HIERARCHY.indexOf(userRole) >= ROLE_HIERARCHY.indexOf(minRole)
}

export function canAssignRole(assignerRole: Role, targetRole: Role): boolean {
  return ROLE_HIERARCHY.indexOf(assignerRole) >= ROLE_HIERARCHY.indexOf(targetRole)
}

export const ROLE_LABELS: Record<Role, string> = {
  owner: 'Owner',
  admin: 'Admin',
  member: 'Member',
  viewer: 'Viewer',
  guest: 'Guest',
}

export const ROLE_COLORS: Record<Role, string> = {
  owner: 'text-amber-400 bg-amber-400/10',
  admin: 'text-teal-400 bg-teal-400/10',
  member: 'text-stone-300 bg-stone-300/10',
  viewer: 'text-stone-500 bg-stone-500/10',
  guest: 'text-stone-600 bg-stone-600/10',
}
