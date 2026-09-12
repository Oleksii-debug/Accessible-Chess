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
    proc = subprocess.run(
        args,
        cwd=REPO,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout.strip()


def git(*args: str, input_text: str | None = None, env: dict[str, str] | None = None) -> str:
    return run("git", *args, input_text=input_text, env=env)


def patch_workflow(text: str, previous: str) -> str:
    text, count = re.subn(
        r"(?m)^  EXPECTED_PREVIOUS_CANDIDATE_SHA: [0-9a-f]{40}$",
        f"  EXPECTED_PREVIOUS_CANDIDATE_SHA: {previous}",
        text,
        count=1,
    )
    assert count == 1, "package predecessor pin not found"

    old_tests = (
        "python -m unittest -v tests.test_v2_book_training_route_rollback "
        "tests.test_v2_board_analysis_hotkey_feedback tests.test_w3_p0f_starter_books_training_content\n"
    )
    new_tests = old_tests.rstrip("\n") + " tests.test_p0_semantic_document_copy\n"
    assert old_tests in text, "source regression command not found"
    text = text.replace(old_tests, new_tests, 1)

    source_marker = "          if($LASTEXITCODE -ne 0){throw 'SOURCE_P0G_W3_REGRESSION_FAILURE'}\n"
    assert source_marker in text, "source failure marker not found"
    text = text.replace(
        source_marker,
        source_marker
        + "          node --check web/version2_final_product_bootstrap.js\n"
        + "          if($LASTEXITCODE -ne 0){throw 'P0_DOCUMENT_COPY_BOOTSTRAP_PARSE_FAILURE'}\n"
        + "          Write-Host 'SOURCE_P0_DOCUMENT_COPY_CONTRACT=PASS'\n",
        1,
    )

    package_step = r'''      - name: Prove packaged semantic document selection and native Ctrl+C
        shell: pwsh
        run: |
          $ErrorActionPreference='Stop'
          $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS='--force-renderer-accessibility'
          Add-Type -AssemblyName UIAutomationClient
          Add-Type -AssemblyName UIAutomationTypes
          if(-not ('AccessibleChessCopyKeys' -as [type])){
            Add-Type -TypeDefinition @"
          using System;
          using System.Runtime.InteropServices;
          public static class AccessibleChessCopyKeys {
            [DllImport("user32.dll")]
            private static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);
            private const uint KEYEVENTF_KEYUP = 0x0002;
            public static void Ctrl(byte key) {
              keybd_event(0x11, 0, 0, UIntPtr.Zero);
              keybd_event(key, 0, 0, UIntPtr.Zero);
              keybd_event(key, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
              keybd_event(0x11, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
            }
          }
          "@
          }
          function WaitClipboard([string]$expected,[int]$timeoutMs=5000){
            $watch=[System.Diagnostics.Stopwatch]::StartNew()
            $last=''
            while($watch.ElapsedMilliseconds -lt $timeoutMs){
              try {$last=[string](Get-Clipboard -Raw -ErrorAction Stop)} catch {$last=''}
              if($last.Trim() -eq $expected.Trim()){return $last}
              Start-Sleep -Milliseconds 100
            }
            throw "Clipboard did not receive exact selected text; expected='$expected' actual='$last'"
          }
          $productRoot=(Resolve-Path 'fresh-extraction\AccessibleChess').Path
          $exe=(Resolve-Path (Join-Path $productRoot 'AccessibleChess.exe')).Path
          $process=Start-Process -FilePath $exe -WorkingDirectory $productRoot -PassThru
          try {
            $desktop=[System.Windows.Automation.AutomationElement]::RootElement
            if($null -eq $desktop){throw 'UIA desktop root unavailable'}
            $pidCondition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty,$process.Id)
            $docTypeCondition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::Document)
            $docCondition=[System.Windows.Automation.AndCondition]::new([System.Windows.Automation.Condition[]]@($pidCondition,$docTypeCondition))
            $doc=$null
            $watch=[System.Diagnostics.Stopwatch]::StartNew()
            while($watch.ElapsedMilliseconds -lt 45000){
              if($process.HasExited){throw "Packaged process exited before document-copy proof with code $($process.ExitCode)"}
              $docs=@($desktop.FindAll([System.Windows.Automation.TreeScope]::Descendants,$docCondition))
              if($docs.Count -gt 0){$doc=$docs[0]; break}
              Start-Sleep -Milliseconds 250
            }
            if($null -eq $doc){throw 'Packaged WebView Document UIA element not found'}
            try {$textPattern=$doc.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)} catch {throw "Packaged WebView Document lacks TextPattern: $($_.Exception.Message)"}
            if($null -eq $textPattern){throw 'Packaged WebView Document lacks TextPattern'}
            if(([string]$textPattern.SupportedTextSelection) -match 'None$'){throw 'Packaged WebView Document reports no text selection support'}
            $all=$textPattern.DocumentRange.Clone()
            $target=$all.FindText('Інформація про гру',$false,$false)
            if($null -eq $target){$target=$all.FindText('Game information',$false,$false)}
            if($null -eq $target){throw 'Stable static document text not found through UIA TextPattern'}
            $selected=([string]$target.GetText(-1)).Trim()
            if(-not $selected){throw 'Static TextPattern target is empty'}
            $enclosing=$target.GetEnclosingElement()
            if($null -ne $enclosing -and [string]$enclosing.Current.ControlType.ProgrammaticName -eq 'ControlType.Edit'){
              throw 'Static text proof accidentally targeted an edit control'
            }
            $target.Select()
            try {$doc.SetFocus()} catch {}
            $ws=New-Object -ComObject WScript.Shell
            $null=$ws.AppActivate($process.Id)
            Set-Clipboard -Value 'P0_COPY_STATIC_SENTINEL'
            Start-Sleep -Milliseconds 150
            [AccessibleChessCopyKeys]::Ctrl([byte]0x43)
            $null=WaitClipboard $selected
            Write-Host "PACKAGED_STATIC_DOCUMENT_SELECTION_COPY=PASS text='$selected'"

            $idCondition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty,'move-input')
            $moveCondition=[System.Windows.Automation.AndCondition]::new([System.Windows.Automation.Condition[]]@($pidCondition,$idCondition))
            $move=$desktop.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$moveCondition)
            if($null -eq $move){throw 'Move Input UIA element not found'}
            try {$value=$move.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)} catch {throw "Move Input lacks ValuePattern: $($_.Exception.Message)"}
            if($null -eq $value){throw 'Move Input lacks ValuePattern'}
            $value.SetValue('e2e4')
            $move.SetFocus()
            $null=$ws.AppActivate($process.Id)
            Set-Clipboard -Value 'P0_COPY_EDIT_SENTINEL'
            Start-Sleep -Milliseconds 100
            [AccessibleChessCopyKeys]::Ctrl([byte]0x41)
            [AccessibleChessCopyKeys]::Ctrl([byte]0x43)
            $null=WaitClipboard 'e2e4'
            $value.SetValue('')
            Write-Host 'PACKAGED_MOVE_INPUT_NATIVE_CTRL_A_CTRL_C=PASS'

            $summary=[ordered]@{
              product_sha=$env:PRODUCT_PARENT
              static_document_text=$selected
              static_document_outside_edit=$true
              textpattern_selection_supported=$true
              ctrl_c_exact_clipboard=$true
              move_input_native_ctrl_a_ctrl_c=$true
              human_tested=$false
              nvda_verified=$false
            }
            $summary|ConvertTo-Json -Depth 4|Set-Content -Encoding UTF8 packaged-v2-document-copy-summary.json
          }
          finally {
            $live=Get-Process -Id $process.Id -ErrorAction SilentlyContinue
            if($live){Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue}
          }
          if(-not (Test-Path packaged-v2-document-copy-summary.json)){throw 'Packaged document-copy evidence missing'}
          $bounded=Get-Content -Raw packaged-v2-document-copy-summary.json
          if($bounded -match '(?i)[A-Z]:\\\\|/home/|/Users/|/tmp/'){throw 'Local path leaked into document-copy evidence'}

'''
    package_marker = "      - name: Prove packaged P0-G Books Training keyboard close and restart\n"
    assert package_marker in text, "packaged acceptance insertion point not found"
    text = text.replace(package_marker, package_step + package_marker, 1)

    upload_marker = (
        "            packaged-v2-current-native-menu-summary.json\n"
        "            packaged-final-acceptance-summary.json\n"
    )
    assert upload_marker in text, "artifact upload list not found"
    text = text.replace(
        upload_marker,
        "            packaged-v2-current-native-menu-summary.json\n"
        "            packaged-v2-document-copy-summary.json\n"
        "            packaged-final-acceptance-summary.json\n",
        1,
    )

    evidence_marker = "          $evidencePath=Join-Path 'artifact-readback' 'packaged-final-acceptance-summary.json'\n"
    assert evidence_marker in text, "artifact readback insertion point not found"
    copy_readback = """          $copyPath=Join-Path 'artifact-readback' 'packaged-v2-document-copy-summary.json'\n          if(-not (Test-Path -LiteralPath $copyPath)){throw 'Downloaded document-copy evidence missing'}\n          $copy=Get-Content -LiteralPath $copyPath -Raw|ConvertFrom-Json\n          if([string]$copy.product_sha -ne $env:PRODUCT_PARENT){throw 'Downloaded document-copy Product SHA mismatch'}\n          if(-not [bool]$copy.static_document_outside_edit -or -not [bool]$copy.textpattern_selection_supported -or -not [bool]$copy.ctrl_c_exact_clipboard){throw 'Downloaded static document-copy evidence incomplete'}\n          if(-not [bool]$copy.move_input_native_ctrl_a_ctrl_c){throw 'Downloaded Move Input copy evidence incomplete'}\n          if([bool]$copy.human_tested -or [bool]$copy.nvda_verified){throw 'Automated document-copy evidence illegally claims human/NVDA verification'}\n\n"""
    text = text.replace(evidence_marker, copy_readback + evidence_marker, 1)

    checkpoint = "          Write-Host 'P0G_PACKAGED_ACTION_RESULT_ACCESSIBILITY=PASS'\n"
    assert checkpoint in text, "package checkpoint insertion point not found"
    text = text.replace(
        checkpoint,
        checkpoint
        + "          Write-Host 'P0_DOCUMENT_TEXT_SELECTION_COPY=PASS'\n"
        + "          Write-Host 'MOVE_INPUT_NATIVE_COPY=PASS'\n",
        1,
    )
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
    patched = patch_workflow(original, previous)

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        workflow_file = td_path / "package.yml"
        workflow_file.write_text(patched, encoding="utf-8")
        index = td_path / "index"
        index_env = dict(os.environ)
        index_env["GIT_INDEX_FILE"] = str(index)
        git("read-tree", product, env=index_env)
        blob = git("hash-object", "-w", str(workflow_file))
        git(
            "update-index",
            "--add",
            "--cacheinfo",
            f"100644,{blob},{WORKFLOW_PATH}",
            env=index_env,
        )
        tree = git("write-tree", env=index_env)

    message = (
        "CI: reconverge same Windows package lineage for P0 document copy\n\n"
        f"First parent exact current Full Product {product}.\n"
        f"Second parent prior SAME WIP=1 package {previous}.\n"
        "Add source copy regression and packaged Windows static TextPattern selection -> native Ctrl+C -> clipboard proof, while re-proving Move Input native Ctrl+A/Ctrl+C.\n\n"
        "HUMAN_TESTED=NO\nNVDA_VERIFIED=NO\nFINAL_WINDOWS_ZIP=NO_PENDING_RUN\n"
    )
    commit = git("commit-tree", tree, "-p", product, "-p", previous, input_text=message)

    changed = git("diff", "--name-only", product, commit)
    if changed != WORKFLOW_PATH:
        raise RuntimeError(f"unexpected package delta: {changed!r}")
    git("diff", "--check", product, commit)

    git("fetch", "--no-tags", "origin", PRODUCT_BRANCH, PACKAGE_BRANCH)
    if git("rev-parse", f"origin/{PRODUCT_BRANCH}") != product:
        raise RuntimeError("Full Product advanced during package reconvergence")
    if git("rev-parse", f"origin/{PACKAGE_BRANCH}") != previous:
        raise RuntimeError("package lineage advanced during package reconvergence")

    git("push", "origin", f"{commit}:refs/heads/{PACKAGE_BRANCH}")
    print(f"RECONVERGED_PACKAGE_HEAD={commit}")
    print(f"PRODUCT_PARENT={product}")
    print(f"PREVIOUS_PACKAGE={previous}")


if __name__ == "__main__":
    main()
