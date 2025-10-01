import { z } from 'zod';

/**
 * Zod schema describing the proxy metadata attached to a session.
 */
export const ProxySchema = z.object({
  id: z.string(),
  label: z.string(),
  latencyMs: z.number().nullable(),
});

/**
 * Zod schema describing the browser metadata associated with a session.
 */
export const BrowserSchema = z.object({
  name: z.string(),
  version: z.string(),
});

/**
 * Zod schema for an individual browser session.
 */
export const SessionSchema = z.object({
  id: z.string(),
  status: z.enum(['pending', 'active', 'failed', 'completed']),
  createdAt: z.string(),
  updatedAt: z.string(),
  region: z.string(),
  proxy: ProxySchema.nullable(),
  browser: BrowserSchema,
  snapshotUrl: z.string().url().nullable(),
  vncUrl: z.string().url().nullable(),
  metadata: z.record(z.string()).default({}),
});

/**
 * Session event schema used by the SSE stream.
 */
export const SessionEventSchema = z.object({
  type: z.enum(['created', 'updated', 'deleted']),
  session: SessionSchema,
  sessionId: z.string(),
  occurredAt: z.string(),
  reason: z.string().nullable(),
});

/**
 * TypeScript representation of a session.
 */
export type Session = z.infer<typeof SessionSchema>;

/**
 * TypeScript representation of a session event.
 */
export type SessionEvent = z.infer<typeof SessionEventSchema>;
