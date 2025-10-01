import { useState, type FormEvent } from 'react';
import type { StartUrlWait } from '../types/session';

/**
 * Form values emitted by {@link SessionComposer} when creating a session.
 */
export interface SessionComposerValues {
  readonly browserName: string;
  readonly region: string;
  readonly proxyId: string | null;
  readonly headless: boolean;
  readonly idleTtlSeconds: number;
  readonly startUrl: string;
  readonly startUrlWait: StartUrlWait;
  readonly proxyHttp: string;
  readonly proxyHttps: string;
  readonly proxySocks: string;
}

interface SessionComposerProps {
  readonly onSubmit: (values: SessionComposerValues) => Promise<void>;
  readonly onCancel: () => void;
}

const defaultValues: SessionComposerValues = {
  browserName: 'Chrome',
  region: 'eu-central',
  proxyId: null,
  headless: false,
  idleTtlSeconds: 300,
  startUrl: '',
  startUrlWait: 'load',
  proxyHttp: '',
  proxyHttps: '',
  proxySocks: '',
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
        <label className="composer__checkbox">
          <input
            type="checkbox"
            checked={values.headless}
            onChange={(event) =>
              setValues((current) => ({ ...current, headless: event.target.checked }))
            }
          />
          Запуск без VNC (headless)
        </label>
        <label>
          Idle TTL (сек)
          <input
            type="number"
            min={30}
            max={3600}
            value={values.idleTtlSeconds}
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                idleTtlSeconds: Number.isNaN(Number.parseInt(event.target.value, 10))
                  ? current.idleTtlSeconds
                  : Number.parseInt(event.target.value, 10),
              }))
            }
          />
        </label>
        <label>
          Начальный URL (опционально)
          <input
            type="url"
            placeholder="https://example.org"
            value={values.startUrl}
            onChange={(event) => setValues((current) => ({ ...current, startUrl: event.target.value }))}
          />
        </label>
        <label>
          Ожидание загрузки стартовой страницы
          <select
            value={values.startUrlWait}
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                startUrlWait: event.target.value as StartUrlWait,
              }))
            }
          >
            <option value="load">Полная загрузка</option>
            <option value="domcontentloaded">DOMContentLoaded</option>
            <option value="none">Без ожидания</option>
          </select>
        </label>
        <fieldset className="composer__fieldset">
          <legend>Прокси (опционально)</legend>
          <label>
            Идентификатор прокси
            <input
              type="text"
              placeholder="proxy-id"
              value={values.proxyId ?? ''}
              onChange={(event) =>
                setValues((current) => ({ ...current, proxyId: event.target.value || null }))
              }
            />
          </label>
          <label>
            HTTP
            <input
              type="url"
              placeholder="http://proxy.local:3128"
              value={values.proxyHttp}
              onChange={(event) =>
                setValues((current) => ({ ...current, proxyHttp: event.target.value }))
              }
            />
          </label>
          <label>
            HTTPS
            <input
              type="url"
              placeholder="http://proxy.local:3129"
              value={values.proxyHttps}
              onChange={(event) =>
                setValues((current) => ({ ...current, proxyHttps: event.target.value }))
              }
            />
          </label>
          <label>
            SOCKS
            <input
              type="url"
              placeholder="socks5://proxy.local:1080"
              value={values.proxySocks}
              onChange={(event) =>
                setValues((current) => ({ ...current, proxySocks: event.target.value }))
              }
            />
          </label>
        </fieldset>
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
