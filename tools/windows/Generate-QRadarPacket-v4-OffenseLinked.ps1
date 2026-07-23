# Generate-QRadarPacket-v3-OffenseLinked.ps1
#
# Purpose:
# - Pull QRadar offense metadata
# - Pull QRadar offense notes
# - Pull offense-linked Ariel evidence using INOFFENSE(offense_id)
# - Generate improved Rulebot packet with evidence distributions
#
# Key change from v1:
# - Primary evidence now uses WHERE INOFFENSE(<offense_id>)
# - No contextual logsource/time-window sample is used as primary evidence

$ErrorActionPreference = "Stop"
<#
Write-Host "DEBUG: Script started" -ForegroundColor Cyan
Write-Host "RUNNING SCRIPT PATH: $PSCommandPath" -ForegroundColor Red
Write-Host "RUNNING SCRIPT VERSION: V4-STAGED-DEBUG-20260723-01" -ForegroundColor Red
#>
# ----------------------------
# Config
# ----------------------------

$PROJECT_ROOT = (Resolve-Path (Join-Path -Path $PSScriptRoot -ChildPath "..\..")).Path

$API_VERSION = "16.0"

$Instances = @{
    "BH" = @{
        BaseUrl = "https://192.168.51.122"
        TokenEnvCandidates = @(
            "QRADAR_BH_SEC_TOKEN",
            "QRADAR_TOKEN"
        )
    }
    "KSA" = @{
        BaseUrl = "https://YOUR-KSA-QRADAR-HOST"
        TokenEnvCandidates = @(
            "QRADAR_KSA_SEC_TOKEN"
            "QRADAR_TOKEN_KSA",
            "QRADAR_TOKEN"
        )
    }
}

$LOOKBACK_DAYS = 30
$MAX_WAIT_SECONDS = 180
$SAMPLE_EVENT_LIMIT = 5
$RESULT_LIMIT = 20
$AQL_TIME_BUFFER_MINUTES = 180  # 3-hour buffer either side of QRadar offense timestamps. Validated against offense 462687: captures full 847 linked events with much faster searches.
$SKIP_CERT_VALIDATION = $true
$VERBOSE_SEARCH_LOG = $false

# ----------------------------
# Helpers
# ----------------------------
function Convert-MsEpochToAqlTime {
    param($Ms)

    if (-not $Ms) {
        return $null
    }

    $epoch = [System.DateTimeOffset]::FromUnixTimeMilliseconds([int64]$Ms)
    return $epoch.UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss")
}

function Get-OffenseAqlTimeBounds {
    param(
        $Offense,
        [int]$BufferMinutes = 360
    )

    $startMs = $Offense.start_time
    if (-not $startMs) {
        $startMs = $Offense.first_persisted_time
    }

    $stopMs = $Offense.close_time
    if (-not $stopMs) {
        $stopMs = $Offense.last_updated_time
    }
    if (-not $stopMs) {
        $stopMs = $Offense.last_persisted_time
    }

    if (-not $startMs -or -not $stopMs) {
        return @{
            Start = $null
            Stop = $null
        }
    }

    $start = [System.DateTimeOffset]::FromUnixTimeMilliseconds([int64]$startMs).UtcDateTime.AddMinutes(-1 * $BufferMinutes)
    $stop = [System.DateTimeOffset]::FromUnixTimeMilliseconds([int64]$stopMs).UtcDateTime.AddMinutes($BufferMinutes)

    return @{
        Start = $start.ToString("yyyy-MM-dd HH:mm:ss")
        Stop = $stop.ToString("yyyy-MM-dd HH:mm:ss")
    }
}

function Get-AqlTimeClause {
    param(
        [string]$Start,
        [string]$Stop
    )

    if (-not [string]::IsNullOrWhiteSpace($Start) -and -not [string]::IsNullOrWhiteSpace($Stop)) {
        return "START '$Start' STOP '$Stop'"
    }

    return "LAST $LOOKBACK_DAYS DAYS"
}

function Get-OffenseLogSourceFilter {
    param($Offense)

    $ids = @()

    if ($Offense.log_sources) {
        foreach ($logSource in $Offense.log_sources) {
            if ($logSource.id) {
                $ids += [string]$logSource.id
            }
        }
    }

    if ($ids.Count -eq 0) {
        return ""
    }

    return " AND logsourceid IN ($($ids -join ','))"
}

function Read-Choice {
    param(
        [string]$Prompt,
        [string[]]$Options
    )

    while ($true) {
        Write-Host ""
        Write-Host $Prompt

        for ($i = 0; $i -lt $Options.Count; $i++) {
            Write-Host "[$($i + 1)] $($Options[$i])"
        }

        $choice = Read-Host "Select option number"

        if ($choice -match '^\d+$') {
            $idx = [int]$choice - 1

            if ($idx -ge 0 -and $idx -lt $Options.Count) {
                return $Options[$idx]
            }
        }

        Write-Host "Invalid selection." -ForegroundColor Yellow
    }
}

function Get-QradarToken {
    param(
        [string[]]$Candidates
    )

    foreach ($name in $Candidates) {
        $value = [System.Environment]::GetEnvironmentVariable($name, [System.EnvironmentVariableTarget]::Process)

        if ([string]::IsNullOrWhiteSpace($value)) {
            $value = [System.Environment]::GetEnvironmentVariable($name, [System.EnvironmentVariableTarget]::User)
        }

        if ([string]::IsNullOrWhiteSpace($value)) {
            $value = [System.Environment]::GetEnvironmentVariable($name, [System.EnvironmentVariableTarget]::Machine)
        }

        if (-not [string]::IsNullOrWhiteSpace($value)) {
            Write-Host "Using QRadar token from environment variable: $name" -ForegroundColor DarkGreen
            return $value
        }
    }

    Write-Host ""
    Write-Host "No QRadar token found in expected environment variables." -ForegroundColor Yellow
    Write-Host "Expected one of: $($Candidates -join ', ')" -ForegroundColor Yellow

    $secure = Read-Host "Paste QRadar token for this run" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)

    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }

    if ([string]::IsNullOrWhiteSpace($plain)) {
        throw "QRadar token is empty."
    }

    return $plain
}

