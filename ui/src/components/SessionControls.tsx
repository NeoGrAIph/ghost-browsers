interface SessionControlsProps {
  onTouch: () => void;
  onKill: () => void;
  isTouching: boolean;
  isKilling: boolean;
}

export function SessionControls({
  onTouch,
  onKill,
  isTouching,
  isKilling,
}: SessionControlsProps): JSX.Element {
  return (
    <div className="actions">
      <button
        className="btn btn-secondary"
        type="button"
        onClick={onTouch}
        disabled={isTouching}
      >
        {isTouching ? 'Extending…' : 'Extend TTL'}
      </button>
      <button className="btn btn-danger" type="button" onClick={onKill} disabled={isKilling}>
        {isKilling ? 'Terminating…' : 'Terminate'}
      </button>
    </div>
  );
}
