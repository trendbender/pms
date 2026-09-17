// Thin API client. Tokens live in localStorage for the MVP. The access token is
// short-lived (30 min), so on a 401 we transparently refresh it once using the
// long-lived refresh token and replay the original request.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ACCESS_KEY = "pms_access";
const REFRESH_KEY = "pms_refresh";

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ACCESS_KEY);
}

function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens(access: string, refresh: string) {
  localStorage.setItem(ACCESS_KEY, access);
  localStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Single-flight refresh: many requests can 401 at once (a whole page load), but
// we only want to hit /auth/refresh once and have the rest await the same call.
let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const res = await fetch(`${API_URL}/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: refresh }),
        });
        if (!res.ok) {
          clearTokens();
          return null;
        }
        const data = (await res.json()) as Tokens;
        setTokens(data.access_token, data.refresh_token);
        return data.access_token;
      } catch {
        return null;
      } finally {
        refreshInFlight = null;
      }
    })();
  }
  return refreshInFlight;
}

async function rawFetch(path: string, options: RequestInit, token: string | null) {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_URL}${path}`, { ...options, headers });
}

export async function api<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  let res = await rawFetch(path, options, getAccessToken());

  // Access token likely expired — refresh once and replay. Never try to refresh
  // the auth calls themselves (that would loop).
  const isAuthCall = path.startsWith("/auth/login") || path.startsWith("/auth/refresh");
  if (res.status === 401 && !isAuthCall && getRefreshToken()) {
    const fresh = await refreshAccessToken();
    if (fresh) {
      res = await rawFetch(path, options, fresh);
    } else if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      // Refresh token is gone/expired — send the user to a clean login.
      clearTokens();
      window.location.href = "/login";
    }
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  const data = text ? JSON.parse(text) : null;

  if (!res.ok) {
    const detail = data?.detail ?? res.statusText;
    throw new ApiError(res.status, typeof detail === "string" ? detail : "Request failed");
  }
  return data as T;
}

// Same refresh-on-401 flow as api(), but for a multipart upload: we must NOT set
// Content-Type (the browser adds the multipart boundary itself).
async function uploadFetch(path: string, form: FormData, token: string | null) {
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_URL}${path}`, { method: "POST", body: form, headers });
}

export async function apiUpload<T = unknown>(path: string, form: FormData): Promise<T> {
  let res = await uploadFetch(path, form, getAccessToken());
  if (res.status === 401 && getRefreshToken()) {
    const fresh = await refreshAccessToken();
    if (fresh) res = await uploadFetch(path, form, fresh);
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail ?? res.statusText;
    throw new ApiError(res.status, typeof detail === "string" ? detail : "Upload failed");
  }
  return data as T;
}

// Authenticated binary fetch (attachments): returns an object URL the caller must
// revoke when done. Reuses the refresh-on-401 flow.
export async function apiBlobUrl(path: string): Promise<string> {
  let res = await rawFetch(path, {}, getAccessToken());
  if (res.status === 401 && getRefreshToken()) {
    const fresh = await refreshAccessToken();
    if (fresh) res = await rawFetch(path, {}, fresh);
  }
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

// ---- typed endpoints used in Sprint 1 ----

export interface Tokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Me {
  id: string;
  email: string;
  name: string;
  language: string;
  system_role: string | null;
}

export interface UserRow {
  id: string;
  email: string;
  name: string;
  is_active: boolean;
  is_suspended: boolean;
  system_role: string | null;
}

export async function login(email: string, password: string): Promise<Tokens> {
  const tokens = await api<Tokens>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setTokens(tokens.access_token, tokens.refresh_token);
  return tokens;
}

export const getMe = () => api<Me>("/auth/me");
export const listUsers = () => api<UserRow[]>("/users");

// Self-service profile update (name / UI language).
export const updateMe = (input: { name?: string; language?: string }) =>
  api<Me>("/users/me", { method: "PATCH", body: JSON.stringify(input) });

// --- User management (workspace Owner/Admin) ---
export const inviteUser = (input: {
  email: string;
  name: string;
  system_role: string;
  initial_password?: string;
}) => api<UserRow>("/users/invite", { method: "POST", body: JSON.stringify(input) });

export const updateUser = (
  id: string,
  input: { name?: string; system_role?: string; is_suspended?: boolean }
) => api<UserRow>(`/users/${id}`, { method: "PATCH", body: JSON.stringify(input) });

export interface Member {
  user_id: string;
  email: string;
  name: string;
  role: string;
}
export const listMembers = (projectId: string) =>
  api<Member[]>(`/projects/${projectId}/members`);
export const addMember = (projectId: string, user_id: string, role: string) =>
  api<Member>(`/projects/${projectId}/members`, {
    method: "POST",
    body: JSON.stringify({ user_id, role }),
  });
export const removeMember = (projectId: string, userId: string) =>
  api<void>(`/projects/${projectId}/members/${userId}`, { method: "DELETE" });

export interface Project {
  id: string;
  name: string;
  code: string;
  goal: string | null;
  status: string;
  health: string;
  group_name: string | null;
  wip_limit: number | null;
}

export const listProjects = () => api<Project[]>("/projects");

export const createProject = (input: {
  name: string;
  code: string;
  goal?: string;
  group_name?: string;
}) =>
  api<Project>("/projects", { method: "POST", body: JSON.stringify(input) });

export const getProject = (id: string) => api<Project>(`/projects/${id}`);

// ---- Sprint 3: tasks ----

export interface TaskStatus {
  id: string;
  name: string;
  category: string;
  position: number;
}

export interface Task {
  id: string;
  key: string;
  number: number;
  title: string;
  status_id: string;
  status_name: string | null;
  status_category: string | null;
  priority: string;
  assignee_id: string | null;
  reviewer_id: string | null;
  is_blocked: boolean;
  blocked_reason: string | null;
  due_at: string | null;
}

export const listStatuses = (projectId: string) =>
  api<TaskStatus[]>(`/projects/${projectId}/statuses`);

export const listTasks = (projectId: string) =>
  api<Task[]>(`/projects/${projectId}/tasks`);

export const createTask = (input: { project_id: string; title: string }) =>
  api<Task>("/tasks", { method: "POST", body: JSON.stringify(input) });

export const changeTaskStatus = (taskId: string, statusId: string) =>
  api<Task>(`/tasks/${taskId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status_id: statusId }),
  });

