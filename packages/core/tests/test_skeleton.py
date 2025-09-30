from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_task_files_exist():
    assert (ROOT / "README-TASK.md").exists()
    assert (ROOT / "core" / "README-TASK.md").exists()
    assert (ROOT / "AGENT_NOTES.md").exists()


def test_placeholder():
    assert True
