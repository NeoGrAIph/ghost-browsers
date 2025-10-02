import { describe, expect, it } from 'vitest';
import { buildSessionCreatePayload } from '../sessionCreation';
import type { SessionComposerSubmission } from '../sessionCreation';

describe('session creation adapter', () => {
  const baseValues: SessionComposerSubmission = {
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

  it('disables vnc when headless flag is set', () => {
    const payload = buildSessionCreatePayload({
      ...baseValues,
      headless: true,
    });

    expect(payload.vnc_enabled).toBe(false);
  });
});
