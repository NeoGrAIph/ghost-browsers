import type { StartUrlWait, WorkerStatus } from '../api';
import { formatStartUrlWait } from '../utils/session';

export interface LaunchSessionFormState {
  worker?: string;
  headless: boolean;
  idle: number;
  startUrl: string;
  labels: string;
  vnc: boolean;
  startUrlWait: StartUrlWait;
}

interface LaunchSessionFormProps {
  form: LaunchSessionFormState;
  healthyWorkers: WorkerStatus[];
  loading: boolean;
  error: string | null;
  startUrlWaitOptions: StartUrlWait[];
  onChange: (patch: Partial<LaunchSessionFormState>) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
}

export function LaunchSessionForm({
  form,
  healthyWorkers,
  loading,
  error,
  startUrlWaitOptions,
  onChange,
  onSubmit,
}: LaunchSessionFormProps): JSX.Element {
  const workersWithVnc = healthyWorkers.some((worker) => worker.supports_vnc);

  return (
    <form className="launch-form" onSubmit={onSubmit}>
      <label>
        Worker
        <select
          value={form.worker ?? ''}
          onChange={(event) =>
            onChange({
              worker: event.target.value || undefined,
            })
          }
        >
          <option value="">Auto</option>
          {healthyWorkers
            .filter((worker) => !form.vnc || worker.supports_vnc)
            .map((worker) => (
              <option key={worker.name} value={worker.name}>
                {worker.name}
              </option>
            ))}
        </select>
        {form.vnc && !workersWithVnc ? (
          <span className="form-hint">Workers with VNC support are unavailable.</span>
        ) : null}
      </label>

      <div className="launch-row">
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.headless}
            disabled={form.vnc}
            onChange={(event) =>
              onChange({
                headless: event.target.checked,
              })
            }
          />
          Headless
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.vnc}
            onChange={(event) =>
              onChange({
                vnc: event.target.checked,
                headless: event.target.checked ? false : form.headless,
                worker: event.target.checked ? undefined : form.worker,
              })
            }
          />
          Enable VNC
        </label>
      </div>

      <label>
        Idle TTL (seconds)
        <input
          type="number"
          min={30}
          max={3600}
          value={form.idle}
          onChange={(event) =>
            onChange({
              idle: Number(event.target.value),
            })
          }
          required
        />
      </label>

      <label>
        Start URL (optional)
        <input
          type="text"
          inputMode="url"
          placeholder="https://example.org"
          value={form.startUrl}
          onChange={(event) =>
            onChange({
              startUrl: event.target.value,
            })
          }
        />
      </label>

      <label>
        Start URL wait
        <select
          value={form.startUrlWait}
          onChange={(event) =>
            onChange({
              startUrlWait: event.target.value as StartUrlWait,
            })
          }
        >
          {startUrlWaitOptions.map((option) => (
            <option key={option} value={option}>
              {formatStartUrlWait(option)}
            </option>
          ))}
        </select>
      </label>

      <label>
        Labels (key=value, comma separated)
        <input
          type="text"
          placeholder="owner=qa, manual=true"
          value={form.labels}
          onChange={(event) =>
            onChange({
              labels: event.target.value,
            })
          }
        />
      </label>

      <button className="btn btn-primary" type="submit" disabled={loading}>
        {loading ? 'Launching…' : 'Launch session'}
      </button>
      {error && <p className="form-error">{error}</p>}
    </form>
  );
}