function Convert-MsEpochToUtc {
    param($Ms)

    if ($null -eq $Ms -or [string]::IsNullOrWhiteSpace("$Ms")) {
        return ""
    }

    try {
        return [System.DateTimeOffset]::FromUnixTimeMilliseconds([int64]$Ms).UtcDateTime.ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    }
    catch {
        return ""
    }
}

function Compact-Json {
    param(
        $Object,
        [int]$Depth = 30
    )

    if ($null -eq $Object) {
        return ""
    }

    return ($Object | ConvertTo-Json -Depth $Depth -Compress)
}

function Compact-JsonArray {
    param(
        $Object,
        [int]$Depth = 30
    )

    if ($null -eq $Object) {
        return "[]"
    }

    return (@($Object) | ConvertTo-Json -Depth $Depth -Compress)
}

function Get-EventsArray {
    param($Result)

    if ($null -eq $Result) {
        return @()
    }

    if ($Result.events) {
        return @($Result.events)
    }

    return @()
}

function Get-FirstValue {
    param(
        $List,
        [string]$FieldName
    )

    $items = @($List)

    if ($items.Count -gt 0 -and $null -ne $items[0]) {
        return $items[0].$FieldName
    }

    return ""
}

function Get-TopDistributionFromCombined {
    param(
        $CombinedDistribution,
        [string]$FieldName,
        [int]$Limit = 20
    )

    $groups = @{}

    foreach ($item in @($CombinedDistribution)) {
        if ($null -eq $item) {
            continue
        }

        $value = $item.$FieldName

        if ($null -eq $value) {
            $key = "__NULL__"
        }
        else {
            $key = [string]$value
        }

        $count = 0

        if ($null -ne $item.event_count) {
            $count = [double]$item.event_count
        }

        if (-not $groups.ContainsKey($key)) {
            $groups[$key] = @{
                value = $value
                count = 0
            }
        }

        $groups[$key].count += $count
    }

    $results = @()

    foreach ($key in $groups.Keys) {
        $obj = [ordered]@{}
        $obj[$FieldName] = $groups[$key].value
        $obj["event_count"] = $groups[$key].count

        $results += [pscustomobject]$obj
    }

    return @(
        $results |
            Sort-Object -Property event_count -Descending |
            Select-Object -First $Limit
    )
}

function Get-QradarAnalyticsRuleMetadata {
    param(
        $BaseUrl,
        $Token,
        $RuleId
    )

    try {
        $result = Invoke-Qradar `
            -BaseUrl $BaseUrl `
            -Token $Token `
            -Method "GET" `
            -Path "/api/analytics/rules/$RuleId"

        return $result
    }
    catch {
        Write-Host "WARNING: Could not retrieve QRadar analytics rule metadata for rule ID $RuleId" -ForegroundColor Yellow
        Write-Host $_.Exception.Message -ForegroundColor Yellow
        return $null
    }
}

function Invoke-Qradar {
    param(
        [string]$BaseUrl,
        [string]$Token,
        [string]$Method,
        [string]$Path,
        $Body = $null,
        [string]$RangeHeader = $null
    )

    if ([string]::IsNullOrWhiteSpace($Token)) {
        throw "QRadar token is empty before calling QRadar."
    }

    $url = "$BaseUrl$Path"

    $args = @()

    if ($SKIP_CERT_VALIDATION) {
        $args += "-k"
    }

    $args += "-sS"
    $args += "-X"
    $args += $Method

    $args += "-H"
    $args += "SEC: $Token"

    $args += "-H"
    $args += "Version: $API_VERSION"

    $args += "-H"
    $args += "Accept: application/json"

    if (-not [string]::IsNullOrWhiteSpace($RangeHeader)) {
        $args += "-H"
        $args += "Range: $RangeHeader"
    }

    if ($null -ne $Body) {
        $jsonBody = $Body | ConvertTo-Json -Depth 30 -Compress

        $args += "-H"
        $args += "Content-Type: application/json"

        $args += "-d"
        $args += $jsonBody
    }

    $args += $url

    $raw = & curl.exe @args

    if ($LASTEXITCODE -ne 0) {
        throw "curl.exe failed with exit code $LASTEXITCODE for $Method $url"
    }

    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }

    try {
        return $raw | ConvertFrom-Json
    }
    catch {
        Write-Host ""
        Write-Host "Failed to parse QRadar response as JSON." -ForegroundColor Red
        Write-Host "URL: $url" -ForegroundColor Red
        Write-Host "Raw response:" -ForegroundColor Red
        Write-Host $raw
        throw
    }
}

function Invoke-ArielAql {
    param(
        [string]$BaseUrl,
        [string]$Token,
        [string]$Aql
    )

    Write-Host ""
    Write-Host "Submitting Ariel AQL:" -ForegroundColor Cyan
    Write-Host $Aql -ForegroundColor DarkCyan

    $encodedAql = [System.Uri]::EscapeDataString($Aql)
    $path = "/api/ariel/searches?query_expression=$encodedAql"

    $response = Invoke-Qradar `
        -BaseUrl $BaseUrl `
        -Token $Token `
        -Method "POST" `
        -Path $path

    if ($response -and $response.http_response) {
        throw "QRadar API error during Ariel submit: $(Compact-Json $response)"
    }

    return $response
}

function Get-QradarSearchId {
    param($SearchResponse)

    if ($null -eq $SearchResponse) {
        throw "Ariel search response was null."
    }

    $props = $SearchResponse.PSObject.Properties.Name

    if ($props -contains "search_id" -and -not [string]::IsNullOrWhiteSpace("$($SearchResponse.search_id)")) {
        return [string]$SearchResponse.search_id
    }

    if ($props -contains "cursor_id" -and -not [string]::IsNullOrWhiteSpace("$($SearchResponse.cursor_id)")) {
        return [string]$SearchResponse.cursor_id
    }

    Write-Host ""
    Write-Host "Unexpected Ariel submit response:" -ForegroundColor Yellow
    Write-Host ($SearchResponse | ConvertTo-Json -Depth 30)

    throw "Ariel search did not return search_id or cursor_id. Properties returned: $($props -join ', ')"
}

