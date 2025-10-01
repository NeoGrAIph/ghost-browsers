from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_task_and_notes_exist() -> None:
    """Ensure the runner scaffolding documentation is preserved."""

    assert (ROOT / "README-TASK.md").exists()
    assert (ROOT / "AGENT_NOTES.md").exists()
    assert (ROOT / "app" / "README-TASK.md").exists()
