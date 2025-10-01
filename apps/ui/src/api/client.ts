import { z } from 'zod';
import { SessionSchema, SessionEventSchema } from '../types/session';
import type { SessionEvent } from '../types/session';
import { createUrl } from '../utils/url';

const sessionCollectionSchema = z.array(SessionSchema);

/**
 * Declares the shape of the API client configuration.
 *
 * @property baseUrl - Gateway origin used as the prefix for every request.
 */
export interface ApiClientConfig {
  /** Base URL of the Ghost Browsers gateway service. */
  readonly baseUrl: string;
}

/**
 * Describes the headers required for authenticated requests.
 *
 * @property token - Optional bearer token to attach to outgoing requests.
 */
export interface AuthHeaders {
  /** Bearer access token. */
  readonly token?: string;
}

/**
 * Small fetch wrapper tailored to the Ghost Browsers API surface.
 *
 * @example
 * ```ts
 * const client = new ApiClient({ baseUrl: 'https://gateway.example' });
 * const sessions = await client.get('/sessions', sessionCollectionSchema, {
 *   token: 'bearer-token',
 * });
 * ```
 */
export class ApiClient {
  private readonly baseUrl: string;

  public constructor(config: ApiClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
  }

  /**
   * Performs a GET request and decodes the JSON response through the provided Zod schema.
   *
   * @param path - Relative endpoint path (e.g. ``/sessions``).
   * @param schema - Zod schema used to validate and parse the response.
   * @param headers - Optional authentication context for the request.
   * @returns The parsed payload typed by the supplied schema.
   * @throws Error when the HTTP response is not successful or the payload fails validation.
   */
  public async get<T>(path: string, schema: z.ZodSchema<T>, headers?: AuthHeaders): Promise<T> {
    const response = await fetch(createUrl(this.baseUrl, path), {
      method: 'GET',
      headers: this.withAuth(headers),
    });

    if (!response.ok) {
      throw new Error(`GET ${path} failed with ${response.status}`);
    }

    const payload: unknown = await response.json();
    return schema.parse(payload);
  }

  /**
   * Performs a POST request with JSON body and returns the decoded payload.
   *
   * @param path - Relative endpoint path to call.
   * @param schema - Zod schema used for decoding the JSON response body.
   * @param body - Request payload encoded as JSON.
   * @param headers - Optional authentication context for the request.
   * @returns Parsed response body typed by ``schema``.
   * @throws Error when the response is unsuccessful or the payload fails validation.
   */
  public async post<T>(
    path: string,
    schema: z.ZodSchema<T>,
    body: Record<string, unknown>,
    headers?: AuthHeaders,
  ): Promise<T> {
    const response = await fetch(createUrl(this.baseUrl, path), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.withAuth(headers),
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      throw new Error(`POST ${path} failed with ${response.status}`);
    }

    const payload: unknown = await response.json();
    return schema.parse(payload);
  }

  /**
   * Performs a DELETE request.
   *
   * @param path - Endpoint path identifying the resource to remove.
   * @param headers - Optional authentication context for the request.
   * @throws Error when the response is unsuccessful.
   */
  public async delete(path: string, headers?: AuthHeaders): Promise<void> {
    const response = await fetch(createUrl(this.baseUrl, path), {
      method: 'DELETE',
      headers: this.withAuth(headers),
    });

    if (!response.ok) {
      throw new Error(`DELETE ${path} failed with ${response.status}`);
    }
  }

  private withAuth(headers?: AuthHeaders): HeadersInit {
    if (!headers?.token) {
      return {};
    }

    return {
      Authorization: `Bearer ${headers.token}`,
    };
  }
}

const gatewayUrl = import.meta.env.VITE_GATEWAY_URL ?? 'http://localhost:8000';

/**
 * Shared API client instance used by React Query hooks.
 */
export const apiClient = new ApiClient({ baseUrl: gatewayUrl });

/**
 * Fetches the session collection.
 *
 * @param headers - Optional authentication context containing the bearer token.
 * @returns Promise resolving to the typed session list.
 */
export const fetchSessions = async (headers?: AuthHeaders) =>
  apiClient.get('/sessions', sessionCollectionSchema, headers);

/**
 * Creates a new session.
 *
 * @param payload - Request body conforming to the session creation contract.
 * @param headers - Optional authentication context containing the bearer token.
 * @returns Promise resolving to the newly created session instance.
 */
export const createSession = async (
  payload: Record<string, unknown>,
  headers?: AuthHeaders,
) =>
  apiClient.post('/sessions', SessionSchema, payload, headers);

/**
 * Deletes an existing session.
 *
 * @param sessionId - Identifier of the session to remove.
 * @param headers - Optional authentication context containing the bearer token.
 * @returns Promise that resolves once the deletion succeeds.
 */
export const deleteSession = (sessionId: string, headers?: AuthHeaders) =>
  apiClient.delete(`/sessions/${sessionId}`, headers);

/**
 * Opens a typed EventSource connection for session updates.
 *
 * The gateway exposes session events via ``/events`` and accepts the bearer
 * token either through the ``Authorization`` header or the ``access_token``
 * query parameter.  We rely on the latter to authenticate native
 * ``EventSource`` instances.
 *
 * @param headers - Optional authentication context containing the bearer token.
 * @returns ``EventSource`` handle and a parser that converts raw messages into ``SessionEvent``.
 * @example
 * ```ts
 * const { eventSource, parseEvent } = openSessionEventStream({ token: 'abc' });
 * eventSource.onmessage = (message) => {
 *   const event = parseEvent(message);
 *   console.log(event.type);
 * };
 * ```
 */
export const openSessionEventStream = (headers?: AuthHeaders) => {
  const url = new URL(createUrl(gatewayUrl, '/events'));
  if (headers?.token) {
    url.searchParams.set('access_token', headers.token);
  }

  const eventSource = new EventSource(url.toString());
  return {
    eventSource,
    parseEvent: (event: MessageEvent<string>): SessionEvent => {
      const payload: unknown = JSON.parse(event.data);
      return SessionEventSchema.parse(payload);
    },
  };
};