// ---- task detail ----

export interface TaskFull {
  id: string;
  project_id: string;
  number: number;
  key: string;
  title: string;
  description: string | null;
  type_id: string;
  type_name: string | null;
  status_id: string;
  status_name: string | null;
  status_category: string | null;
  priority: string;
  assignee_id: string | null;
  reviewer_id: string | null;
  reporter_id: string | null;
  sprint_id: string | null;
  acceptance_criteria: string | null;
  definition_of_done: string | null;
  story_points: number | null;
  is_blocked: boolean;
  blocked_reason: string | null;
  due_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskComment {
  id: string;
  task_id: string;
  author_id: string | null;
  body: string;
  edited_at: string | null;
  created_at: string;
}

export interface TaskActivity {
  id: string;
  actor_id: string | null;
  action: string;
  data: Record<string, unknown> | null;
  created_at: string;
}

export const getTask = (id: string) => api<TaskFull>(`/tasks/${id}`);
export const getTaskByKey = (key: string) =>
  api<TaskFull>(`/tasks/by-key/${encodeURIComponent(key)}`);
export const getTaskComments = (id: string) =>
  api<TaskComment[]>(`/tasks/${id}/comments`);
export const addTaskComment = (id: string, body: string) =>
  api<TaskComment>(`/tasks/${id}/comments`, {
    method: "POST",
    body: JSON.stringify({ body }),
  });
export const deleteComment = (commentId: string) =>
  api<void>(`/comments/${commentId}`, { method: "DELETE" });
export const getTaskActivity = (id: string) =>
  api<TaskActivity[]>(`/tasks/${id}/activity`);
export interface TaskPatch {
  title?: string;
  description?: string;
  priority?: string;
  assignee_id?: string | null;
  reviewer_id?: string | null;
  acceptance_criteria?: string;
  definition_of_done?: string;
  due_at?: string | null;
  story_points?: number | null;
}

export const updateTask = (id: string, patch: TaskPatch) =>
  api<TaskFull>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(patch) });

export const deleteTask = (id: string) =>
  api<void>(`/tasks/${id}`, { method: "DELETE" });

// ---- attachments ----

export interface Attachment {
  id: string;
  task_id: string;
  comment_id: string | null;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_by: string | null;
  created_at: string;
}

export const listAttachments = (taskId: string) =>
  api<Attachment[]>(`/tasks/${taskId}/attachments`);

export const uploadAttachment = (taskId: string, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<Attachment>(`/tasks/${taskId}/attachments`, form);
};

export const deleteAttachment = (id: string) =>
  api<void>(`/attachments/${id}`, { method: "DELETE" });

export const attachmentBlobUrl = (id: string) => apiBlobUrl(`/attachments/${id}`);

// ---- Sprint 4: kanban board ----

export interface BoardColumn {
  status_id: string;
  name: string;
  category: string;
  position: number;
  wip_limit: number | null;
  wip_exceeded: boolean;
  tasks: Task[];
}

export interface Board {
  project_id: string;
  columns: BoardColumn[];
}

export const getBoard = (projectId: string) =>
  api<Board>(`/projects/${projectId}/board`);

