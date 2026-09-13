param(
    [Parameter(Mandatory = $true)]
    [string]$CandidateExePath
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$script:appPid = $null

function Fail([string]$message) { throw "WordDeck packaged Course/Story UIA FAIL: $message" }

function Invoke-WinApp([string[]]$arguments, [switch]$Json) {
    $output = & winapp @arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Fail "winapp $($arguments -join ' ') exited with code $exitCode. Output: $($output -join ' ')"
    }
    if ($Json) {
        try { return ($output | Out-String | ConvertFrom-Json) }
        catch { Fail "winapp returned invalid JSON for: $($arguments -join ' ')" }
    }
    return $output
}

function Wait-For([string]$selector, [int]$timeoutMs = 10000) {
    Invoke-WinApp @('ui','wait-for',$selector,'-a',[string]$script:appPid,'--timeout',[string]$timeoutMs) | Out-Null
}

function Wait-Gone([string]$selector, [int]$timeoutMs = 7000) {
    Invoke-WinApp @('ui','wait-for',$selector,'-a',[string]$script:appPid,'--gone','--timeout',[string]$timeoutMs) | Out-Null
}

function Get-Value([string]$selector) {
    $result = Invoke-WinApp @('ui','get-value',$selector,'-a',[string]$script:appPid,'--json') -Json
    return [string]$result.text
}

function Focus([string]$selector) {
    Invoke-WinApp @('ui','focus',$selector,'-a',[string]$script:appPid) | Out-Null
}

function Get-FocusedName {
    $result = Invoke-WinApp @('ui','get-focused','-a',[string]$script:appPid,'--json') -Json
    if (-not $result.hasFocus -or $null -eq $result.element) { return '' }
    return [string]$result.element.name
}

