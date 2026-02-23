/**
 * Auth utilities — JWT storage, user context helpers.
 * Supports localStorage (browser) with server-side fallback.
 */

const TOKEN_KEY = "langorch_token";
const USER_KEY = "langorch_user";

export type AuthUser = {
  identity: string;
  roles: string[];
  user_id?: string;
  email?: string;
  full_name?: string;
  role?: string;
};

// Five-tier role hierarchy (ascending privilege)
export const ROLES = ["viewer", "approver", "operator", "manager", "admin"] as const;
export type Role = (typeof ROLES)[number];

export const ROLE_LABELS: Record<string, string> = {
  viewer: "Viewer",
  approver: "Approver",
  operator: "Operator",
  manager: "Manager",
  admin: "Admin",
};

export const ROLE_COLORS: Record<string, string> = {
  viewer: "bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400",
  approver: "bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400",
  operator: "bg-blue-100 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400",
  manager: "bg-purple-100 dark:bg-purple-950/40 text-purple-700 dark:text-purple-400",
  admin: "bg-red-100 dark:bg-red-950/40 text-red-700 dark:text-red-400",
};

// ── Storage helpers ────────────────────────────────────────────────────────

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function setToken(token: string): void {
  if (isBrowser()) localStorage.setItem(TOKEN_KEY, token);
}

export function getToken(): string | null {
  if (!isBrowser()) return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function removeToken(): void {
  if (isBrowser()) {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }
}

export function setUser(user: AuthUser): void {
  if (isBrowser()) localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getUser(): AuthUser | null {
  if (!isBrowser()) return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function isAuthenticated(): boolean {
  const token = getToken();
  if (!token) return false;
  try {
    // Decode payload without verifying signature (verification is server-side)
    const [, payloadB64] = token.split(".");
    const payload = JSON.parse(atob(payloadB64.replace(/-/g, "+").replace(/_/g, "/")));
    const exp: number = payload.exp;
    return exp > Date.now() / 1000;
  } catch {
    return false;
  }
}

export function hasRole(userOrRoles: AuthUser | string[] | null, required: string): boolean {
  const roles = Array.isArray(userOrRoles) ? userOrRoles : userOrRoles?.roles ?? [];
  const roleIdx = ROLES.indexOf(required as Role);
  if (roleIdx === -1) return roles.includes(required);
  for (const r of roles) {
    const idx = ROLES.indexOf(r as Role);
    if (idx >= roleIdx) return true;
  }
  return false;
}

export function logout(): void {
  removeToken();
  if (isBrowser()) window.location.href = "/login";
}