export const moveTask = (
  taskId: string,
  input: { status_id: string; after_id?: string | null; before_id?: string | null }
) =>
  api<Task>(`/tasks/${taskId}/position`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });

// ---- Sprint 5: agile (sprints, initiatives, backlog) ----

export interface SprintStats {
  total: number;
  done: number;
  in_progress: number;
  blocked: number;
  todo: number;
}

export interface Sprint {
  id: string;
  project_id: string;
  name: string;
  goal: string | null;
  status: string;
  start_date: string | null;
  end_date: string | null;
  stats: SprintStats;
}

export interface SprintCompletion {
  sprint: Sprint;
  completed: number;
  moved: number;
  moved_to: string;
}

export const listSprints = (projectId: string) =>
  api<Sprint[]>(`/projects/${projectId}/sprints`);

export const createSprint = (
  projectId: string,
  input: { name: string; goal?: string }
) =>
  api<Sprint>(`/projects/${projectId}/sprints`, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const updateSprint = (
  sprintId: string,
  input: { name?: string; goal?: string }
) =>
  api<Sprint>(`/sprints/${sprintId}`, { method: "PATCH", body: JSON.stringify(input) });

export const startSprint = (sprintId: string) =>
  api<Sprint>(`/sprints/${sprintId}/start`, { method: "POST", body: "{}" });

export const completeSprint = (sprintId: string, nextSprintId?: string) =>
  api<SprintCompletion>(`/sprints/${sprintId}/complete`, {
    method: "POST",
    body: JSON.stringify(nextSprintId ? { next_sprint_id: nextSprintId } : {}),
  });

export const getBacklog = (projectId: string) =>
  api<Task[]>(`/projects/${projectId}/backlog`);

export interface Initiative {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  task_count: number;
  done_count: number;
}

export const listInitiatives = (projectId: string) =>
  api<Initiative[]>(`/projects/${projectId}/initiatives`);

export const createInitiative = (projectId: string, input: { name: string }) =>
  api<Initiative>(`/projects/${projectId}/initiatives`, {
    method: "POST",
    body: JSON.stringify(input),
  });

export const getInitiative = (id: string) => api<Initiative>(`/initiatives/${id}`);

export const listInitiativeTasks = (id: string) =>
  api<Task[]>(`/initiatives/${id}/tasks`);

export const updateInitiative = (
  id: string,
  input: { name?: string; description?: string | null }
) =>
  api<Initiative>(`/initiatives/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });

// ---- Sprint 6: management / dashboards ----

export interface TaskCard {
  id: string;
  key: string;
  title: string;
  priority: string;
  status_name: string | null;
  status_category: string | null;
  due_at: string | null;
  is_blocked: boolean;
  assignee_id: string | null;
  reviewer_id: string | null;
  sprint_id: string | null;
  project_id: string;
  project_code: string;
  project_name: string;
}

export interface PagedTasks {
  items: TaskCard[];
  total: number;
  limit: number;
  offset: number;
}

export interface PortfolioRow {
  project_id: string;
  code: string;
  name: string;
  health: string;
  status: string;
  group_name: string | null;
  open: number;
  overdue: number;
  blocked: number;
  review: number;
  sprint_name: string | null;
  sprint_done: number;
  sprint_total: number;
}

export interface Portfolio {
  rows: PortfolioRow[];
  totals: {
    active_projects: number;
    blockers: number;
    overdue: number;
    waiting_my_review: number;
  };
}

export const getPortfolio = () => api<Portfolio>("/portfolio");
export const getMyTasks = () => api<TaskCard[]>("/me/tasks");
export const getMyReviews = () => api<TaskCard[]>("/me/reviews");

export const getAllTasks = (params: {
  priority?: string;
  category?: string;
  limit?: number;
  offset?: number;
} = {}) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") q.set(k, String(v));
  }
  const qs = q.toString();
  return api<PagedTasks>(`/tasks${qs ? `?${qs}` : ""}`);
};

// ---- Sprint 7: notifications + search ----

export interface Notification {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  task_id: string | null;
  payload: Record<string, unknown> | null;
  read_at: string | null;
  created_at: string;
}

export const getNotifications = () => api<Notification[]>("/me/notifications");
export const getUnreadCount = () =>
  api<{ unread: number }>("/me/notifications/count");
export const markNotificationRead = (id: string) =>
  api<Notification>(`/notifications/${id}/read`, { method: "POST", body: "{}" });
export const markAllNotificationsRead = () =>
  api<{ unread: number }>("/me/notifications/read-all", {
    method: "POST",
    body: "{}",
  });

export const searchTasks = (q: string) =>
  api<TaskCard[]>(`/search?q=${encodeURIComponent(q)}`);
