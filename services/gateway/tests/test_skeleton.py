from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_task_and_notes_exist() -> None:
    """Ensure gateway documentation placeholders stay available."""

    assert (ROOT / "README-TASK.md").exists()
    assert (ROOT / "AGENT_NOTES.md").exists()
    assert (ROOT / "app" / "README-TASK.md").exists()