function Assert-Focus([string]$expected, [string]$context) {
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    do {
        $actual = Get-FocusedName
        if ($actual -eq $expected) { return }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail "$context expected focus '$expected', actual '$actual'."
}

function Send-Keys([string]$keys, [string]$target = '') {
    $modalKey = $keys -ieq 'enter' -or $keys -ieq 'esc'
    $transport = if ($keys -ieq 'alt+f4') {
        'post-message'
    } elseif ($keys.Contains('+') -or ($modalKey -and -not [string]::IsNullOrWhiteSpace($target))) {
        'send-input'
    } else {
        'post-message'
    }

    $arguments = @('ui','send-keys',$keys,'-a',[string]$script:appPid)
    if (-not [string]::IsNullOrWhiteSpace($target)) {
        $arguments += @('--target',$target)
    }
    $arguments += @('--via',$transport)
    Invoke-WinApp $arguments | Out-Null
    Start-Sleep -Milliseconds 250
}

function Send-MenuKey([string]$keys) {
    Invoke-WinApp @('ui','send-keys',$keys,'-a',[string]$script:appPid,'--via','send-input') | Out-Null
    Start-Sleep -Milliseconds 250
}

function Type-Text([string]$text, [string]$target) {
    Invoke-WinApp @('ui','send-keys',$text,'-a',[string]$script:appPid,'--target',$target,'--via','send-input','--verbatim') | Out-Null
    Start-Sleep -Milliseconds 250
}

function Wait-ValueContains([string]$selector, [string]$fragment, [int]$timeoutMs = 7000) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($timeoutMs)
    $last = ''
    do {
        $last = Get-Value $selector
        if ($last.Contains($fragment, [StringComparison]::Ordinal)) { return $last }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail "$selector did not contain '$fragment' within ${timeoutMs}ms. Last value: $last"
}

function Get-PracticeAttemptCount {
    $status = Get-Value 'Результат і прогрес курсу'
    $match = [regex]::Match($status, 'practice attempts\s+(\d+)', [Text.RegularExpressions.RegexOptions]::CultureInvariant)
    if (-not $match.Success) { Fail "Course status does not expose learner practice-attempt count: $status" }
    return [int]$match.Groups[1].Value
}

function Start-Candidate([string]$exePath) {
    $process = Start-Process -FilePath $exePath -WorkingDirectory (Split-Path -Parent $exePath) -PassThru
    if ($null -eq $process -or $process.Id -le 0) { Fail 'Packaged WordDeck launch did not return a valid process ID.' }
    $script:appPid = [int]$process.Id
    Wait-For 'Current English word' 30000
    Focus 'Current English word'
    Assert-Focus 'Current English word' 'packaged startup'
    Write-Host "WordDeck packaged Course/Story UIA target PID=$script:appPid EXE=$exePath"
}

function Wait-ProcessExit([int]$processId, [int]$timeoutMs = 10000) {
    $deadline = [DateTime]::UtcNow.AddMilliseconds($timeoutMs)
    do {
        if ($null -eq (Get-Process -Id $processId -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail "WordDeck process $processId did not exit normally within ${timeoutMs}ms."
}

function Open-GovernedCourseByKeyboard {
    Focus 'Current English word'
    Assert-Focus 'Current English word' 'before Tools menu'

    # TrainingEntryPoints installs the standard Tools menu in this order:
    # Spelling, Sentence, Listening, shortcut settings, Story/Course. Home makes
    # the starting point deterministic; four Down presses then reach Course.
    Send-Keys 'alt+t' 'Current English word'
    Send-MenuKey 'home'
    for ($i = 0; $i -lt 4; $i++) { Send-MenuKey 'down' }
    Send-MenuKey 'enter'

    Wait-For 'Розділ курсу' 10000
    foreach ($required in @(
        'Текст навчального матеріалу',
        'Позначити поточний навчальний матеріал прочитаним',
        'Вправа на розуміння',
        'Умова вправи на розуміння',
        'Відповідь на вправу на розуміння',
        'Перевірити відповідь',
        'Результат і прогрес курсу')) {
        Wait-For $required 7000
    }
}

if ($env:WORDDECK_ALLOW_MUTATING_UIA_STATE -ne '1') {
    Fail 'Refusing to mutate learner Course/Story state outside an explicit disposable test profile. Set WORDDECK_ALLOW_MUTATING_UIA_STATE=1 only in an isolated CI/test user profile.'
}

try {
    $candidateExe = (Resolve-Path -LiteralPath $CandidateExePath).Path
    Start-Candidate $candidateExe
    Open-GovernedCourseByKeyboard

    # Verify semantic keyboard traversal in the real WinForms course surface.
    Focus 'Текст навчального матеріалу'
    Assert-Focus 'Текст навчального матеріалу' 'course material initial focus'
    Send-Keys 'tab' 'Текст навчального матеріалу'
    Assert-Focus 'Позначити поточний навчальний матеріал прочитаним' 'course Tab order to mark-read action'
    Send-Keys 'shift+tab' 'Позначити поточний навчальний матеріал прочитаним'
    Assert-Focus 'Текст навчального матеріалу' 'course Shift+Tab return'

    $beforePractice = Get-PracticeAttemptCount

    # Blank Enter is deliberately fail-closed: no learner evidence may be added.
    Focus 'Відповідь на вправу на розуміння'
    Assert-Focus 'Відповідь на вправу на розуміння' 'course comprehension answer'
    Send-Keys 'enter' 'Відповідь на вправу на розуміння'
    $blankStatus = Wait-ValueContains 'Результат і прогрес курсу' 'Введіть відповідь.'
    Assert-Focus 'Відповідь на вправу на розуміння' 'course blank Enter guard'
    $afterBlankPractice = Get-PracticeAttemptCount
    if ($afterBlankPractice -ne $beforePractice) {
        Fail "Blank Course/Story Enter changed learner practice evidence: before=$beforePractice after=$afterBlankPractice."
    }

    # The governed built-in M07 first bounded task accepts "straight". Type via
    # actual keyboard injection, submit with Enter, and verify learner-facing
    # feedback plus one persisted practice attempt without claiming mastery.
    Type-Text 'straight' 'Відповідь на вправу на розуміння'
    if ((Get-Value 'Відповідь на вправу на розуміння') -ne 'straight') {
        Fail 'Keyboard text entry did not reach the governed M07 comprehension answer field.'
    }
    Send-Keys 'enter' 'Відповідь на вправу на розуміння'
    $acceptedStatus = Wait-ValueContains 'Результат і прогрес курсу' 'Правильно.'
    if (-not $acceptedStatus.Contains('Mastery не змінено.', [StringComparison]::Ordinal)) {
        Fail "Accepted Course/Story feedback lost the truthful no-mastery boundary: $acceptedStatus"
    }
    $expectedPractice = $beforePractice + 1
    $afterAcceptedPractice = Get-PracticeAttemptCount
    if ($afterAcceptedPractice -ne $expectedPractice) {
        Fail "Accepted Course/Story attempt was not recorded exactly once: expected=$expectedPractice actual=$afterAcceptedPractice."
    }

    # Close the course and the whole packaged app normally, then relaunch the same
    # EXE and prove the learner evidence survived the real restart boundary.
    Send-Keys 'alt+f4'
    Wait-Gone 'Розділ курсу' 7000
    Wait-For 'Current English word' 5000

    $firstPid = [int]$script:appPid
    Focus 'Current English word'
    Send-Keys 'alt+f4' 'Current English word'
    Wait-ProcessExit $firstPid 10000
    $script:appPid = $null

    Start-Candidate $candidateExe
    Open-GovernedCourseByKeyboard
    $reopenedPractice = Get-PracticeAttemptCount
    if ($reopenedPractice -ne $expectedPractice) {
        Fail "Course/Story learner evidence did not survive packaged app restart: expected=$expectedPractice actual=$reopenedPractice."
    }

    Send-Keys 'alt+f4'
    Wait-Gone 'Розділ курсу' 7000
    Wait-For 'Current English word' 5000
    $secondPid = [int]$script:appPid
    Focus 'Current English word'
    Send-Keys 'alt+f4' 'Current English word'
    Wait-ProcessExit $secondPid 10000
    $script:appPid = $null

    Write-Host "WordDeck packaged Course/Story UIA PASS: keyboard menu route, semantic Tab order, blank-submit fail-closed behavior, governed M07 feedback/practice evidence, truthful no-mastery boundary, normal close/reopen and persisted learner state verified. practice_attempts=$expectedPractice"
}
finally {
    if ($null -ne $script:appPid -and $script:appPid -gt 0) {
        try { Stop-Process -Id $script:appPid -Force -ErrorAction SilentlyContinue } catch { }
    }
}