function Wait-QradarSearch {
    param(
        [string]$BaseUrl,
        [string]$Token,
        [string]$SearchId,
        [int]$MaxWaitSeconds = 180
    )

    $deadline = (Get-Date).AddSeconds($MaxWaitSeconds)
    $startTime = Get-Date

    while ((Get-Date) -lt $deadline) {
        $status = Invoke-Qradar `
            -BaseUrl $BaseUrl `
            -Token $Token `
            -Method "GET" `
            -Path "/api/ariel/searches/$SearchId"

        $state = "$($status.status)".ToUpperInvariant()
        $elapsed = ((Get-Date) - $startTime).TotalSeconds
        $elapsedRounded = [math]::Round($elapsed, 0)

        Write-Host "Ariel search status: $state - elapsed ${elapsedRounded}s" -ForegroundColor DarkYellow

        if ($state -eq "COMPLETED" -or $status.completed -eq $true) {
            return $status
        }

        if ($state -eq "ERROR" -or $state -eq "CANCELED") {
            throw "Ariel search $SearchId failed with status $state. Details: $(Compact-Json $status)"
        }

        Start-Sleep -Seconds 2
    }

    throw "Ariel search $SearchId did not complete within $MaxWaitSeconds seconds."
}


function Get-ArielResults {
    param(
        [string]$BaseUrl,
        [string]$Token,
        [string]$SearchId,
        [int]$Limit = 20
    )

    $rangeHeader = "items=0-$($Limit - 1)"

    return Invoke-Qradar `
        -BaseUrl $BaseUrl `
        -Token $Token `
        -Method "GET" `
        -Path "/api/ariel/searches/$SearchId/results" `
        -RangeHeader $rangeHeader
}

function Invoke-OffenseLinkedAql {
    param(
        [string]$BaseUrl,
        [string]$Token,
        [string]$Aql,
        [int]$Limit = 20,
        [int]$MaxWaitSeconds = 180
    )

    $searchResponse = Invoke-ArielAql `
        -BaseUrl $BaseUrl `
        -Token $Token `
        -Aql $Aql

    $searchId = Get-QradarSearchId -SearchResponse $searchResponse

    $status = Wait-QradarSearch `
        -BaseUrl $BaseUrl `
        -Token $Token `
        -SearchId $searchId `
        -MaxWaitSeconds $MaxWaitSeconds

    $results = Get-ArielResults `
        -BaseUrl $BaseUrl `
        -Token $Token `
        -SearchId $searchId `
        -Limit $Limit

    return @{
        search_id = $searchId
        status = $status
        results = $results
    }
}

