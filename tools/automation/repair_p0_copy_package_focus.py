from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

REPO = Path.cwd()
PRODUCT_BRANCH = os.environ["PRODUCT_BRANCH"]
PACKAGE_BRANCH = os.environ["PACKAGE_BRANCH"]
EXPECTED_PACKAGE_HEAD = os.environ["EXPECTED_PACKAGE_HEAD"]
P0_MERGE_SHA = os.environ["P0_MERGE_SHA"]
WORKFLOW_PATH = ".github/workflows/post-freeze-v2-windows-package-qualification.yml"


def run(*args: str, input_text: str | None = None, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(args, cwd=REPO, input=input_text, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if proc.returncode:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    return proc.stdout.strip()


def git(*args: str, input_text: str | None = None, env: dict[str, str] | None = None) -> str:
    return run("git", *args, input_text=input_text, env=env)


def patch(text: str, previous: str) -> str:
    text, count = re.subn(
        r"(?m)^  EXPECTED_PREVIOUS_CANDIDATE_SHA: [0-9a-f]{40}$",
        f"  EXPECTED_PREVIOUS_CANDIDATE_SHA: {previous}",
        text,
        count=1,
    )
    assert count == 1
    old_static = """            $target.Select()\n            try {$doc.SetFocus()} catch {}\n            $ws=New-Object -ComObject WScript.Shell\n            $null=$ws.AppActivate($process.Id)\n            Set-Clipboard -Value 'P0_COPY_STATIC_SENTINEL'\n"""
    new_static = """            $ws=New-Object -ComObject WScript.Shell\n            $null=$ws.AppActivate($process.Id)\n            try {$doc.SetFocus()} catch {}\n            $target.Select()\n            Start-Sleep -Milliseconds 100\n            Set-Clipboard -Value 'P0_COPY_STATIC_SENTINEL'\n"""
    assert old_static in text, "static selection focus sequence not found"
    text = text.replace(old_static, new_static, 1)

    old_edit = """            $value.SetValue('e2e4')\n            $move.SetFocus()\n            $null=$ws.AppActivate($process.Id)\n            Set-Clipboard -Value 'P0_COPY_EDIT_SENTINEL'\n"""
    new_edit = """            $value.SetValue('e2e4')\n            $null=$ws.AppActivate($process.Id)\n            $move.SetFocus()\n            Start-Sleep -Milliseconds 100\n            Set-Clipboard -Value 'P0_COPY_EDIT_SENTINEL'\n"""
    assert old_edit in text, "Move Input focus sequence not found"
    text = text.replace(old_edit, new_edit, 1)
    return text


def main() -> None:
    git("config", "user.name", "Accessible Chess W5")
    git("config", "user.email", "actions@users.noreply.github.com")
    git("fetch", "--no-tags", "origin", PRODUCT_BRANCH, PACKAGE_BRANCH)
    product = git("rev-parse", f"origin/{PRODUCT_BRANCH}")
    previous = git("rev-parse", f"origin/{PACKAGE_BRANCH}")
    if previous != EXPECTED_PACKAGE_HEAD:
        raise RuntimeError(f"package head moved: expected {EXPECTED_PACKAGE_HEAD}, got {previous}")
    git("merge-base", "--is-ancestor", P0_MERGE_SHA, product)
    original = git("show", f"{previous}:{WORKFLOW_PATH}") + "\n"
    patched = patch(original, previous)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        candidate = root / "package.yml"
        candidate.write_text(patched, encoding="utf-8")
        index = root / "index"
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(index)
        git("read-tree", product, env=env)
        blob = git("hash-object", "-w", str(candidate))
        git("update-index", "--add", "--cacheinfo", f"100644,{blob},{WORKFLOW_PATH}", env=env)
        tree = git("write-tree", env=env)

    message = (
        "CI: harden P0 document-copy focus order on same package lineage\n\n"
        f"First parent exact current Full Product {product}.\n"
        f"Second parent prior SAME WIP=1 package {previous}.\n"
        "Activate window and focus UIA Document/Edit before selecting text so the native Ctrl+C gate cannot invalidate its own selection.\n\n"
        "HUMAN_TESTED=NO\nNVDA_VERIFIED=NO\nFINAL_WINDOWS_ZIP=NO_PENDING_RUN\n"
    )
    commit = git("commit-tree", tree, "-p", product, "-p", previous, input_text=message)
    changed = git("diff", "--name-only", product, commit)
    if changed != WORKFLOW_PATH:
        raise RuntimeError(f"unexpected package delta: {changed!r}")
    git("diff", "--check", product, commit)
    git("fetch", "--no-tags", "origin", PRODUCT_BRANCH, PACKAGE_BRANCH)
    if git("rev-parse", f"origin/{PRODUCT_BRANCH}") != product:
        raise RuntimeError("Full Product advanced during package repair")
    if git("rev-parse", f"origin/{PACKAGE_BRANCH}") != previous:
        raise RuntimeError("package lineage advanced during package repair")
    # This push is expected to be rejected by the Actions token because the commit modifies a workflow.
    # The uploaded commit object remains addressable; the trusted connector advances the branch ref without force.
    git("push", "origin", f"{commit}:refs/heads/{PACKAGE_BRANCH}")
    print(f"REPAIRED_PACKAGE_HEAD={commit}")


if __name__ == "__main__":
    main()
