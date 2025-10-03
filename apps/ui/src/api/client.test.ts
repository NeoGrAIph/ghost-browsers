import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { openSessionEventStream } from './client';

class MockEventSource {
  public static createdUrls: string[] = [];

  public onmessage: ((event: MessageEvent<string>) => void) | null = null;

  public onerror: ((event: Event) => void) | null = null;

  public onopen: ((event: Event) => void) | null = null;

  public readyState = 0;

  public constructor(public readonly url: string) {
    MockEventSource.createdUrls.push(url);
  }

  public close(): void {
    this.readyState = 2;
  }

  public addEventListener(): void {}

  public removeEventListener(): void {}

  public dispatchEvent(): boolean {
    return true;
  }
}

describe('openSessionEventStream', () => {
  const originalEventSource = globalThis.EventSource;

  beforeEach(() => {
    MockEventSource.createdUrls = [];
    globalThis.EventSource = MockEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    if (originalEventSource) {
      globalThis.EventSource = originalEventSource;
    } else {
      Reflect.deleteProperty(globalThis as { EventSource?: typeof EventSource }, 'EventSource');
    }
  });

  it('opens /events and forwards the bearer token via query string', () => {
    const { eventSource } = openSessionEventStream({ token: 'abc123' });

    expect(MockEventSource.createdUrls).toHaveLength(1);
    expect(MockEventSource.createdUrls[0]).toContain('/events');
    expect(MockEventSource.createdUrls[0]).toContain('access_token=abc123');

    eventSource.close();
  });

  it('omits the access_token parameter when no token is provided', () => {
    const { eventSource } = openSessionEventStream();

    expect(MockEventSource.createdUrls).toHaveLength(1);
    expect(MockEventSource.createdUrls[0]).toContain('/events');
    expect(MockEventSource.createdUrls[0]).not.toContain('access_token=');

    eventSource.close();
  });

  it('normalises relative gateway URLs against the current origin', async () => {
    vi.resetModules();
    vi.stubEnv('VITE_GATEWAY_URL', '/api');

    try {
      const { openSessionEventStream: relativeOpenSessionEventStream } = await import('./client');

      const { eventSource } = relativeOpenSessionEventStream({ token: 'xyz' });

      expect(MockEventSource.createdUrls).toHaveLength(1);
      expect(MockEventSource.createdUrls[0]).toContain('/api/events');
      expect(MockEventSource.createdUrls[0]).toContain('access_token=xyz');
      expect(MockEventSource.createdUrls[0].startsWith(window.location.origin)).toBe(true);

      eventSource.close();
    } finally {
      vi.unstubAllEnvs();
      vi.resetModules();
    }
  });
});
