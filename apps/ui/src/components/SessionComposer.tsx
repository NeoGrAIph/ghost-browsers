import { useEffect, useMemo, useState, type FormEvent } from 'react';
import type { SessionComposerData, RunnerChoice } from '../utils/composer';

/**
 * Aggregated form state collected by the session composer modal.
 */
export interface SessionComposerValues {
  readonly browserName: string;
  readonly region: string;
  readonly proxyId: string | null;
  readonly runnerId: string | null;
  readonly headless: boolean;
  readonly idleTtlSeconds: number;
  readonly startUrl: string;
  readonly startUrlWait: 'none' | 'domcontentloaded' | 'load';
  readonly proxyHttp: string;
  readonly proxyHttps: string;
  readonly proxySocks: string;
}

interface SessionComposerProps {
  readonly onSubmit: (values: SessionComposerValues) => Promise<void>;
  readonly onCancel: () => void;
  readonly data: SessionComposerData | null;
  readonly isLoading: boolean;
  readonly error: string | null;
}

const defaultValues: SessionComposerValues = {
  browserName: '',
  region: '',
  proxyId: null,
  runnerId: null,
  headless: false,
  idleTtlSeconds: 300,
  startUrl: '',
  startUrlWait: 'load',
  proxyHttp: '',
  proxyHttps: '',
  proxySocks: '',
};

const matchesSelection = (runner: RunnerChoice, values: SessionComposerValues) => {
  const browserMatches =
    !values.browserName ||
    runner.browsers.length === 0 ||
    runner.browsers.includes(values.browserName);
  const regionMatches =
    !values.region || runner.regions.length === 0 || runner.regions.includes(values.region);
  const proxyMatches =
    !values.proxyId || runner.proxies.length === 0 || runner.proxies.includes(values.proxyId);
  return browserMatches && regionMatches && proxyMatches;
};

const formatRunnerLabel = (runner: RunnerChoice) => {
  const parts: string[] = [];
  parts.push(runner.state === 'idle' ? 'Готов' : runner.state);
  if (typeof runner.availableSlots === 'number') {
    parts.push(`${runner.availableSlots} свободн.`);
  }
  parts.push(runner.supportsVnc ? 'VNC' : 'без VNC');
  return `${runner.id} — ${parts.join(' · ')}`;
};

/**
 * Modal-like form used to create new sessions.
 */
export function SessionComposer({
  onSubmit,
  onCancel,
  data,
  isLoading,
  error,
}: SessionComposerProps): JSX.Element {
  const [values, setValues] = useState(defaultValues);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (!data) {
      return;
    }

    setValues((current) => {
      const nextBrowser = data.browsers.some((option) => option.id === current.browserName)
        ? current.browserName
        : data.browsers[0]?.id ?? '';
      const nextRegion =
        current.region && data.regions.some((option) => option.id === current.region)
          ? current.region
          : data.regions[0]?.id ?? '';
      const nextProxy =
        current.proxyId && data.proxies.some((option) => option.id === current.proxyId)
          ? current.proxyId
          : null;

      if (
        nextBrowser === current.browserName &&
        nextRegion === current.region &&
        nextProxy === current.proxyId
      ) {
        return current;
      }

      return {
        ...current,
        browserName: nextBrowser,
        region: nextRegion,
        proxyId: nextProxy,
        runnerId: null,
      };
    });
  }, [data]);

  const matchingRunners = useMemo(() => {
    if (!data) {
      return [];
    }
    return data.runners.filter((runner) => matchesSelection(runner, values));
  }, [data, values]);

  useEffect(() => {
    if (!values.runnerId) {
      return;
    }
    if (matchingRunners.some((runner) => runner.id === values.runnerId)) {
      return;
    }
    setValues((current) => ({ ...current, runnerId: null }));
  }, [matchingRunners, values.runnerId]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setSubmitError(null);

    void (async () => {
      try {
        await onSubmit(values);
        setValues(defaultValues);
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : 'Не удалось создать сессию');
      } finally {
        setIsSubmitting(false);
      }
    })();
  };

  const isBusy = isSubmitting || isLoading;
  const hasOptions = Boolean(data && data.browsers.length && data.regions.length);
  const canSubmit = hasOptions && values.browserName !== '' && values.region !== '' && !isBusy;

  return (
    <div className="composer" role="dialog" aria-modal>
      <form className="composer__form" onSubmit={handleSubmit}>
        <h2>Новая сессия</h2>
        {isLoading && <p className="composer__hint">Загружаем доступные параметры…</p>}
        {error && <p className="composer__error">{error}</p>}
        <label>
          Браузер
          <select
            value={values.browserName}
            onChange={(event) =>
              setValues((current) => ({ ...current, browserName: event.target.value }))
            }
            disabled={isBusy || !hasOptions}
          >
            {data?.browsers.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Регион
          <select
            value={values.region}
            onChange={(event) => setValues((current) => ({ ...current, region: event.target.value }))}
            disabled={isBusy || !hasOptions}
          >
            {data?.regions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Прокси (необязательно)
          <select
            value={values.proxyId ?? ''}
            onChange={(event) =>
              setValues((current) => ({ ...current, proxyId: event.target.value || null }))
            }
            disabled={isBusy || !data}
          >
            <option value="">Без прокси</option>
            {data?.proxies.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Runner (опционально)
          <select
            value={values.runnerId ?? ''}
            onChange={(event) =>
              setValues((current) => ({ ...current, runnerId: event.target.value || null }))
            }
            disabled={isBusy || !data}
          >
            <option value="">Автовыбор (здоровые)</option>
            {matchingRunners.map((runner) => (
              <option key={runner.id} value={runner.id}>
                {formatRunnerLabel(runner)}
              </option>
            ))}
          </select>
        </label>
        {!isLoading && data && matchingRunners.length === 0 && (
          <p className="composer__hint">Нет подходящих раннеров для выбранных параметров.</p>
        )}
        {submitError && <p className="composer__error">{submitError}</p>}
        <div className="composer__actions">
          <button type="button" className="ghost" onClick={onCancel}>
            Отмена
          </button>
          <button type="submit" className="primary" disabled={!canSubmit}>
            Создать
          </button>
        </div>
      </form>
    </div>
  );
}
