import { z } from 'zod';

/**
 * Enumerates lifecycle statuses reported by the backend for a session.
 */
export const SessionStatusSchema = z.enum(['INIT', 'READY', 'TERMINATING', 'DEAD']);

/**
 * Enumerates the event types emitted through the session event stream.
 */
export const SessionEventTypeSchema = z.enum([
  'session.created',
  'session.updated',
  'session.ended',
]);

/**
 * Zod schema describing the proxy configuration attached to a session payload.
 */
export const SessionProxySchema = z.object({
  http: z.string().url().nullable(),
  https: z.string().url().nullable(),
  socks: z.string().url().nullable(),
});

/**
 * Zod schema representing the payload accepted by the proxy update endpoint.
 *
 * The backend enforces that at least one proxy endpoint is provided which we
 * mirror on the client to surface validation issues before sending the
 * request.
 */
export const SessionProxyUpdateSchema = SessionProxySchema.superRefine((value, ctx) => {
  if (!value.http && !value.https && !value.socks) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: 'At least one proxy URL must be provided.',
    });
  }
});

/**
 * Zod schema describing the VNC connection parameters for a session.
 */
export const SessionVncSchema = z.object({
  http_url: z.string().url().nullable(),
  websocket_url: z.string().url().nullable(),
  token: z.string().nullable(),
  token_ttl_seconds: z.number().int().positive().nullable(),
});

/**
 * Zod schema for the raw session representation returned by FastAPI.
 */
export const SessionSchema = z.object({
  id: z.string().uuid(),
  runner_id: z.string(),
  status: SessionStatusSchema,
  created_at: z.string(),
  last_seen_at: z.string(),
  ended_at: z.string().nullable(),
  start_url: z.string().url().nullable(),
  start_url_wait: z.enum(['none', 'domcontentloaded', 'load']),
  headless: z.boolean(),
  idle_ttl_seconds: z.number(),
  browser: z.string(),
  labels: z.record(z.string()).default({}),
  ws_endpoint: z.string().nullable(),
  ws_public_endpoint: z.string().nullable(),
  proxy: SessionProxySchema.nullable(),
  vnc: SessionVncSchema.nullable(),
  vnc_enabled: z.boolean().nullable(),
  metadata: z.record(z.unknown()).default({}),
});

/**
 * Zod schema for the raw session event representation streamed by FastAPI.
 */
export const SessionEventSchema = z.object({
  id: z.string().uuid(),
  type: SessionEventTypeSchema,
  session: SessionSchema,
  occurred_at: z.string(),
  reason: z.string().nullable(),
});

export type SessionStatus = z.infer<typeof SessionStatusSchema>;
export type SessionEventType = z.infer<typeof SessionEventTypeSchema>;
export type RawSession = z.infer<typeof SessionSchema>;
export type RawSessionEvent = z.infer<typeof SessionEventSchema>;
export type StartUrlWait = RawSession['start_url_wait'];
export type SessionProxyUpdate = z.infer<typeof SessionProxyUpdateSchema>;

/**
 * UI-friendly proxy descriptor with camelCase keys.
 */
export interface SessionProxy {
  readonly http: string | null;
  readonly https: string | null;
  readonly socks: string | null;
}

/**
 * UI-friendly VNC descriptor with camelCase keys.
 */
export interface SessionVnc {
  readonly httpUrl: string | null;
  readonly websocketUrl: string | null;
  readonly token: string | null;
  readonly tokenTtlSeconds: number | null;
}

/**
 * Normalised session object consumed by the React UI.
 */
