$ErrorActionPreference = "Stop"
$root = (Resolve-Path ".").Path
$demo = Join-Path $root ("artifacts\acceptance-demo-" + [guid]::NewGuid().ToString("N"))
Copy-Item -LiteralPath (Join-Path $root "examples\demo_project") -Destination $demo -Recurse

$models = python -m delphiopt models | Out-String
if ($LASTEXITCODE -ne 0) { throw "models failed" }
$experts = python -m delphiopt experts | Out-String
if ($LASTEXITCODE -ne 0) { throw "experts failed" }

$optRaw = python -m delphiopt optimize $demo --mode delphi --max-rounds 3 | Out-String
if ($LASTEXITCODE -ne 0) { throw "optimize failed: $optRaw" }
$opt = $optRaw | ConvertFrom-Json
$runs = Join-Path $demo ".delphiopt\runs"

$inspect = python -m delphiopt inspect $opt.run_id --runs-root $runs | Out-String
if ($LASTEXITCODE -ne 0) { throw "inspect failed" }
$reportOut = (python -m delphiopt report $opt.run_id --runs-root $runs | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "report failed" }
$benchRaw = python -m delphiopt benchmark $demo | Out-String
if ($LASTEXITCODE -ne 0) { throw "benchmark failed" }
$bench = $benchRaw | ConvertFrom-Json
$reproRaw = python -m delphiopt reproduce $opt.run_id --runs-root $runs | Out-String
if ($LASTEXITCODE -ne 0) { throw "reproduce failed: $reproRaw" }
$repro = $reproRaw | ConvertFrom-Json

$events = @($inspect -split "`r?`n" | Where-Object { $_ -match "^\{" })
$result = [ordered]@{
    project = $demo
    models_command = ($models -match "mock")
    experts_command = ($experts -match "algorithm")
    optimize_exit = 0
    status = $opt.status
    correctness = $opt.correctness
    speedup = $opt.speedup
    run_id = $opt.run_id
    llm_calls = $opt.llm_calls
    benchmark_runs = $opt.benchmark_runs
    tool_calls = $opt.tool_calls
    total_tokens = $opt.total_tokens
    model_calls_recorded = ($opt.models_used.psobject.Properties.Value | Measure-Object -Sum).Sum
    disagreement_rounds = $opt.round_disagreements.Count
    reputation_experts = @($opt.expert_reliability.psobject.Properties).Count
    calibration_error = $opt.calibration_error
    prediction_error = $opt.prediction_error
    trace_events = $events.Count
    inspect_has_agent_call = ($inspect -match "agent_call")
    report_exit = 0
    report_exists = (Test-Path -LiteralPath $reportOut)
    benchmark_exit = 0
    benchmark_correctness = $bench.correctness
    reproduce_exit = 0
    reproduce_status = $repro.status
    trace_exists = (Test-Path (Join-Path $runs "$($opt.run_id).jsonl"))
    sqlite_exists = (Test-Path (Join-Path $runs "traces.sqlite3"))
    run_config_exists = (Test-Path (Join-Path $runs "$($opt.run_id).run_config.yaml"))
    summary_exists = (Test-Path (Join-Path $runs "$($opt.run_id).summary.json"))
    reputation_exists = (Test-Path (Join-Path $demo ".delphiopt\reputation.json"))
    patch_count = @(Get-ChildItem (Join-Path $runs "$($opt.run_id)\patches") -File).Count
}

$path = Join-Path $root "artifacts\runtime_acceptance.json"
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $path -Encoding utf8
$result | ConvertTo-Json -Depth 5

if ($opt.status -ne "accepted" -or -not $opt.correctness -or
    -not $result.report_exists -or -not $result.trace_exists -or
    -not $result.sqlite_exists -or -not $result.run_config_exists -or
    -not $result.summary_exists -or -not $result.reputation_exists -or
    $result.patch_count -lt 1 -or $result.model_calls_recorded -ne $opt.llm_calls -or
    $result.disagreement_rounds -ne $opt.rounds -or $result.reputation_experts -lt 1) {
    throw "runtime acceptance invariant failed"
}
