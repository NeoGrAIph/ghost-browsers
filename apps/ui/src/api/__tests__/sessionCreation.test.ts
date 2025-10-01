import { describe, expect, it } from 'vitest';
import { buildSessionCreatePayload } from '../sessionCreation';
import { mapCoreEventToView, mapCoreSessionToView } from '../sessionMapper';
import type { SessionComposerValues } from '../../components/SessionComposer';
import type { CoreSession, CoreSessionEvent } from '../sessionMapper';

describe('session creation adapter', () => {
  const baseValues: SessionComposerValues = {
    browserName: 'Camoufox',
    region: 'eu-central',
    proxyId: 'proxy-1',
    headless: false,
    idleTtlSeconds: 300,
    startUrl: '',
    startUrlWait: 'load',
    proxyHttp: '',
    proxyHttps: '',
    proxySocks: '',
  };

  it('produces runner payload with defaults and metadata', () => {
    const payload = buildSessionCreatePayload(baseValues);

    expect(payload).toMatchObject({
      status: 'INIT',
      headless: false,
      idle_ttl_seconds: 300,
      start_url: null,
      start_url_wait: 'load',
      browser: 'Camoufox',
      labels: { region: 'eu-central', proxy_id: 'proxy-1' },
      metadata: { region: 'eu-central', proxy_id: 'proxy-1' },
      proxy: null,
      vnc: null,
    });
    expect(payload).not.toHaveProperty('vnc_enabled');
  });

  it('keeps optional proxy configuration when provided', () => {
    const payload = buildSessionCreatePayload({
      ...baseValues,
      proxyHttp: 'http://proxy.local:3128',
      proxyHttps: '',
      proxySocks: '',
    });

    expect(payload.proxy).toEqual({
      http: 'http://proxy.local:3128',
      https: null,
      socks: null,
    });
    expect(payload.metadata.proxy_label).toBe('http://proxy.local:3128');
  });
});

describe('core session mapping', () => {
  const coreSession: CoreSession = {
    id: 'session-1',
    runner_id: 'runner-1',
    status: 'READY',
    created_at: '2024-01-01T10:00:00Z',
    last_seen_at: '2024-01-01T10:05:00Z',
    ended_at: null,
    start_url: null,
    start_url_wait: 'load',
    headless: false,
    idle_ttl_seconds: 600,
    browser: 'camoufox',
    labels: { region: 'eu-central' },
    ws_endpoint: null,
    proxy: {
      http: null,
      https: null,
      socks: null,
    },
    vnc: {
      http_url: 'https://vnc.example/view',
      websocket_url: null,
      token: null,
      token_ttl_seconds: null,
    },
    vnc_enabled: true,
    metadata: {
      region: 'eu-central',
      browser_version: '1.2.3',
      proxy_id: 'proxy-1',
    },
  };

  it('maps raw session payload into UI-friendly structure', () => {
    const session = mapCoreSessionToView(coreSession);
    expect(session).toMatchObject({
      id: 'session-1',
      status: 'active',
      region: 'eu-central',
      browser: { name: 'camoufox', version: '1.2.3' },
      vncUrl: 'https://vnc.example/view',
    });
    expect(session.metadata.proxy_id).toBe('proxy-1');
  });

  it('maps session events to UI format', () => {
    const event: CoreSessionEvent = {
      id: 'event-1',
      type: 'session.updated',
      session: coreSession,
      occurred_at: '2024-01-01T10:05:00Z',
      reason: null,
    };

    const view = mapCoreEventToView(event);
    expect(view).toMatchObject({
      type: 'updated',
      sessionId: 'session-1',
      occurredAt: '2024-01-01T10:05:00Z',
      reason: null,
    });
    expect(view.session.id).toBe('session-1');
  });
});