function Invoke-StagedAql {
    param(
        [string]$BaseUrl,
        [string]$Token,
        [string]$Label,
        [string]$Aql,
        [int]$Limit = 20,
        [int]$MaxWaitSeconds = 180
    )

    Write-Host ""
    Write-Host "Starting Ariel stage: $Label" -ForegroundColor Cyan
    Write-Host $Aql -ForegroundColor DarkGray

    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    try {
        $result = Invoke-OffenseLinkedAql `
            -BaseUrl $BaseUrl `
            -Token $Token `
            -Aql $Aql `
            -Limit $Limit `
            -MaxWaitSeconds $MaxWaitSeconds

        $events = Get-EventsArray $result.results

        $sw.Stop()
        $duration =[math]::Round($sw.Elapsed.TotalSeconds, 2)

        Write-Host "Completed Ariel stage: $Label ($($events.Count) rows, ${duration}s)" -ForegroundColor Green

        return @{
            label = $Label
            status = "completed"
            duration_seconds = $duration
            events = @($events)
            error = $null
        }
    }
    catch {
        $sw.Stop()
        $duration = [math]::Round($sw.Elapsed.TotalSeconds, 2)

        Write-Host "Failed Ariel stage: $Label after ${duration}s" -ForegroundColor Yellow
        Write-Host $_.Exception.Message -ForegroundColor Yellow

        return @{
            label = $Label
            status = "failed"
            duration_seconds = $duration
            events = @()
            error = $_.Exception.Message
        }
    }
}

function Get-StageEvents {
    param($Stage)

    if ($null -eq $Stage) {
        return @()
    }

    if ($Stage -is [hashtable] -and $Stage.ContainsKey("events")) {
        return @($Stage["events"])
    }

    if ($Stage.PSObject.Properties.Name -contains "events") {
        return @($Stage.events)
    }

    if ($Stage.PSObject.Properties.Name -contains "Events") {
        return @($Stage.Events)
    }

    return @()
}

function Invoke-DistributionQuery {
    param(
        [string]$BaseUrl,
        [string]$Token,
        [string]$OffenseId,
        [string]$FieldName,
        [string]$GroupByClause = $null
    )

    if ([string]::IsNullOrWhiteSpace($GroupByClause)) {
        $GroupByClause = $FieldName
    }

    $aql = @"
SELECT
    $FieldName,
    COUNT(*) AS event_count
FROM events
WHERE INOFFENSE($OffenseId)
GROUP BY $GroupByClause
LAST $LOOKBACK_DAYS DAYS
"@

    $result = Invoke-OffenseLinkedAql `
        -BaseUrl $BaseUrl `
        -Token $Token `
        -Aql $aql `
        -Limit $RESULT_LIMIT `
        -MaxWaitSeconds $MAX_WAIT_SECONDS

    return Get-EventsArray $result.results
}

function Resolve-ExportedRuleBinding {
    param(
        $LinkedRuleIdentifier,
        $Identifier,
        $RuleName
    )

    $searchValues = @()

    if ($LinkedRuleIdentifier) {
        $searchValues += [string]$LinkedRuleIdentifier
    }

    if ($Identifier) {
        $searchValues += [string]$Identifier
    }

    $rulesRoot = Join-Path -Path $PROJECT_ROOT -ChildPath "data\rules\current"
    $buildingBlocksRoot = Join-Path -Path $PROJECT_ROOT -ChildPath "data\building_blocks\current"

    $roots = @(
        $rulesRoot
        $buildingBlocksRoot
    )

    Write-Host "Rule binding search roots:" -ForegroundColor DarkYellow
    $roots | ForEach-Object { Write-Host " - $_" -ForegroundColor DarkYellow }

    foreach ($root in $roots) {
        if (-not (Test-Path $root)) {
            continue
        }

        $files = Get-ChildItem $root -Recurse -Filter "*.json"

        foreach ($file in $files) {
            try {
                $obj = Get-Content $file.FullName -Raw | ConvertFrom-Json
            }
            catch {
                continue
            }

            foreach ($value in $searchValues) {
                if ($obj.uuid -eq $value) {
                    return @{
                        exported_rule_doc_id = $file.BaseName
                        exported_rule_name = $obj.rule_name
                        exported_uuid = $obj.uuid
                        exported_object_type = $obj.object_type
                        exported_file_path = $file.FullName
                        binding_method = "linked_rule_identifier_to_exported_uuid"
                    }
                }
            }

            if ($RuleName -and $obj.rule_name -eq $RuleName) {
                return @{
                    exported_rule_doc_id = $file.BaseName
                    exported_rule_name = $obj.rule_name
                    exported_uuid = $obj.uuid
                    exported_object_type = $obj.object_type
                    exported_file_path = $file.FullName
                    binding_method = "rule_name_exact_match"
                }
            }
        }
    }

    return $null
}

# ----------------------------
# Main
# ----------------------------

Write-Host ""
Write-Host "Starting Rulebot Packet Generator v2 - Offense Linked Evidence" -ForegroundColor Green

$instanceKey = Read-Choice "Select QRadar instance:" @("BH", "KSA")
$inst = $Instances[$instanceKey]

$token = Get-QradarToken -Candidates $inst.TokenEnvCandidates

Write-Host ""
Write-Host "Using QRadar BaseUrl: $($inst.BaseUrl)" -ForegroundColor DarkGreen

$offenseId = Read-Host "Enter Offense ID"

Write-Host "DEEP mode may run expensive multi-field Ariel grouping. Use only when needed." -ForegroundColor Yellow
$evidenceModeChoice = Read-Choice "Select evidence collection mode:" @("FAST", "DEEP")

Write-Host ""
Write-Host "Selected evidence mode: $evidenceModeChoice" -ForegroundColor Green

Write-Host ""
Write-Host "Pulling QRadar offense metadata..." -ForegroundColor Cyan

$offense = Invoke-Qradar `
    -BaseUrl $inst.BaseUrl `
    -Token $token `
    -Method "GET" `
    -Path "/api/siem/offenses/$offenseId"

$timeBounds = Get-OffenseAqlTimeBounds -Offense $offense -BufferMinutes $AQL_TIME_BUFFER_MINUTES
$aqlTimeClause = Get-AqlTimeClause -Start $timeBounds.Start -Stop $timeBounds.Stop
$extraWhere = Get-OffenseLogSourceFilter -Offense $offense

Write-Host ""
Write-Host "Using AQL time bounds: $aqlTimeClause" -ForegroundColor DarkGreen
Write-Host "Using extra WHERE filter: $($extraWhere.Trim())" -ForegroundColor DarkGreen

if ($offense -and $offense.http_response) {
    throw "QRadar offense API error: $(Compact-Json $offense)"
}

Write-Host "Pulling QRadar offense notes..." -ForegroundColor Cyan

$notes = @()

try {
    $notesResponse = Invoke-Qradar `
        -BaseUrl $inst.BaseUrl `
        -Token $token `
        -Method "GET" `
        -Path "/api/siem/offenses/$offenseId/notes" `
        -RangeHeader "items=0-4"

    if ($notesResponse) {
        $notes = @($notesResponse)
    }
}
catch {
    Write-Host "WARNING: Could not retrieve offense notes." -ForegroundColor Yellow
    Write-Host $_.Exception.Message -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Running offense-linked Ariel evidence queries..." -ForegroundColor Cyan

# FAST mode core query:
# Staged queries are light search loads, query gives us source/destination/QID/logsource/category/username combinations.
$collectionStages = @()

$topSourceIps = @()
$topDestinationIps = @()
$topQids = @()
$topUsernames = @()
$topLogSources = @()
$topCategories = @()

$combinedDistribution = @()
$qidLogSourceCategory = @()

$aqlTopQids = @"
SELECT
    qid,
    COUNT(*) AS event_count
FROM events
WHERE INOFFENSE($offenseId)$extraWhere
GROUP BY qid
ORDER BY event_count DESC
$aqlTimeClause
"@

$topQidsStage = Invoke-StagedAql `
    -BaseUrl $inst.BaseUrl `
    -Token $token `
    -Label "top_qids" `
    -Aql $aqlTopQids `
    -Limit $RESULT_LIMIT `
    -MaxWaitSeconds $MAX_WAIT_SECONDS

$collectionStages += $topQidsStage
$topQids = Get-StageEvents -Stage $topQidsStage
<#
Write-Host "DEBUG topQidsStage raw: $(Compact-Json $topQidsStage)" -ForegroundColor Magenta
Write-Host "DEBUG topQids count immediately after assignment: $($topQids.Count)" -ForegroundColor Magenta
Write-Host "DEBUG topQids JSON: $(Compact-JsonArray $topQids)" -ForegroundColor Magenta
#>


$aqlTopSourceIps = @"
SELECT
    sourceip,
    COUNT(*) AS event_count
FROM events
WHERE INOFFENSE($offenseId)$extraWhere
GROUP BY sourceip
ORDER BY event_count DESC
$aqlTimeClause
"@

$topSourceIpsStage = Invoke-StagedAql `
    -BaseUrl $inst.BaseUrl `
    -Token $token `
    -Label "top_source_ips" `
    -Aql $aqlTopSourceIps `
    -Limit $RESULT_LIMIT `
    -MaxWaitSeconds $MAX_WAIT_SECONDS

$collectionStages += $topSourceIpsStage
$topSourceIps = Get-StageEvents -Stage $topSourceIpsStage

$topSourceIps = Get-StageEvents -Stage $topSourceIpsStage
<#
Write-Host "DEBUG topSourceIpsStage raw: $(Compact-Json $topSourceIpsStage)" -ForegroundColor Magenta
Write-Host "DEBUG topSourceIps count after Get-StageEvents: $($topSourceIps.Count)" -ForegroundColor Magenta
Write-Host "DEBUG topSourceIps JSON: $(Compact-JsonArray $topSourceIps)" -ForegroundColor Magenta
#>
$aqlTopDestinationIps = @"
SELECT
    destinationip,
    COUNT(*) AS event_count
FROM events
WHERE INOFFENSE($offenseId)$extraWhere
GROUP BY destinationip
ORDER BY event_count DESC
$aqlTimeClause
"@

$topDestinationIpsStage = Invoke-StagedAql `
    -BaseUrl $inst.BaseUrl `
    -Token $token `
    -Label "top_destination_ips" `
    -Aql $aqlTopDestinationIps `
    -Limit $RESULT_LIMIT `
    -MaxWaitSeconds $MAX_WAIT_SECONDS
$collectionStages += $topDestinationIpsStage
$topDestinationIps = Get-StageEvents -Stage $topDestinationIpsStage

$topDestinationIps = Get-StageEvents -Stage $topDestinationIpsStage
<#
Write-Host "DEBUG topDestinationIpsStage raw: $(Compact-Json $topDestinationIpsStage)" -ForegroundColor Magenta
Write-Host "DEBUG topDestinationIps count after Get-StageEvents: $($topDestinationIps.Count)" -ForegroundColor Magenta
Write-Host "DEBUG topDestinationIps JSON: $(Compact-JsonArray $topDestinationIps)" -ForegroundColor Magenta
#>

$aqlTopUsernames = @"
SELECT
    username,
    COUNT(*) AS event_count
FROM events
WHERE INOFFENSE($offenseId)$extraWhere
GROUP BY username
ORDER BY event_count DESC
$aqlTimeClause
"@

$topUsernamesStage = Invoke-StagedAql `
    -BaseUrl $inst.BaseUrl `
    -Token $token `
    -Label "top_usernames" `
    -Aql $aqlTopUsernames `
    -Limit $RESULT_LIMIT `
    -MaxWaitSeconds $MAX_WAIT_SECONDS

$collectionStages += $topUsernamesStage
$topUsernames = Get-StageEvents -Stage $topUsernamesStage

$topUsernames = Get-StageEvents -Stage $topUsernamesStage
<#
Write-Host "DEBUG topUsernamesStage raw: $(Compact-Json $topUsernamesStage)" -ForegroundColor Magenta
Write-Host "DEBUG topUsernames count after Get-StageEvents: $($topUsernames.Count)" -ForegroundColor Magenta
Write-Host "DEBUG topUsernames JSON: $(Compact-JsonArray $topUsernames)" -ForegroundColor Magenta
#>

$aqlTopLogSources = @"
SELECT
    logsourceid,
    COUNT(*) AS event_count
FROM events
WHERE INOFFENSE($offenseId)$extraWhere
GROUP BY logsourceid
ORDER BY event_count DESC
$aqlTimeClause
"@

$topLogSourcesStage = Invoke-StagedAql `
    -BaseUrl $inst.BaseUrl `
    -Token $token `
    -Label "top_log_sources" `
    -Aql $aqlTopLogSources `
    -Limit $RESULT_LIMIT `
    -MaxWaitSeconds $MAX_WAIT_SECONDS

$collectionStages += $topLogSourcesStage
$topLogSources = Get-StageEvents -Stage $topLogSourcesStage

$topLogSources = Get-StageEvents -Stage $topLogSourcesStage
<#
Write-Host "DEBUG topLogSourcesStage raw: $(Compact-Json $topLogSourcesStage)" -ForegroundColor Magenta
Write-Host "DEBUG topLogSources count after Get-StageEvents: $($topLogSources.Count)" -ForegroundColor Magenta
Write-Host "DEBUG topLogSources JSON: $(Compact-JsonArray $topLogSources)" -ForegroundColor Magenta
#>

$aqlTopCategories = @"
SELECT
    category,
    COUNT(*) AS event_count
FROM events
WHERE INOFFENSE($offenseId)$extraWhere
GROUP BY category
ORDER BY event_count DESC
$aqlTimeClause
"@

$topCategoriesStage = Invoke-StagedAql `
    -BaseUrl $inst.BaseUrl `
    -Token $token `
    -Label "top_categories" `
    -Aql $aqlTopCategories `
    -Limit $RESULT_LIMIT `
    -MaxWaitSeconds $MAX_WAIT_SECONDS

$collectionStages += $topCategoriesStage
$topCategories = Get-StageEvents -Stage $topCategoriesStage

$topCategories = Get-StageEvents -Stage $topCategoriesStage

<#
Write-Host "DEBUG topCategoriesStage raw: $(Compact-Json $topCategoriesStage)" -ForegroundColor Magenta
Write-Host "DEBUG topCategories count after Get-StageEvents: $($topCategories.Count)" -ForegroundColor Magenta
Write-Host "DEBUG topCategories JSON: $(Compact-JsonArray $topCategories)" -ForegroundColor Magenta
#>



# Always collect a small sample of strict offense-linked events.
$aqlSampleEvents = @"
SELECT
starttime,
qid,
username,
sourceip,
sourceport,
destinationip,
destinationport,
logsourceid,
category,
eventcount,
magnitude
FROM events
WHERE INOFFENSE($offenseId)$extraWhere
$aqlTimeClause
"@

$sampleEventsStage = Invoke-StagedAql `
    -BaseUrl $inst.BaseUrl `
    -Token $token `
    -Label "representative_events" `
    -Aql $aqlSampleEvents `
    -Limit $SAMPLE_EVENT_LIMIT `
    -MaxWaitSeconds $MAX_WAIT_SECONDS

$collectionStages += $sampleEventsStage
$sampleEvents = Get-StageEvents -Stage $sampleEventsStage

$sampleEvents = Get-StageEvents -Stage $sampleEventsStage

<#
Write-Host "DEBUG sampleEventsStage raw: $(Compact-Json $sampleEventsStage)" -ForegroundColor Magenta
Write-Host "DEBUG sampleEvents count after Get-StageEvents: $($sampleEvents.Count)" -ForegroundColor Magenta
Write-Host "DEBUG sampleEvents JSON: $(Compact-JsonArray $sampleEvents)" -ForegroundColor Magenta

# DEBUG the above counts for each distribution
Write-Host "DEBUG topQids count: $($topQids.Count)" -ForegroundColor Magenta
Write-Host "DEBUG topSourceIps count: $($topSourceIps.Count)" -ForegroundColor Magenta
Write-Host "DEBUG topDestinationIps count: $($topDestinationIps.Count)" -ForegroundColor Magenta
Write-Host "DEBUG topLogSources count: $($topLogSources.Count)" -ForegroundColor Magenta
Write-Host "DEBUG topCategories count: $($topCategories.Count)" -ForegroundColor Magenta
Write-Host "DEBUG sampleEvents count: $($sampleEvents.Count)" -ForegroundColor Magenta
#>
if ($evidenceModeChoice -eq "DEEP") {
    Write-Host ""
    Write-Host "DEEP mode selected. Running additional distribution queries..." -ForegroundColor Yellow

    $topSourceIps = Invoke-DistributionQuery `
        -BaseUrl $inst.BaseUrl `
        -Token $token `
        -OffenseId $offenseId `
        -FieldName "sourceip"

    $topDestinationIps = Invoke-DistributionQuery `
        -BaseUrl $inst.BaseUrl `
        -Token $token `
        -OffenseId $offenseId `
        -FieldName "destinationip"

    $topQids = Invoke-DistributionQuery `
        -BaseUrl $inst.BaseUrl `
        -Token $token `
        -OffenseId $offenseId `
        -FieldName "qid"

    $topUsernames = Invoke-DistributionQuery `
        -BaseUrl $inst.BaseUrl `
        -Token $token `
        -OffenseId $offenseId `
        -FieldName "username"

    $topLogSources = Invoke-DistributionQuery `
        -BaseUrl $inst.BaseUrl `
        -Token $token `
        -OffenseId $offenseId `
        -FieldName "logsourceid"

    $topCategories = Invoke-DistributionQuery `
        -BaseUrl $inst.BaseUrl `
        -Token $token `
        -OffenseId $offenseId `
        -FieldName "category"

    $aqlQidLogSourceCategory = @"
SELECT
    qid,
    logsourceid,
    category,
    COUNT(*) AS event_count
FROM events
WHERE INOFFENSE($offenseId)
GROUP BY qid, logsourceid, category
LAST $LOOKBACK_DAYS DAYS
"@

    $qidLogSourceCategoryResult = Invoke-OffenseLinkedAql `
        -BaseUrl $inst.BaseUrl `
        -Token $token `
        -Aql $aqlQidLogSourceCategory `
        -Limit $RESULT_LIMIT `
        -MaxWaitSeconds $MAX_WAIT_SECONDS

    $qidLogSourceCategory = Get-EventsArray $qidLogSourceCategoryResult.results

    $qidLogSourceCategory = @(
        $qidLogSourceCategory |
            Sort-Object -Property event_count -Descending
    )
}
else {
    Write-Host ""
    Write-Host "FAST mode selected. Using bounded staged Ariel distribution queries." -ForegroundColor Yellow

    $combinedDistribution = @($combinedDistribution)

    $combinedDistribution = @(
        $combinedDistribution |
            Sort-Object -Property event_count -Descending
    )

    $topSourceIps = Get-TopDistributionFromCombined `
        -CombinedDistribution $combinedDistribution `
        -FieldName "sourceip" `
        -Limit $RESULT_LIMIT

    $topDestinationIps = Get-TopDistributionFromCombined `
        -CombinedDistribution $combinedDistribution `
        -FieldName "destinationip" `
        -Limit $RESULT_LIMIT

    $topQids = Get-TopDistributionFromCombined `
        -CombinedDistribution $combinedDistribution `
        -FieldName "qid" `
        -Limit $RESULT_LIMIT

    $topUsernames = Get-TopDistributionFromCombined `
        -CombinedDistribution $combinedDistribution `
        -FieldName "username" `
        -Limit $RESULT_LIMIT

    $topLogSources = Get-TopDistributionFromCombined `
        -CombinedDistribution $combinedDistribution `
        -FieldName "logsourceid" `
        -Limit $RESULT_LIMIT

    $topCategories = Get-TopDistributionFromCombined `
        -CombinedDistribution $combinedDistribution `
        -FieldName "category" `
        -Limit $RESULT_LIMIT

    $qidLogSourceCategory = @(
        $combinedDistribution |
            Sort-Object -Property event_count -Descending
    )
}

# ----------------------------
# Finalize staged evidence arrays
# ----------------------------
# Important:
# PowerShell can unwrap single-item arrays or later logic can overwrite variables.
# Rehydrate the final evidence arrays directly from the stage objects immediately
# before legacy field derivation and template generation.

$topQids = @(Get-StageEvents -Stage $topQidsStage)
$topSourceIps = @(Get-StageEvents -Stage $topSourceIpsStage)
$topDestinationIps = @(Get-StageEvents -Stage $topDestinationIpsStage)
$topUsernames = @(Get-StageEvents -Stage $topUsernamesStage)
$topLogSources = @(Get-StageEvents -Stage $topLogSourcesStage)
$topCategories = @(Get-StageEvents -Stage $topCategoriesStage)
$sampleEvents = @(Get-StageEvents -Stage $sampleEventsStage)
<#
Write-Host ""
Write-Host "DEBUG finalized staged evidence arrays:" -ForegroundColor Magenta
Write-Host "topQids count: $($topQids.Count)" -ForegroundColor Magenta
Write-Host "topSourceIps count: $($topSourceIps.Count)" -ForegroundColor Magenta
Write-Host "topDestinationIps count: $($topDestinationIps.Count)" -ForegroundColor Magenta
Write-Host "topUsernames count: $($topUsernames.Count)" -ForegroundColor Magenta
Write-Host "topLogSources count: $($topLogSources.Count)" -ForegroundColor Magenta
Write-Host "topCategories count: $($topCategories.Count)" -ForegroundColor Magenta
Write-Host "sampleEvents count: $($sampleEvents.Count)" -ForegroundColor Magenta
Write-Host "topQids JSON: $(Compact-JsonArray $topQids)" -ForegroundColor Magenta
Write-Host "topSourceIps JSON: $(Compact-JsonArray $topSourceIps)" -ForegroundColor Magenta


Write-Host ""
Write-Host "DEBUG before legacy field derivation:" -ForegroundColor Magenta
Write-Host "topQids count: $($topQids.Count)" -ForegroundColor Magenta
Write-Host "topSourceIps count: $($topSourceIps.Count)" -ForegroundColor Magenta
Write-Host "topDestinationIps count: $($topDestinationIps.Count)" -ForegroundColor Magenta
Write-Host "topUsernames count: $($topUsernames.Count)" -ForegroundColor Magenta
Write-Host "topLogSources count: $($topLogSources.Count)" -ForegroundColor Magenta
Write-Host "topCategories count: $($topCategories.Count)" -ForegroundColor Magenta
Write-Host "sampleEvents count: $($sampleEvents.Count)" -ForegroundColor Magenta
Write-Host "topQids JSON: $(Compact-JsonArray $topQids)" -ForegroundColor Magenta
Write-Host "topSourceIps JSON: $(Compact-JsonArray $topSourceIps)" -ForegroundColor Magenta
#>
# ----------------------------
# Derive legacy-compatible fields from dominant offense-linked evidence
# ----------------------------


$primarySourceIp = Get-FirstValue -List $topSourceIps -FieldName "sourceip"
$primaryDestinationIp = Get-FirstValue -List $topDestinationIps -FieldName "destinationip"
$primaryQid = Get-FirstValue -List $topQids -FieldName "qid"
$primaryUsername = Get-FirstValue -List $topUsernames -FieldName "username"


$firstSample = $null

if ($sampleEvents.Count -gt 0) {
    $firstSample = $sampleEvents[0]
}

$sourcePort = ""
$destinationPort = ""
$category = ""
$logSourceId = ""

if ($firstSample) {
    $sourcePort = $firstSample.sourceport
    $destinationPort = $firstSample.destinationport
    $category = $firstSample.category
    $logSourceId = $firstSample.logsourceid
}

$ruleIds = @()

if ($offense.rules) {
    $ruleIds = @($offense.rules | ForEach-Object { $_.id })
}

$ruleIdLegacy = ""

if ($ruleIds.Count -gt 0) {
    $ruleIdLegacy = $ruleIds[0]
}

$offenseRulesRaw = @()
$qradarRuleApiMetadata = @()
$resolvedRuleBindings = @()

if ($offense.rules) {
    $offenseRulesRaw = @($offense.rules)

    foreach ($offenseRule in $offenseRulesRaw) {
        $offenseRuleId = $offenseRule.id

        if (-not $offenseRuleId) {
            continue
        }

        $metadata = Get-QradarAnalyticsRuleMetadata `
            -BaseUrl $inst.BaseUrl `
            -Token $token `
            -RuleId $offenseRuleId

        if ($metadata) {
            $qradarRuleApiMetadata += $metadata

            $binding = Resolve-ExportedRuleBinding `
                -LinkedRuleIdentifier $metadata.linked_rule_identifier `
                -Identifier $metadata.identifier `
                -RuleName $metadata.name

            if ($binding) {
                $resolvedRuleBindings += @{
                    offense_rule_id = $offenseRuleId
                    offense_rule_type = $offenseRule.type
                    qradar_identifier = $metadata.identifier
                    linked_rule_identifier = $metadata.linked_rule_identifier
                    qradar_rule_name = $metadata.name
                    qradar_origin = $metadata.origin
                    qradar_type = $metadata.type
                    exported_rule_doc_id = $binding.exported_rule_doc_id
                    exported_rule_name = $binding.exported_rule_name
                    exported_uuid = $binding.exported_uuid
                    exported_object_type = $binding.exported_object_type
                    exported_file_path = $binding.exported_file_path
                    binding_method = $binding.binding_method
                }
            }
            else {
                $resolvedRuleBindings += @{
                    offense_rule_id = $offenseRuleId
                    offense_rule_type = $offenseRule.type
                    qradar_identifier = $metadata.identifier
                    linked_rule_identifier = $metadata.linked_rule_identifier
                    qradar_rule_name = $metadata.name
                    qradar_origin = $metadata.origin
                    qradar_type = $metadata.type
                    exported_rule_doc_id = ""
                    exported_rule_name = ""
                    exported_uuid = ""
                    exported_object_type = ""
                    exported_file_path = ""
                    binding_method = "metadata_only_no_exported_match"
                }
            }
        }
        else {
            $resolvedRuleBindings += @{
                offense_rule_id = $offenseRuleId
                offense_rule_type = $offenseRule.type
                binding_method = "qradar_metadata_lookup_failed"
            }
        }
    }
}

