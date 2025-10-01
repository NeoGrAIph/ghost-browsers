import { z } from 'zod';
import { Session, SessionEvent } from '../types/session';

/**
 * Enumerates the raw status values emitted by the Runner service.
 */
export const CoreSessionStatusSchema = z.enum(['INIT', 'READY', 'TERMINATING', 'DEAD']);

/**
 * Zod schema describing the proxy configuration returned by the Runner.
 */
const CoreProxySchema = z
  .object({
    http: z.string().url().nullable().optional(),
    https: z.string().url().nullable().optional(),
    socks: z.string().url().nullable().optional(),
  })
  .transform((value) => ({
    http: value.http ?? null,
    https: value.https ?? null,
    socks: value.socks ?? null,
  }));

/**
 * Zod schema describing the VNC details embedded in session payloads.
 */
const CoreVncSchema = z
  .object({
    http_url: z.string().url().nullable().optional(),
    websocket_url: z.string().url().nullable().optional(),
    token: z.string().nullable().optional(),
    token_ttl_seconds: z.number().int().nullable().optional(),
  })
  .transform((value) => ({
    http_url: value.http_url ?? null,
    websocket_url: value.websocket_url ?? null,
    token: value.token ?? null,
    token_ttl_seconds: value.token_ttl_seconds ?? null,
  }));

/**
 * Zod schema that mirrors ``core.models.Session``.
 */
export const CoreSessionSchema = z.object({
  id: z.string(),
  runner_id: z.string(),
  status: CoreSessionStatusSchema,
  created_at: z.string(),
  last_seen_at: z.string(),
  ended_at: z.string().nullable().optional(),
  start_url: z.string().url().nullable().optional(),
  start_url_wait: z.enum(['none', 'domcontentloaded', 'load']).default('load'),
  headless: z.boolean().default(false),
  idle_ttl_seconds: z.number().int(),
  browser: z.string(),
  labels: z.record(z.string()).default({}),
  ws_endpoint: z.string().nullable().optional(),
  proxy: CoreProxySchema.nullable().optional(),
  vnc: CoreVncSchema.nullable().optional(),
  vnc_enabled: z.boolean().nullable().optional(),
  metadata: z.record(z.unknown()).default({}),
});

export type CoreSession = z.infer<typeof CoreSessionSchema>;

/**
 * Zod schema describing the Runner → Gateway session event payload.
 */
export const CoreSessionEventSchema = z.object({
  id: z.string(),
  type: z.enum(['session.created', 'session.updated', 'session.ended']),
  session: CoreSessionSchema,
  occurred_at: z.string(),
  reason: z.string().nullable().optional(),
});

export type CoreSessionEvent = z.infer<typeof CoreSessionEventSchema>;

const statusMap: Record<CoreSession['status'], Session['status']> = {
  INIT: 'pending',
  READY: 'active',
  TERMINATING: 'completed',
  DEAD: 'completed',
};

const eventTypeMap: Record<CoreSessionEvent['type'], SessionEvent['type']> = {
  'session.created': 'created',
  'session.updated': 'updated',
  'session.ended': 'deleted',
};

/**
 * Convert arbitrary metadata entries into serialisable strings for the UI.
 */
const coerceMetadataValue = (value: unknown): string | null => {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value === 'string') {
    return value;
  }
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return value.toString();
  }
  if (typeof value === 'symbol') {
    return value.description ?? value.toString();
  }
  if (value instanceof Date) {
    return value.toISOString();
  }
  if (typeof value === 'function') {
    return value.name || '[anonymous function]';
  }
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value);
    } catch {
      return null;
    }
  }
  return '[unsupported]';
};

const normaliseMetadata = (metadata: Record<string, unknown>): Record<string, string> => {
  const entries: [string, string][] = [];
  for (const [key, value] of Object.entries(metadata)) {
    const formatted = coerceMetadataValue(value);
    if (formatted === null) {
      continue;
    }
    entries.push([key, formatted]);
  }
  return Object.fromEntries(entries);
};

const resolveProxy = (
  core: CoreSession,
): Session['proxy'] => {
  const metadataProxyId = core.metadata?.proxy_id ?? core.metadata?.proxyId;
  const proxyId = typeof metadataProxyId === 'string' && metadataProxyId.trim() ? metadataProxyId.trim() : null;
  const proxyLabel =
    (typeof core.metadata?.proxy_label === 'string' && core.metadata.proxy_label.trim()
      ? core.metadata.proxy_label.trim()
      : null) ??
    (proxyId ?? core.proxy?.http ?? core.proxy?.https ?? core.proxy?.socks ?? null);

  if (!proxyId && !proxyLabel) {
    return null;
  }

  return {
    id: proxyId ?? proxyLabel ?? 'proxy',
    label: proxyLabel ?? proxyId ?? 'proxy',
    latencyMs: null,
  };
};

const resolveRegion = (core: CoreSession): string => {
  const fromLabels = typeof core.labels?.region === 'string' ? core.labels.region.trim() : '';
  const fromMetadata = typeof core.metadata?.region === 'string' ? core.metadata.region.trim() : '';
  return fromLabels || fromMetadata || 'unknown';
};

const resolveBrowserVersion = (core: CoreSession): string => {
  const fromMetadata = core.metadata?.browser_version;
  if (typeof fromMetadata === 'string' && fromMetadata.trim()) {
    return fromMetadata.trim();
  }
  if (typeof fromMetadata === 'number') {
    return String(fromMetadata);
  }
  return 'n/a';
};

/**
 * Convert a ``core.Session`` payload into the UI-friendly representation.
 */
export const mapCoreSessionToView = (core: CoreSession): Session => ({
  id: core.id,
  status: statusMap[core.status],
  createdAt: core.created_at,
  updatedAt: core.last_seen_at,
  region: resolveRegion(core),
  proxy: resolveProxy(core),
  browser: {
    name: core.browser,
    version: resolveBrowserVersion(core),
  },
  snapshotUrl:
    (typeof core.metadata?.snapshot_url === 'string' && core.metadata.snapshot_url.trim()
      ? core.metadata.snapshot_url.trim()
      : null) ?? core.vnc?.http_url ?? null,
  vncUrl: core.vnc?.http_url ?? null,
  metadata: normaliseMetadata(core.metadata ?? {}),
});

/**
 * Convert a ``core.SessionEvent`` payload into the UI-friendly representation.
 */
export const mapCoreEventToView = (event: CoreSessionEvent): SessionEvent => ({
  type: eventTypeMap[event.type],
  sessionId: event.session.id,
  session: mapCoreSessionToView(event.session),
  occurredAt: event.occurred_at,
  reason: event.reason ?? null,
});
