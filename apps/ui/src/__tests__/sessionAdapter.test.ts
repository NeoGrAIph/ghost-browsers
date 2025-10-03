import { describe, expect, it } from 'vitest';
import { adaptSession, adaptSessionEvent, type RawSession, type RawSessionEvent } from '../types/session';

describe('session adapters', () => {
  const baseSession: RawSession = {
    id: '00000000-0000-0000-0000-000000000001',
    runner_id: 'runner-1',
    status: 'READY',
    created_at: '2024-01-01T00:00:00Z',
    last_seen_at: '2024-01-01T00:10:00Z',
    ended_at: null,
    start_url: null,
    start_url_wait: 'load',
    headless: false,
    idle_ttl_seconds: 300,
    browser: 'camoufox',
    labels: {
      region: 'eu-central',
      proxy_id: 'proxy-1',
      proxy_label: 'Proxy One',
    },
    ws_endpoint: null,
    ws_public_endpoint: '/sessions/00000000-0000-0000-0000-000000000001/ws',
    proxy: {
      http: 'http://proxy.local:3128',
      https: null,
      socks: null,
    },
    vnc: {
      http_url: 'https://vnc.example/view/1',
      websocket_url: 'wss://vnc.example/ws/1',
      token: 'opaque-token',
      token_ttl_seconds: 60,
    },
    vnc_enabled: true,
    metadata: {
      snapshot_url: 'https://cdn.example/snapshots/1.png',
    },
  };

  it('normalises session payloads to camelCase fields', () => {
    const session = adaptSession(baseSession);

    expect(session).toMatchObject({
      id: baseSession.id,
      runnerId: baseSession.runner_id,
      status: baseSession.status,
      createdAt: baseSession.created_at,
      lastSeenAt: baseSession.last_seen_at,
      region: 'eu-central',
      proxyId: 'proxy-1',
      proxyLabel: 'Proxy One',
      snapshotUrl: 'https://cdn.example/snapshots/1.png',
    });
    expect(session.proxy).toEqual({
      http: 'http://proxy.local:3128',
      https: null,
      socks: null,
    });
    expect(session.vnc).toEqual({
      httpUrl: 'https://vnc.example/view/1?token=opaque-token',
      websocketUrl: 'wss://vnc.example/ws/1?token=opaque-token',
      token: 'opaque-token',
      tokenTtlSeconds: 60,
    });
    expect(session.wsEndpoint).toBe('/sessions/00000000-0000-0000-0000-000000000001/ws');
    expect(session.publicWsEndpoint).toBe('/sessions/00000000-0000-0000-0000-000000000001/ws');
  });

  it('derives event metadata and terminal flag', () => {
    const event: RawSessionEvent = {
      id: '11111111-1111-1111-1111-111111111111',
      type: 'session.updated',
      occurred_at: '2024-01-01T00:10:00Z',
      reason: null,
      session: baseSession,
    };

    const adapted = adaptSessionEvent(event);
    expect(adapted).toMatchObject({
      id: event.id,
      type: event.type,
      occurredAt: event.occurred_at,
      isTerminal: false,
    });
    expect(adapted.session.id).toBe(baseSession.id);
  });
});
