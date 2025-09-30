export interface WorkerStatus {
  name: string;
  healthy: boolean;
  detail: Record<string, unknown>;
  supports_vnc: boolean;
}

export type StartUrlWait = 'none' | 'domcontentloaded' | 'load';

export interface SessionItem {
  worker: string;
  id: string;
  status: string;
  created_at: string;
  last_seen_at: string;
  headless: boolean;
  idle_ttl_seconds: number;
  labels: Record<string, string>;
  ws_endpoint: string;
  vnc_enabled: boolean;
  vnc: {
    ws?: string | null;
    http?: string | null;
    password_protected?: boolean;
  };
  start_url_wait?: StartUrlWait;
}

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? import.meta.env.VITE_API_BASE ?? '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function fetchWorkers(): Promise<WorkerStatus[]> {
  return request<WorkerStatus[]>('/workers');
}

export function fetchSessions(): Promise<SessionItem[]> {
  return request<SessionItem[]>('/sessions');
}

export function createSession(payload: {
  worker?: string;
  headless?: boolean;
  idle_ttl_seconds?: number;
  start_url?: string;
  labels?: Record<string, string>;
  vnc?: boolean;
  start_url_wait?: StartUrlWait;
}): Promise<SessionItem> {
  return request<SessionItem>('/sessions', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function deleteSession(worker: string, id: string): Promise<{ id: string; status: string }> {
  return request<{ id: string; status: string }>(`/sessions/${worker}/${id}`, {
    method: 'DELETE',
  });
}

export function touchSession(worker: string, id: string): Promise<SessionItem> {
  return request<SessionItem>(`/sessions/${worker}/${id}/touch`, {
    method: 'POST',
  });
}
