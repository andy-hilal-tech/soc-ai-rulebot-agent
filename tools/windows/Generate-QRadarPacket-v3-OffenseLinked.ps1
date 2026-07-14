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

Write-Host "DEBUG: Script started" -ForegroundColor Cyan

# ----------------------------
# Config
# ----------------------------

$API_VERSION = "16.0"

$Instances = @{
    "BH" = @{
        BaseUrl = "https://192.168.51.122"
        TokenEnvCandidates = @(
            "QRADAR_TOKEN",
            "QRADAR_TOKEN_BH",
            "QRADAR_SEC_TOKEN",
            "QRADAR_API_TOKEN"
        )
    }
    "KSA" = @{
        BaseUrl = "https://YOUR-KSA-QRADAR-HOST"
        TokenEnvCandidates = @(
            "QRADAR_TOKEN_KSA",
            "QRADAR_TOKEN"
        )
    }
}

$LOOKBACK_DAYS = 30
$MAX_WAIT_SECONDS = 180
$SAMPLE_EVENT_LIMIT = 5
$RESULT_LIMIT = 20
$SKIP_CERT_VALIDATION = $true
$VERBOSE_SEARCH_LOG = $false

# ----------------------------
# Helpers
# ----------------------------

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
# One combined distribution query gives us source/destination/QID/logsource/category/username combinations.
$aqlCombinedDistribution = @"
SELECT
    sourceip,
    destinationip,
    qid,
    logsourceid,
    category,
    username,
    COUNT(*) AS event_count
FROM events
WHERE INOFFENSE($offenseId)
GROUP BY sourceip, destinationip, qid, logsourceid, category, username
LAST $LOOKBACK_DAYS DAYS
"@

$combinedDistributionResult = Invoke-OffenseLinkedAql `
    -BaseUrl $inst.BaseUrl `
    -Token $token `
    -Aql $aqlCombinedDistribution `
    -Limit $RESULT_LIMIT `
    -MaxWaitSeconds $MAX_WAIT_SECONDS

$combinedDistribution = Get-EventsArray $combinedDistributionResult.results

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
WHERE INOFFENSE($offenseId)
LAST $LOOKBACK_DAYS DAYS
"@

$sampleEventsResult = Invoke-OffenseLinkedAql `
    -BaseUrl $inst.BaseUrl `
    -Token $token `
    -Aql $aqlSampleEvents `
    -Limit $SAMPLE_EVENT_LIMIT `
    -MaxWaitSeconds $MAX_WAIT_SECONDS

$sampleEvents = Get-EventsArray $sampleEventsResult.results

# Initialise optional DEEP-mode arrays.
$topSourceIps = @()
$topDestinationIps = @()
$topQids = @()
$topUsernames = @()
$topLogSources = @()
$topCategories = @()
$qidLogSourceCategory = @()

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
    Write-Host "FAST mode selected. Deriving top evidence from combined distribution." -ForegroundColor Yellow

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
# Derive legacy-compatible fields from dominant offense-linked evidence
# ----------------------------

$topSourceIps = @($topSourceIps)
$topDestinationIps = @($topDestinationIps)
$topQids = @($topQids)
$topUsernames = @($topUsernames)
$topLogSources = @($topLogSources)
$topCategories = @($topCategories)

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
$payloadSummaryParts += "LookbackWindow=LAST $LOOKBACK_DAYS DAYS"
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
$template += "  coverage_note: Primary evidence is offense-linked using INOFFENSE. Distributions are stronger evidence than any single sample event.`r`n"
$template += "  dominant_log_source: $logSourceId`r`n"
$template += "  primary_category: $category`r`n"

# ----------------------------
# Rule / offense metadata
# ----------------------------

$template += "rule_id: $ruleIdLegacy`r`n"
$template += "rule_ids: $(Compact-Json $ruleIds)`r`n"
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
Write-Host "- Primary evidence is based on WHERE INOFFENSE($offenseId)."
Write-Host "- No contextual logsource/time-window sample is used as primary evidence."
Write-Host "- Distributions should be treated as stronger evidence than any single sample event."
Write-Host "- If INOFFENSE returns no events, do not make tuning recommendations from unrelated contextual evidence."
