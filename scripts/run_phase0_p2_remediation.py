from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/apply_phase0_p2_remediation.py"


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    eof_old = '    path.write_text(text + "\\n", encoding="utf-8")\n'
    eof_new = '    path.write_text(text.rstrip() + "\\n", encoding="utf-8")\n'
    restore_block = '''    workflow = subprocess.check_output(
        ["git", "show", f"{RESTORE_WORKFLOW_FROM}:.github/workflows/backend-core.yml"],
        cwd=ROOT,
        text=True,
    )
    (ROOT / ".github/workflows/backend-core.yml").write_text(workflow, encoding="utf-8")

'''
    delete_old = '''    script = ROOT / "scripts/apply_phase0_p2_remediation.py"
    script.unlink()
'''
    delete_new = '''    for temporary in (
        ROOT / "scripts/apply_phase0_p2_remediation.py",
        ROOT / "scripts/run_phase0_p2_remediation.py",
    ):
        temporary.unlink()
'''

    assert text.count(eof_old) == 1
    assert text.count(restore_block) == 1
    assert text.count(delete_old) == 1
    text = text.replace(eof_old, eof_new, 1)
    text = text.replace(restore_block, "", 1)
    text = text.replace(delete_old, delete_new, 1)
    TARGET.write_text(text, encoding="utf-8")

    subprocess.run(["python", str(TARGET)], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
