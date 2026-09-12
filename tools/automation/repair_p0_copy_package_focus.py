from __future__ import annotations

# Regenerate after the retained presentation-privacy gate became part of Full Product.
import os
import re
import subprocess
from pathlib import Path

REPO = Path.cwd()
PRODUCT_BRANCH = os.environ["PRODUCT_BRANCH"]
PACKAGE_BRANCH = os.environ["PACKAGE_BRANCH"]
EXPECTED_PACKAGE_HEAD = os.environ["EXPECTED_PACKAGE_HEAD"]
P0_MERGE_SHA = os.environ["P0_MERGE_SHA"]
AUTOMATION_BRANCH = os.environ["GITHUB_REF_NAME"]
WORKFLOW_PATH = ".github/workflows/post-freeze-v2-windows-package-qualification.yml"
GENERATED_PATH = Path("tools/automation/generated_post_freeze_v2_windows_package_qualification.yml.txt")
MARKER_PATH = Path("tools/automation/p0_package_reconverge_inputs.txt")


def run(*args: str, input_text: str | None = None) -> str:
    proc = subprocess.run(
        args,
        cwd=REPO,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def git(*args: str, input_text: str | None = None) -> str:
    return run("git", *args, input_text=input_text)


def patch(text: str, previous: str) -> str:
    text, count = re.subn(
        r"(?m)^  EXPECTED_PREVIOUS_CANDIDATE_SHA: [0-9a-f]{40}$",
        f"  EXPECTED_PREVIOUS_CANDIDATE_SHA: {previous}",
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError("package workflow lineage SHA was not found exactly once")

    old_static = """            $target.Select()\n            try {$doc.SetFocus()} catch {}\n            $ws=New-Object -ComObject WScript.Shell\n            $null=$ws.AppActivate($process.Id)\n            Set-Clipboard -Value 'P0_COPY_STATIC_SENTINEL'\n"""
    new_static = """            $ws=New-Object -ComObject WScript.Shell\n            $null=$ws.AppActivate($process.Id)\n            try {$doc.SetFocus()} catch {}\n            $target.Select()\n            Start-Sleep -Milliseconds 100\n            Set-Clipboard -Value 'P0_COPY_STATIC_SENTINEL'\n"""
    if old_static in text:
        text = text.replace(old_static, new_static, 1)
    elif new_static not in text:
        raise RuntimeError("static document-copy focus sequence is neither old nor repaired form")

    old_edit = """            $value.SetValue('e2e4')\n            $move.SetFocus()\n            $null=$ws.AppActivate($process.Id)\n            Set-Clipboard -Value 'P0_COPY_EDIT_SENTINEL'\n"""
    new_edit = """            $value.SetValue('e2e4')\n            $null=$ws.AppActivate($process.Id)\n            $move.SetFocus()\n            Start-Sleep -Milliseconds 100\n            Set-Clipboard -Value 'P0_COPY_EDIT_SENTINEL'\n"""
    if old_edit in text:
        text = text.replace(old_edit, new_edit, 1)
    elif new_edit not in text:
        raise RuntimeError("Move Input copy focus sequence is neither old nor repaired form")
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
    GENERATED_PATH.write_text(patched, encoding="utf-8")
    MARKER_PATH.write_text(
        f"PRODUCT_PARENT={product}\nPREVIOUS_PACKAGE={previous}\nWORKFLOW_PATH={WORKFLOW_PATH}\n",
        encoding="utf-8",
    )

    # Verify that the generated workflow produces exactly one workflow-only delta
    # when overlaid on the exact current Product tree.
    env = dict(os.environ)
    index = str(REPO / ".git" / "p0-package-generated.index")
    try:
        Path(index).unlink(missing_ok=True)
        env["GIT_INDEX_FILE"] = index
        proc = subprocess.run(["git", "read-tree", product], cwd=REPO, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode:
            raise RuntimeError(proc.stderr)
        blob = git("hash-object", "-w", str(GENERATED_PATH))
        proc = subprocess.run(
            ["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},{WORKFLOW_PATH}"],
            cwd=REPO,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if proc.returncode:
            raise RuntimeError(proc.stderr)
        tree_proc = subprocess.run(["git", "write-tree"], cwd=REPO, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if tree_proc.returncode:
            raise RuntimeError(tree_proc.stderr)
        generated_tree = tree_proc.stdout.strip()
        changed = git("diff-tree", "--no-commit-id", "--name-only", "-r", product, generated_tree)
        if changed != WORKFLOW_PATH:
            raise RuntimeError(f"unexpected generated package delta: {changed!r}")
    finally:
        Path(index).unlink(missing_ok=True)

    git("add", str(GENERATED_PATH), str(MARKER_PATH))
    git("commit", "-m", f"Automation: stage package workflow for {product[:12]}")
    git("push", "origin", f"HEAD:refs/heads/{AUTOMATION_BRANCH}")
    print(f"PRODUCT_PARENT={product}")
    print(f"PREVIOUS_PACKAGE={previous}")
    print(f"GENERATED_WORKFLOW_BLOB={blob}")
    print(f"GENERATED_TREE={generated_tree}")
    print("PACKAGE_REF_NOT_MOVED=PASS")


if __name__ == "__main__":
    main()
