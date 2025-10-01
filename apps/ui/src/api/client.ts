import { z } from 'zod';
import { SessionSchema, SessionEventSchema } from '../types/session';
import { createUrl } from '../utils/url';

const sessionCollectionSchema = z.object({
  sessions: z.array(SessionSchema),
});

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
 * Fetches the session collection.
 */
export const fetchSessions = async (headers?: AuthHeaders) =>
  apiClient.get('/sessions', sessionCollectionSchema, headers);

/**
 * Creates a new session.
 */
export const createSession = async (
  payload: Record<string, unknown>,
  headers?: AuthHeaders,
) =>
  apiClient.post('/sessions', SessionSchema, payload, headers);

/**
 * Deletes an existing session.
 */
export const deleteSession = (sessionId: string, headers?: AuthHeaders) =>
  apiClient.delete(`/sessions/${sessionId}`, headers);

/**
 * Opens a typed EventSource connection for session updates.
 */
export const openSessionEventStream = (headers?: AuthHeaders) => {
  const url = new URL(createUrl(gatewayUrl, '/sessions/stream'));
  if (headers?.token) {
    url.searchParams.set('access_token', headers.token);
  }

  const eventSource = new EventSource(url);
  return {
    eventSource,
    parseEvent: (event: MessageEvent<string>) => {
      const payload: unknown = JSON.parse(event.data);
      return SessionEventSchema.parse(payload);
    },
  };
};
