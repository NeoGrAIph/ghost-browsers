import type { SessionComposerValues } from '../components/SessionComposer';

/**
 * JSON payload accepted by the Runner ``POST /sessions`` endpoint.
 */
export interface SessionCreateRequest {
  readonly status: 'INIT';
  readonly headless: boolean;
  readonly idle_ttl_seconds: number;
  readonly start_url: string | null;
  readonly start_url_wait: 'none' | 'domcontentloaded' | 'load';
  readonly browser: string;
  readonly labels: Record<string, string>;
  readonly metadata: Record<string, unknown>;
  readonly proxy: {
    readonly http: string | null;
    readonly https: string | null;
    readonly socks: string | null;
  } | null;
  readonly vnc?: null;
  readonly vnc_enabled?: boolean;
}

const sanitizeUrl = (value: string): string | null => {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
};

const buildProxy = (
  values: SessionComposerValues,
): SessionCreateRequest['proxy'] => {
  const http = sanitizeUrl(values.proxyHttp);
  const https = sanitizeUrl(values.proxyHttps);
  const socks = sanitizeUrl(values.proxySocks);

  if (!http && !https && !socks) {
    return null;
  }

  return {
    http,
    https,
    socks,
  };
};

/**
 * Convert form values collected by :component:`SessionComposer` into a Runner payload.
 */
export const buildSessionCreatePayload = (
  values: SessionComposerValues,
): SessionCreateRequest => {
  const startUrl = sanitizeUrl(values.startUrl);
  const labels: Record<string, string> = { region: values.region };
  const metadata: Record<string, unknown> = {
    region: values.region,
  };

  if (values.proxyId) {
    labels.proxy_id = values.proxyId;
    metadata.proxy_id = values.proxyId;
  }

  const proxy = buildProxy(values);
  if (proxy) {
    metadata.proxy_label = proxy.http ?? proxy.https ?? proxy.socks;
  }

  const payload: SessionCreateRequest = {
    status: 'INIT',
    headless: values.headless,
    idle_ttl_seconds: values.idleTtlSeconds,
    start_url: startUrl,
    start_url_wait: values.startUrlWait,
    browser: values.browserName,
    labels,
    metadata,
    proxy,
    vnc: null,
  };

  if (values.headless) {
    payload.vnc_enabled = false;
  }

  return payload;
};
