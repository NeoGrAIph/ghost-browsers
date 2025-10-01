import { useMutation, useQueryClient } from '@tanstack/react-query';
import { deleteSession } from '../api/client';
import { queryKeys } from '../utils/queryKeys';
import { Session } from '../types/session';
import { useAuth } from '../hooks/useAuth';

interface SessionActionsProps {
  readonly session: Session | null;
}

/**
 * Action buttons for the selected session.
 */
export function SessionActions({ session }: SessionActionsProps): JSX.Element {
  const queryClient = useQueryClient();
  const { token } = useAuth();

  const deleteMutation = useMutation({
    mutationFn: async () => {
      if (!session) {
        return;
      }
      await deleteSession(session.id, { token: token ?? undefined });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
    },
  });

  return (
    <div className="session-actions">
      <button
        type="button"
        className="danger"
        onClick={() => deleteMutation.mutate()}
        disabled={!session || deleteMutation.isPending}
      >
        Удалить
      </button>
    </div>
  );
}