$eventName = $offense.offense_source

if ([string]::IsNullOrWhiteSpace($eventName)) {
    $eventName = $offense.description
}

$eventName = "$eventName" -replace "`r", " " -replace "`n", " "
$eventName = $eventName.Trim()

$eventDescription = "$($offense.description)" -replace "`r", " " -replace "`n", " "
$eventDescription = $eventDescription.Trim()

$startTime = Convert-MsEpochToUtc $offense.start_time

if ($firstSample -and $firstSample.starttime) {
    $startTime = Convert-MsEpochToUtc $firstSample.starttime
}

# ----------------------------
# Payload summary
# ----------------------------

$payloadSummaryParts = @()

$payloadSummaryParts += "EvidenceMode=INOFFENSE_ONLY"
$payloadSummaryParts += "LookbackWindow=$aqlTimeClause"
$payloadSummaryParts += "QRadarStatus=$($offense.status)"
$payloadSummaryParts += "Magnitude=$($offense.magnitude)"
$payloadSummaryParts += "Severity=$($offense.severity)"
$payloadSummaryParts += "Relevance=$($offense.relevance)"
$payloadSummaryParts += "Credibility=$($offense.credibility)"
$payloadSummaryParts += "QRadarEventCount=$($offense.event_count)"
$payloadSummaryParts += "Notes=" + (Compact-Json $notes)

