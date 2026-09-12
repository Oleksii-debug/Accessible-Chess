from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

REPO = Path.cwd()
PRODUCT_BRANCH = os.environ["PRODUCT_BRANCH"]
PACKAGE_BRANCH = os.environ["PACKAGE_BRANCH"]
EXPECTED_PACKAGE_HEAD = os.environ["EXPECTED_PACKAGE_HEAD"]
P0_MERGE_SHA = os.environ["P0_MERGE_SHA"]
API_TOKEN = os.environ["API_TOKEN"]
GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]
AUTOMATION_BRANCH = os.environ["GITHUB_REF_NAME"]
WORKFLOW_PATH = ".github/workflows/post-freeze-v2-windows-package-qualification.yml"
MARKER_PATH = Path("tools/automation/p0_package_remote_commit.txt")


def run(*args: str, input_text: str | None = None, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        args,
        cwd=REPO,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    if proc.returncode:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def git(*args: str, input_text: str | None = None, env: dict[str, str] | None = None) -> str:
    return run("git", *args, input_text=input_text, env=env)


def api(method: str, path: str, payload: dict[str, object] | None = None) -> dict[str, object]:
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {API_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "accessible-chess-package-reconverge",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


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

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        candidate = root / "package.yml"
        candidate.write_text(patched, encoding="utf-8")
        index = root / "index"
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(index)
        git("read-tree", product, env=env)
        local_blob = git("hash-object", "-w", str(candidate))
        git(
            "update-index",
            "--add",
            "--cacheinfo",
            f"100644,{local_blob},{WORKFLOW_PATH}",
            env=env,
        )
        local_tree = git("write-tree", env=env)

    product_commit = api("GET", f"/git/commits/{product}")
    product_tree = str(dict(product_commit["tree"])["sha"])
    remote_blob = api("POST", "/git/blobs", {"content": patched, "encoding": "utf-8"})
    remote_tree = api(
        "POST",
        "/git/trees",
        {
            "base_tree": product_tree,
            "tree": [
                {
                    "path": WORKFLOW_PATH,
                    "mode": "100644",
                    "type": "blob",
                    "sha": str(remote_blob["sha"]),
                }
            ],
        },
    )
    if str(remote_tree["sha"]) != local_tree:
        raise RuntimeError(
            f"remote/local tree mismatch: remote={remote_tree['sha']} local={local_tree}"
        )

    message = (
        "CI: reconverge exact P0 document-copy source oracle on same package lineage\n\n"
        f"First parent exact current Full Product {product}.\n"
        f"Second parent prior SAME WIP=1 package {previous}.\n"
        "Carry the repaired focus-order workflow and bind its prior-package SHA to the exact predecessor.\n\n"
        "HUMAN_TESTED=NO\nNVDA_VERIFIED=NO\nFINAL_WINDOWS_ZIP=NO_PENDING_RUN\n"
    )
    remote_commit = api(
        "POST",
        "/git/commits",
        {
            "message": message,
            "tree": str(remote_tree["sha"]),
            "parents": [product, previous],
        },
    )
    commit = str(remote_commit["sha"])
    parents = [str(dict(parent)["sha"]) for parent in list(remote_commit["parents"])]
    if parents != [product, previous]:
        raise RuntimeError(f"remote package parents mismatch: {parents}")

    git("fetch", "--no-tags", "origin", PRODUCT_BRANCH, PACKAGE_BRANCH)
    if git("rev-parse", f"origin/{PRODUCT_BRANCH}") != product:
        raise RuntimeError("Full Product advanced during package repair")
    if git("rev-parse", f"origin/{PACKAGE_BRANCH}") != previous:
        raise RuntimeError("package lineage advanced during package repair")

    MARKER_PATH.write_text(
        f"REMOTE_PACKAGE_COMMIT={commit}\nPRODUCT_PARENT={product}\nPREVIOUS_PACKAGE={previous}\n",
        encoding="utf-8",
    )
    git("add", str(MARKER_PATH))
    git("commit", "-m", f"Automation: record remote package commit {commit[:12]}")
    git("push", "origin", f"HEAD:refs/heads/{AUTOMATION_BRANCH}")
    print(f"REMOTE_PACKAGE_COMMIT={commit}")
    print(f"PRODUCT_PARENT={product}")
    print(f"PREVIOUS_PACKAGE={previous}")
    print("PACKAGE_REF_NOT_MOVED=PASS")


if __name__ == "__main__":
    main()
