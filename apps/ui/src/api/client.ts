import { z } from 'zod';
import {
  SessionSchema,
  SessionEventSchema,
  adaptSession,
  adaptSessionEvent,
  type Session,
  type SessionEvent,
} from '../types/session';
import { createUrl } from '../utils/url';

/**
 * Declares the shape of the API client configuration.
 */
export interface ApiClientConfig {
  /** Base URL of the Ghost Browsers gateway service. */
  readonly baseUrl: string;
}

/**
 * Describes the headers required for authenticated requests.
 */
export interface AuthHeaders {
  /** Bearer access token. */
  readonly token?: string;
}

/**
 * Small fetch wrapper tailored to the Ghost Browsers API surface.
 */
export class ApiClient {
  private readonly baseUrl: string;

  public constructor(config: ApiClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
  }

  /**
   * Performs a GET request and decodes the JSON response through the provided Zod schema.
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
 * Fetches the session collection and normalises the payload for the UI.
 */
export const fetchSessions = async (headers?: AuthHeaders): Promise<Session[]> => {
  const payload = await apiClient.get('/sessions', z.array(SessionSchema), headers);
  return payload.map(adaptSession);
};

/**
 * Creates a new session.
 */
export const createSession = async (
  payload: Record<string, unknown>,
  headers?: AuthHeaders,
): Promise<Session> => apiClient.post('/sessions', SessionSchema, payload, headers).then(adaptSession);

/**
 * Deletes an existing session.
 */
export const deleteSession = (sessionId: string, headers?: AuthHeaders) =>
  apiClient.delete(`/sessions/${sessionId}`, headers);

/**
 * Opens a typed EventSource connection for session updates.
 *
 * The backend accepts bearer credentials in the `Authorization` header as well
 * as the `access_token` query parameter. Because the native EventSource API
 * does not allow custom headers, the token is appended to the stream URL when
 * present so both the default browser implementation and polyfills with header
 * support function correctly.
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
      const parsed = SessionEventSchema.parse(payload);
      return adaptSessionEvent(parsed);
    },
  };
};
