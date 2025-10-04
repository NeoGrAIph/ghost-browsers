import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { SessionDetailsPanel } from '../components/SessionDetailsPanel';
import type { Session } from '../types/session';

describe('SessionDetailsPanel', () => {
  it('renders the VNC iframe with the tokenised URL', () => {
    const session: Session = {
      id: '00000000-0000-0000-0000-000000000001',
      runnerId: 'runner-1',
      status: 'READY',
      createdAt: '2024-01-01T00:00:00Z',
      lastSeenAt: '2024-01-01T00:01:00Z',
      endedAt: null,
      startUrl: null,
      startUrlWait: 'load',
      headless: false,
      idleTtlSeconds: 300,
      browser: 'camoufox',
      wsEndpoint: null,
      publicWsEndpoint: null,
      proxy: null,
      vnc: {
        httpUrl: 'https://vnc.example/view/1?token=opaque-token',
        websocketUrl: null,
        token: 'opaque-token',
        tokenTtlSeconds: 60,
      },
      vncEnabled: true,
      labels: {},
      metadata: {},
      region: null,
      proxyId: null,
      proxyLabel: null,
      snapshotUrl: null,
    };

    render(
      <SessionDetailsPanel session={session} now={Date.parse('2024-01-01T00:02:00Z')} onTogglePin={() => {}} isPinned={false} />,
    );

    const iframe = screen.getByTitle('VNC');
    if (!(iframe instanceof HTMLIFrameElement)) {
      throw new Error('Expected VNC preview to render as an <iframe>.');
    }

    expect(iframe.src).toContain('token=opaque-token');
  });
});
