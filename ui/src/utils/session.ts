import type { SessionItem, StartUrlWait } from '../api';

export { StartUrlWait };

export function sessionKey(session: Pick<SessionItem, 'worker' | 'id'>): string {
  return `${session.worker}:${session.id}`;
}

export function formatStartUrlWait(mode: StartUrlWait | undefined | null): string {
  switch (mode) {
    case 'none':
      return 'No wait';
    case 'domcontentloaded':
      return 'DOM ready';
    case 'load':
    default:
      return 'Full load';
  }
}

export function getStatusBadgeClass(status: SessionItem['status']): string {
  switch (status) {
    case 'READY':
      return 'badge badge-ready';
    case 'INIT':
      return 'badge badge-warmup';
    case 'TERMINATING':
      return 'badge badge-warning';
    case 'DEAD':
      return 'badge badge-dead';
    default:
      return 'badge';
  }
}
