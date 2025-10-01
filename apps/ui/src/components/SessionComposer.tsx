import { useState, type FormEvent } from 'react';

export interface SessionComposerValues {
  readonly browserName: string;
  readonly region: string;
  readonly proxyId: string | null;
}

interface SessionComposerProps {
  readonly onSubmit: (values: SessionComposerValues) => Promise<void>;
  readonly onCancel: () => void;
}

const defaultValues: SessionComposerValues = {
  browserName: 'Chrome',
  region: 'eu-central',
  proxyId: null,
};

/**
 * Modal-like form used to create new sessions.
 */
export function SessionComposer({ onSubmit, onCancel }: SessionComposerProps): JSX.Element {
  const [values, setValues] = useState(defaultValues);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);

    void (async () => {
      try {
        await onSubmit(values);
        setValues(defaultValues);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Не удалось создать сессию');
      } finally {
        setIsSubmitting(false);
      }
    })();
  };

  return (
    <div className="composer" role="dialog" aria-modal>
      <form className="composer__form" onSubmit={handleSubmit}>
        <h2>Новая сессия</h2>
        <label>
          Браузер
          <select
            value={values.browserName}
            onChange={(event) =>
              setValues((current) => ({ ...current, browserName: event.target.value }))
            }
          >
            <option value="Chrome">Chrome</option>
            <option value="Firefox">Firefox</option>
          </select>
        </label>
        <label>
          Регион
          <select
            value={values.region}
            onChange={(event) => setValues((current) => ({ ...current, region: event.target.value }))}
          >
            <option value="eu-central">eu-central</option>
            <option value="us-east">us-east</option>
            <option value="ap-south">ap-south</option>
          </select>
        </label>
        <label>
          Прокси (необязательно)
          <input
            type="text"
            placeholder="proxy-id"
            value={values.proxyId ?? ''}
            onChange={(event) =>
              setValues((current) => ({ ...current, proxyId: event.target.value || null }))
            }
          />
        </label>
        {error && <p className="composer__error">{error}</p>}
        <div className="composer__actions">
          <button type="button" className="ghost" onClick={onCancel}>
            Отмена
          </button>
          <button type="submit" className="primary" disabled={isSubmitting}>
            Создать
          </button>
        </div>
      </form>
    </div>
  );
}