export interface Session {
  readonly id: string;
  readonly runnerId: string;
  readonly status: SessionStatus;
  readonly createdAt: string;
  readonly lastSeenAt: string;
  readonly endedAt: string | null;
  readonly startUrl: string | null;
  readonly startUrlWait: StartUrlWait;
  readonly headless: boolean;
  readonly idleTtlSeconds: number;
  readonly browser: string;
  readonly wsEndpoint: string | null;
  readonly publicWsEndpoint: string | null;
  readonly proxy: SessionProxy | null;
  readonly vnc: SessionVnc | null;
  readonly vncEnabled: boolean | null;
  readonly labels: Record<string, string>;
  readonly metadata: Record<string, unknown>;
  readonly region: string | null;
  readonly proxyId: string | null;
  readonly proxyLabel: string | null;
  readonly snapshotUrl: string | null;
}

/**
 * Normalised session event consumed by the React UI.
 */
export interface SessionEvent {
  readonly id: string;
  readonly type: SessionEventType;
  readonly occurredAt: string;
  readonly reason: string | null;
  readonly session: Session;
  readonly isTerminal: boolean;
}

/**
 * Converts a raw proxy payload into the UI representation.
 */
export const adaptProxy = (proxy: RawSession['proxy']): SessionProxy | null => {
  if (!proxy) {
    return null;
  }

  return {
    http: proxy.http ?? null,
    https: proxy.https ?? null,
    socks: proxy.socks ?? null,
  };
};

/**
 * Converts raw VNC data into the UI representation.
 */
const ensureTokenInUrl = (
  url: string | null | undefined,
  token: string | null | undefined,
): string | null => {
  if (!url) {
    return null;
  }
  if (!token) {
    return url;
  }

  try {
    const parsed = new URL(url);
    parsed.searchParams.delete('access_token');
    parsed.searchParams.set('token', token);
    return parsed.toString();
  } catch (error) {
    // In practice URLs are validated on the backend, but we keep the original
    // value if parsing fails to avoid breaking rendering in the UI.
    console.warn('Failed to append VNC token to URL', error);
    return url;
  }
};

export const adaptVnc = (vnc: RawSession['vnc']): SessionVnc | null => {
  if (!vnc) {
    return null;
  }

  const token = vnc.token ?? null;

  return {
    httpUrl: ensureTokenInUrl(vnc.http_url, token),
    websocketUrl: ensureTokenInUrl(vnc.websocket_url, token),
    token,
    tokenTtlSeconds: vnc.token_ttl_seconds ?? null,
  };
};

/**
 * Converts the snake_case FastAPI session payload into the camelCase UI variant.
 */
export const adaptSession = (session: RawSession): Session => {
  const labels = session.labels ?? {};
  const metadata = session.metadata ?? {};
  const snapshotValue = metadata['snapshot_url'];

  return {
    id: session.id,
    runnerId: session.runner_id,
    status: session.status,
    createdAt: session.created_at,
    lastSeenAt: session.last_seen_at,
    endedAt: session.ended_at ?? null,
    startUrl: session.start_url ?? null,
    startUrlWait: session.start_url_wait,
    headless: session.headless,
    idleTtlSeconds: session.idle_ttl_seconds,
    browser: session.browser,
    wsEndpoint: session.ws_endpoint ?? session.ws_public_endpoint ?? null,
    publicWsEndpoint: session.ws_public_endpoint ?? null,
    proxy: adaptProxy(session.proxy),
    vnc: adaptVnc(session.vnc),
    vncEnabled: session.vnc_enabled ?? null,
    labels,
    metadata,
    region: labels.region ?? null,
    proxyId: labels.proxy_id ?? null,
    proxyLabel: labels.proxy_label ?? labels.proxy_id ?? null,
    snapshotUrl: typeof snapshotValue === 'string' ? snapshotValue : null,
  };
};

/**
 * Converts the raw FastAPI session event into the UI representation.
 */
export const adaptSessionEvent = (event: RawSessionEvent): SessionEvent => ({
  id: event.id,
  type: event.type,
  occurredAt: event.occurred_at,
  reason: event.reason ?? null,
  session: adaptSession(event.session),
  isTerminal: event.session.status === 'DEAD',
});
