import { z } from 'zod';

/**
 * Enumerates operational states reported by the gateway for runners.
 */
export const RunnerStateSchema = z.enum(['starting', 'idle', 'busy', 'degraded', 'offline']);

/**
 * Zod schema describing the raw runner payload returned by FastAPI.
 */
export const RunnerStatusSchema = z
  .object({
    id: z.string(),
    base_url: z.string().url(),
    state: RunnerStateSchema,
    total_slots: z.number().int().nonnegative().nullable(),
    available_slots: z.number().int().nonnegative().nullable(),
    healthy: z.boolean(),
    supports_vnc: z.boolean(),
    last_heartbeat_at: z.string().nullable(),
    vnc_http_url_template: z.string().nullable().optional(),
    vnc_ws_url_template: z.string().nullable().optional(),
    capabilities: z.array(z.string()).optional().default([]),
  })
  .passthrough();

export type RunnerState = z.infer<typeof RunnerStateSchema>;
export type RawRunnerStatus = z.infer<typeof RunnerStatusSchema>;

/**
 * Normalised runner snapshot consumed by the React UI.
 */
export interface RunnerStatus {
  readonly id: string;
  readonly baseUrl: string;
  readonly state: RunnerState;
  readonly totalSlots: number | null;
  readonly availableSlots: number | null;
  readonly healthy: boolean;
  readonly supportsVnc: boolean;
  readonly lastHeartbeatAt: string | null;
  readonly vncHttpUrlTemplate: string | null;
  readonly vncWsUrlTemplate: string | null;
  readonly capabilities: readonly string[];
}

/**
 * Converts the snake_case runner payload into the camelCase UI variant.
 */
export const adaptRunnerStatus = (runner: RawRunnerStatus): RunnerStatus => ({
  id: runner.id,
  baseUrl: runner.base_url,
  state: runner.state,
  totalSlots: runner.total_slots ?? null,
  availableSlots: runner.available_slots ?? null,
  healthy: runner.healthy,
  supportsVnc: runner.supports_vnc,
  lastHeartbeatAt: runner.last_heartbeat_at ?? null,
  vncHttpUrlTemplate: runner.vnc_http_url_template ?? null,
  vncWsUrlTemplate: runner.vnc_ws_url_template ?? null,
  capabilities: runner.capabilities ?? [],
});

