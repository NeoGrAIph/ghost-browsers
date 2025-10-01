import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { openSessionEventStream } from './client';

class MockEventSource {
  public static createdUrls: string[] = [];

  public onmessage: ((event: MessageEvent<string>) => void) | null = null;

  public onerror: ((event: Event) => void) | null = null;

  public onopen: ((event: Event) => void) | null = null;

  public readyState = 0;

  public constructor(public readonly url: string, _initDict?: EventSourceInit) {
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
      // eslint-disable-next-line @typescript-eslint/no-dynamic-delete -- test cleanup
      delete (globalThis as { EventSource?: typeof EventSource }).EventSource;
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
});