if ($sampleEvents.Count -eq 0) {
    $payloadSummaryParts += "CoverageWarning=No INOFFENSE events were returned. Do not infer tuning recommendation from contextual evidence."
}
else {
    $payloadSummaryParts += "CoverageWarning=Primary evidence is offense-linked using INOFFENSE. Distributions are stronger evidence than any single sample event."
}

$payloadSummary = ($payloadSummaryParts -join "  ")
# debug
<#
Write-Host ""
Write-Host "DEBUG before template build:" -ForegroundColor Magenta
Write-Host "topQids count: $($topQids.Count)" -ForegroundColor Magenta
Write-Host "topSourceIps count: $($topSourceIps.Count)" -ForegroundColor Magenta
Write-Host "topDestinationIps count: $($topDestinationIps.Count)" -ForegroundColor Magenta
Write-Host "topUsernames count: $($topUsernames.Count)" -ForegroundColor Magenta
Write-Host "topLogSources count: $($topLogSources.Count)" -ForegroundColor Magenta
Write-Host "topCategories count: $($topCategories.Count)" -ForegroundColor Magenta
Write-Host "sampleEvents count: $($sampleEvents.Count)" -ForegroundColor Magenta
Write-Host "topQids JSON before template: $(Compact-JsonArray $topQids)" -ForegroundColor Magenta
Write-Host "topSourceIps JSON before template: $(Compact-JsonArray $topSourceIps)" -ForegroundColor Magenta
#>
# ----------------------------
# Build Rulebot template
# ----------------------------

$template = ""

# ----------------------------
# Basic identifiers
# ----------------------------

$template += "offense_id: $offenseId`r`n"
$template += "client_id: default`r`n"
$template += "evidence_mode: INOFFENSE_ONLY`r`n"

# ----------------------------
# Human-readable evidence summary
# ----------------------------

$template += "evidence_summary:`r`n"
$template += "  evidence_mode: INOFFENSE_ONLY`r`n"
$template += "  collection_mode: $evidenceModeChoice`r`n"
$template += "  qradar_event_count: $($offense.event_count)`r`n"
$template += "  primary_source_ip: $primarySourceIp`r`n"
$template += "  primary_destination_ip: $primaryDestinationIp`r`n"
$template += "  primary_qid: $primaryQid`r`n"
$template += "  qid_distribution: $(Compact-JsonArray $topQids)`r`n"
$template += "  source_distribution: $(Compact-JsonArray $topSourceIps)`r`n"
$template += "  destination_distribution: $(Compact-JsonArray $topDestinationIps)`r`n"
$template += "  coverage_note: Primary evidence is offense-linked using INOFFENSE. Top distributions were collected using a bounded offense time window and offense log source filters. Representative events are examples only. Combined distribution is skipped in FAST mode because multi-field grouping can be expensive on QRadar.`r`n"
$template += "  dominant_log_source: $logSourceId`r`n"
$template += "  primary_category: $category`r`n"

# ----------------------------
# Rule / offense metadata
# ----------------------------

$template += "rule_id: $ruleIdLegacy`r`n"
$template += "rule_ids: $(Compact-Json $ruleIds)`r`n"
$template += "offense_rules_raw: $(Compact-JsonArray $offenseRulesRaw)`r`n"
$template += "qradar_rule_api_metadata: $(Compact-JsonArray $qradarRuleApiMetadata)`r`n"
$template += "resolved_rule_bindings: $(Compact-JsonArray $resolvedRuleBindings)`r`n"
$template += "event_name: $eventName`r`n"
$template += "event_description: $eventDescription`r`n"

# ----------------------------
# Legacy compatibility fields
# Keep these for current Rulebot prompt compatibility.
# These are now derived from dominant offense-linked evidence.
# ----------------------------

$template += "source_ip: $primarySourceIp`r`n"
$template += "source_port: $sourcePort`r`n"
$template += "destination_ip: $primaryDestinationIp`r`n"
$template += "destination_port: $destinationPort`r`n"
$template += "username: $primaryUsername`r`n"
$template += "log_source_id: $logSourceId`r`n"
$template += "qid: $primaryQid`r`n"
$template += "category: $category`r`n"

$template += "magnitude: $($offense.magnitude)`r`n"
$template += "severity: $($offense.severity)`r`n"
$template += "relevance: $($offense.relevance)`r`n"
$template += "credibility: $($offense.credibility)`r`n"
$template += "start_time: $startTime`r`n"
$template += "event_count: $($offense.event_count)`r`n"

# ----------------------------
# Rich offense-linked evidence fields
# Rulebot should eventually prioritize these over the legacy single fields.
# ----------------------------

$template += "top_source_ips: $(Compact-JsonArray $topSourceIps)`r`n"
$template += "top_destination_ips: $(Compact-JsonArray $topDestinationIps)`r`n"
$template += "top_qids: $(Compact-JsonArray $topQids)`r`n"
$template += "top_usernames: $(Compact-JsonArray $topUsernames)`r`n"
$template += "top_log_sources: $(Compact-JsonArray $topLogSources)`r`n"
$template += "top_categories: $(Compact-JsonArray $topCategories)`r`n"
$template += "qid_logsource_category_distribution: $(Compact-JsonArray $qidLogSourceCategory)`r`n"
$template += "combined_distribution: $(Compact-JsonArray $combinedDistribution)`r`n"
$template += "representative_events: $(Compact-JsonArray $sampleEvents)`r`n"
# $template += "collection_stages: $(Compact-JsonArray $collectionStages)`r`n" #add later when Rulebot has this field

# ----------------------------
# Compact machine-readable context
# ----------------------------

$template += "payload_summary: $payloadSummary`r`n"

# ----------------------------
# Analyst-fill fields
# ----------------------------

$template += "why_false_positive: `r`n"
$template += "desired_outcome: `r`n"
$template += "analyst_notes: `r`n"
$templateText = $template

$templateText | Set-Clipboard

Write-Host ""
Write-Host "Generated Rulebot packet:" -ForegroundColor Green
Write-Host ""
Write-Host $templateText

# Save to file as fallback/output artifact.
$outputDir = Join-Path $PSScriptRoot "output"

if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

$outputFile = Join-Path $outputDir "RulebotPacket-$offenseId.txt"

$templateText | Out-File -FilePath $outputFile -Encoding UTF8

Write-Host ""
Write-Host "Saved packet to:" -ForegroundColor Green
Write-Host $outputFile -ForegroundColor Green

try {
    $templateText | Set-Clipboard
    Write-Host ""
    Write-Host "OK: Rulebot offense template copied to clipboard." -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "WARNING: Clipboard copy failed. Use the saved output file instead." -ForegroundColor Yellow
    Write-Host $_.Exception.Message -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Notes:"
Write-Host "- FAST mode uses bounded START/STOP windows derived from QRadar offense metadata."
Write-Host "- FAST mode applies offense log source filters when available."
Write-Host "- FAST mode uses staged lightweight Ariel queries."
Write-Host "- Combined distribution is skipped in FAST mode because multi-field grouping can be expensive on QRadar."
