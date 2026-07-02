# Generate-QRadarPacket.ps1
# Clean Rulebot offense template generator
# Purpose:
#   - Pull offense details from QRadar
#   - Build the current Rulebot offense template
#   - Copy the result to clipboard for paste into Teams
#
# Notes:
#   - Analyst still fills:
#       why_false_positive

#       desired_outcome
#       analyst_notes
#   - Supports BH and KSA instances
#   - Uses QRadar API v16
#   - Uses curl.exe for consistency on Windows

$ErrorActionPreference = "Stop"

# TLS setup
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
[Net.ServicePointManager]::Expect100Continue = $false
[Net.ServicePointManager]::CheckCertificateRevocationList = $false
# Uncomment only if absolutely required
# [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

# ----------------------------
# Config
# ----------------------------
$API_VERSION = "16.0"

# Adjust these to your real instance URLs
$Instances = @{
    "BH"  = @{
        Name    = "BH"
        BaseUrl = "https://192.168.51.122"
        Token   = $env:QRADAR_BH_SEC_TOKEN
        ClientId = "default"
    }
    "KSA" = @{
        Name    = "KSA"
        BaseUrl = "https://192.168.60.161"
        Token   = $env:QRADAR_KSA_SEC_TOKEN
        ClientId = "default"
    }
}

# ----------------------------
# Helpers
# ----------------------------
function Convert-MsEpochToUtcDateTime {
    param($Ms)

    if ([string]::IsNullOrWhiteSpace("$Ms")) {
        return $null
    }

    try {
        return :FromUnixTimeMilliseconds([int64]$Ms).UtcDateTime
    }
    catch {
        return $null
    }
}


function Format-AqlUtcDateTime {
    param([datetime]$DateTime)

    # QRadar AQL START/STOP generally expects a readable timestamp string.
    return $DateTime.ToString("yyyy-MM-dd HH:mm:ss")
}


function Get-OffenseAqlTimeScope {
    param(
        $Offense,
        [int]$BeforeMinutes = 30,
        [int]$AfterMinutes = 90
    )

    $startMs = $Offense.start_time

    if ([string]::IsNullOrWhiteSpace("$startMs")) {
        return $null
    }

    $offenseStartUtc = Convert-MsEpochToUtcDateTime $startMs

    if ($null -eq $offenseStartUtc) {
        return $null
    }

    $windowStart = $offenseStartUtc.AddMinutes(-1 * $BeforeMinutes)
    $windowEnd   = $offenseStartUtc.AddMinutes($AfterMinutes)

    $startText = Format-AqlUtcDateTime $windowStart
    $endText   = Format-AqlUtcDateTime $windowEnd

    return @{
        Scope = "START '$startText' STOP '$endText'"
        Label = "$startText UTC to $endText UTC"
    }
}


function Get-FirstArielEvent {
    param($Result)

    if ($null -eq $Result) {
        return $null
    }

    if ($Result.events -and $Result.events.Count -gt 0) {
        return $Result.events[0]
    }

    if ($Result.rows -and $Result.rows.Count -gt 0) {
        return $Result.rows[0]
    }

    return $null
}


function Invoke-ArielAql {
    param(
        [string]$BaseUrl,
        [string]$Token,
        [string]$Aql,
        [int]$MaxWaitSeconds = 30
    )

    Write-Host "AQL:" -ForegroundColor DarkYellow
    Write-Host $Aql

    $search = Invoke-Qradar `
        -BaseUrl $BaseUrl `
        -Token $Token `
        -Method "POST" `
        -Path ("/api/ariel/searches?query_expression=" + [uri]::EscapeDataString($Aql))

    $searchId = Get-QradarSearchId -SearchResponse $search

    if ([string]::IsNullOrWhiteSpace($searchId)) {
        Write-Host "WARNING: Ariel search_id was empty." -ForegroundColor Red
        return $null
    }

    $ready = Wait-QradarSearch `
        -BaseUrl $BaseUrl `
        -Token $Token `
        -SearchId $searchId `
        -MaxWaitSeconds $MaxWaitSeconds

    if (-not $ready) {
        Write-Host "WARNING: Ariel search did not complete successfully." -ForegroundColor Red
        return $null
    }

    $result = Invoke-Qradar `
        -BaseUrl $BaseUrl `
        -Token $Token `
        -Method "GET" `
        -Path "/api/ariel/searches/$searchId/results"

    return $result
}


function Wait-QradarSearch {
    param(
        [string]$BaseUrl,
        [string]$Token,
        [string]$SearchId,
        [int]$MaxWaitSeconds = 30
    )

    $elapsed = 0

    while ($elapsed -lt $MaxWaitSeconds) {
        $status = Invoke-Qradar `
            -BaseUrl $BaseUrl `
            -Token $Token `
            -Method "GET" `
            -Path "/api/ariel/searches/$SearchId"

#        Write-Host "DEBUG: Ariel search $SearchId status: $($status.status)" -ForegroundColor DarkYellow

        if ($status.status -eq "COMPLETED") {
            return $true
        }

        if ($status.status -eq "ERROR" -or $status.status -eq "CANCELED") {
            return $false
        }

        Start-Sleep -Seconds 2
        $elapsed += 2
    }

    return $false
}


function Read-Choice {
    param(
        [string]$Prompt,
        [string[]]$Options
    )

    Write-Host $Prompt
    for ($i = 0; $i -lt $Options.Count; $i++) {
        Write-Host ("[{0}] {1}" -f ($i + 1), $Options[$i])
    }

    $n = Read-Host "Enter number"
    if (-not ($n -as [int])) {
        throw "Invalid selection."
    }

    $index = [int]$n - 1
    if ($index -lt 0 -or $index -ge $Options.Count) {
        throw "Invalid selection."
    }

    return $Options[$index]
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
        throw "Missing token. Set QRADAR_BH_SEC_TOKEN / QRADAR_KSA_SEC_TOKEN."
    }

    $uri = "$BaseUrl$Path"

    $args = @(
        "-k",
        "-sS",
        "-X", $Method,
        "-H", "SEC: $Token",
        "-H", "Accept: application/json",
        "-H", "Version: $API_VERSION"
    )

    if ($RangeHeader) {
        $args += @("-H", "Range: items=$RangeHeader")
    }

    if ($Body -ne $null) {
        $jsonBody = ($Body | ConvertTo-Json -Depth 20 -Compress)
        $args += @("-H", "Content-Type: application/json", "--data-binary", $jsonBody)
    }

    $args += $uri

    $raw = & curl.exe @args
    if ($LASTEXITCODE -ne 0) {
        throw "curl failed (exit $LASTEXITCODE) calling $uri"
    }

    try {
        return ($raw | ConvertFrom-Json)
    }
    catch {
        return $raw
    }
}

function Truncate-Text {
    param(
        [string]$Text,
        [int]$MaxLen = 400
    )

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return ""
    }

    $clean = $Text -replace "\r?\n", " "
    if ($clean.Length -gt $MaxLen) {
        return $clean.Substring(0, $MaxLen) + " ..."
    }

    return $clean
}

function Truncate-Json {
    param(
        $Object,
        [int]$MaxLen = 1000
    )

    if ($null -eq $Object) {
        return ""
    }

    $json = ($Object | ConvertTo-Json -Depth 20)
    return (Truncate-Text -Text $json -MaxLen $MaxLen)
}

function MsEpochToUtc {
    param($Ms)

    if ($null -eq $Ms) {
        return ""
    }

    try {
        return ([DateTimeOffset]::FromUnixTimeMilliseconds([long]$Ms)).UtcDateTime.ToString("o")
    }
    catch {
        return "$Ms"
    }
}

function Get-FirstRuleId {
    param($Offense)

    if ($Offense.rules -and $Offense.rules.Count -gt 0) {
        $firstRule = $Offense.rules | Select-Object -First 1
        if ($null -ne $firstRule.id) {
            return [string]$firstRule.id
        }
    }

    return ""
}

function Get-FirstQid {
    param(
        $SampleEvent,
        [string]$FallbackQid
    )

    if (-not [string]::IsNullOrWhiteSpace($FallbackQid)) {
        return $FallbackQid
    }

    if ($null -eq $SampleEvent) {
        return ""
    }

    $qidCandidates = @(
        "qid",
        "QID",
        "qidnumber",
        "qidNumber"
    )

    foreach ($field in $qidCandidates) {
        if ($SampleEvent.PSObject.Properties.Name -contains $field) {
            $value = $SampleEvent.$field
            if (-not [string]::IsNullOrWhiteSpace("$value")) {
                return "$value"
            }
        }
    }

    return ""
}

function Get-EventName {
    param(
        $Offense,
        $SampleEvent
    )

    if ($null -ne $SampleEvent) {
        $nameCandidates = @(
            "eventname",
            "eventName",
            "qidname",
            "qidName",
            "name",
            "Event Name",
            "QID Name"
        )

        foreach ($field in $nameCandidates) {
            if ($SampleEvent.PSObject.Properties.Name -contains $field) {
                $value = "$($SampleEvent.$field)"
                if (-not [string]::IsNullOrWhiteSpace($value)) {
                    return $value.Trim()
                }
            }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace("$($Offense.description)")) {
        return "$($Offense.description)".Trim()
    }

    return "Unknown event"
}

function Get-QradarSearchId {
    param($SearchResponse)

    if ($null -eq $SearchResponse) {
        return ""
    }

    foreach ($name in @("search_id", "searchId", "id")) {
        if ($SearchResponse.PSObject.Properties.Name -contains $name) {
            $value = $SearchResponse.$name
            if (-not [string]::IsNullOrWhiteSpace("$value")) {
                return "$value"
            }
        }
    }

    return ""
}


function Get-EventField {
    param(
        $Event,
        [string[]]$Names
    )

    if ($null -eq $Event) {
        return ""
    }

    foreach ($name in $Names) {
        if ($Event.PSObject.Properties.Name -contains $name) {
            $value = $Event.$name
            if (-not [string]::IsNullOrWhiteSpace("$value")) {
                return "$value"
            }
        }
    }

    return ""
}


function Resolve-LogSourceName {
    param(
        $Offense,
        $SampleEvent
    )

    $logSourceId = Get-EventField -Event $SampleEvent -Names @("logsourceid", "logSourceId", "LogSourceId")

    if ([string]::IsNullOrWhiteSpace($logSourceId)) {
        return ""
    }

    if ($Offense.log_sources) {
        foreach ($ls in $Offense.log_sources) {
            if ("$($ls.id)" -eq "$logSourceId") {
                if ($ls.name) {
                    return "$($ls.name)"
                }

                return "logsourceid=$logSourceId"
            }
        }
    }

    return "logsourceid=$logSourceId"
}

# ----------------------------
# Main
# ----------------------------
$instanceKey = Read-Choice "Select QRadar instance:" @("BH", "KSA")
$inst = $Instances[$instanceKey]

$offenseId = Read-Host "Enter Offense ID"
$qidOpt    = Read-Host "Optional QID (press Enter to skip)"

# 1) Pull offense
$offense = Invoke-Qradar `
    -BaseUrl $inst.BaseUrl `
    -Token $inst.Token `
    -Method "GET" `
    -Path "/api/siem/offenses/$offenseId"

# 2) Pull offense notes (optional)
$notes = $null
try {
    $notes = Invoke-Qradar `
        -BaseUrl $inst.BaseUrl `
        -Token $inst.Token `
        -Method "GET" `
        -Path "/api/siem/offenses/$offenseId/notes" `
        -RangeHeader "0-2"
}
catch {
    # Notes are optional
}

# 3) Ariel sample query (best-effort)
$sampleEvent = $null
$freq = "unknown"

$COUNT_HOURS_BACK = 4
$FALLBACK_SAMPLE_HOURS_BACK = 24

# Primary sample/count window around the offense start time
$OFFENSE_WINDOW_BEFORE_MINUTES = 30
$OFFENSE_WINDOW_AFTER_MINUTES  = 90


$logSourceIds = @()
if ($offense.log_sources) {
    $logSourceIds = $offense.log_sources | ForEach-Object { $_.id }
}

$logSourceFilter = ""
if ($logSourceIds.Count -gt 0) {
    $idList = ($logSourceIds -join ",")
    $logSourceFilter = " AND logsourceid IN ($idList)"
}

$sampleSelectFields = "starttime, qid, username, sourceip, sourceport, destinationip, destinationport, logsourceid, category"

if (-not [string]::IsNullOrWhiteSpace($qidOpt)) {
    $whereFilter = "qid = $qidOpt $logSourceFilter"
}
else {
    $whereFilter = "1=1 $logSourceFilter"
}

$offenseTimeScope = Get-OffenseAqlTimeScope `
    -Offense $offense `
    -BeforeMinutes $OFFENSE_WINDOW_BEFORE_MINUTES `
    -AfterMinutes $OFFENSE_WINDOW_AFTER_MINUTES

if ($offenseTimeScope) {
    $primaryTimeScope = $offenseTimeScope.Scope
    $primaryTimeLabel = $offenseTimeScope.Label
}
else {
    $primaryTimeScope = "LAST $FALLBACK_SAMPLE_HOURS_BACK HOURS"
    $primaryTimeLabel = "LAST $FALLBACK_SAMPLE_HOURS_BACK HOURS"
}

$aqlCountPrimary = "SELECT COUNT(*) AS cnt FROM events WHERE $whereFilter $primaryTimeScope"
$aqlSamplePrimary = "SELECT $sampleSelectFields FROM events WHERE $whereFilter $primaryTimeScope"

$aqlCountFallback = "SELECT COUNT(*) AS cnt FROM events WHERE $whereFilter LAST $COUNT_HOURS_BACK HOURS"
$aqlSampleFallback = "SELECT $sampleSelectFields FROM events WHERE $whereFilter LAST $FALLBACK_SAMPLE_HOURS_BACK HOURS"

try {
    # ----------------------------
    # COUNT SEARCH
    # ----------------------------

    Write-Host ""
    Write-Host "Running primary count query around offense time..." -ForegroundColor Yellow

    $result1 = Invoke-ArielAql `
        -BaseUrl $inst.BaseUrl `
        -Token $inst.Token `
        -Aql $aqlCountPrimary `
        -MaxWaitSeconds 30

    if ($result1 -and $result1.events -and $result1.events.Count -gt 0 -and $result1.events[0].cnt) {
        $freq = "$($result1.events[0].cnt)"
        $freqWindowLabel = $primaryTimeLabel
    }
    elseif ($result1 -and $result1.rows -and $result1.rows.Count -gt 0 -and $result1.rows[0].cnt) {
        $freq = "$($result1.rows[0].cnt)"
        $freqWindowLabel = $primaryTimeLabel
    }
    else {
        Write-Host "Primary count query returned no count. Trying fallback count window..." -ForegroundColor Yellow

        $result1Fallback = Invoke-ArielAql `
            -BaseUrl $inst.BaseUrl `
            -Token $inst.Token `
            -Aql $aqlCountFallback `
            -MaxWaitSeconds 30

        if ($result1Fallback -and $result1Fallback.events -and $result1Fallback.events.Count -gt 0 -and $result1Fallback.events[0].cnt) {
            $freq = "$($result1Fallback.events[0].cnt)"
            $freqWindowLabel = "LAST $COUNT_HOURS_BACK HOURS"
        }
        elseif ($result1Fallback -and $result1Fallback.rows -and $result1Fallback.rows.Count -gt 0 -and $result1Fallback.rows[0].cnt) {
            $freq = "$($result1Fallback.rows[0].cnt)"
            $freqWindowLabel = "LAST $COUNT_HOURS_BACK HOURS"
        }
    }

    # ----------------------------
    # SAMPLE SEARCH
    # ----------------------------

    Write-Host ""
    Write-Host "Running primary sample query around offense time..." -ForegroundColor Yellow

    $result2 = Invoke-ArielAql `
        -BaseUrl $inst.BaseUrl `
        -Token $inst.Token `
        -Aql $aqlSamplePrimary `
        -MaxWaitSeconds 30

    $sampleEvent = Get-FirstArielEvent -Result $result2
    $sampleWindowLabel = $primaryTimeLabel

    if (-not $sampleEvent) {
        Write-Host "Primary sample query returned no event. Trying fallback sample window..." -ForegroundColor Yellow

        $result2Fallback = Invoke-ArielAql `
            -BaseUrl $inst.BaseUrl `
            -Token $inst.Token `
            -Aql $aqlSampleFallback `
            -MaxWaitSeconds 30

        $sampleEvent = Get-FirstArielEvent -Result $result2Fallback
        $sampleWindowLabel = "LAST $FALLBACK_SAMPLE_HOURS_BACK HOURS"
    }

    if ($sampleEvent) {
        Write-Host "Ariel sample event found. Populating offense fields..." -ForegroundColor Green
    }
    else {
        Write-Host "WARNING: No Ariel sample event found." -ForegroundColor Red
    }
}
catch {
    Write-Host "WARNING: Ariel failed - check permissions / query syntax / endpoint behavior." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    $freq = "unknown"
    $freqWindowLabel = "unknown"
    $sampleWindowLabel = "unknown"
}

# 4) Derive current Rulebot offense template fields

$ruleId = Get-FirstRuleId -Offense $offense
$qid    = Get-FirstQid -SampleEvent $sampleEvent -FallbackQid $qidOpt
$eventName = Get-EventName -Offense $offense -SampleEvent $sampleEvent

$eventDescription = $offense.description
if ( [string]::IsNullOrWhiteSpace($eventDescription)) {
    $eventDescription = $eventName
}

# Core offense metadata
$magnitude  = "$($offense.magnitude)"
$eventCount = "$($offense.event_count)"

# Sample event enrichment
$sourceIp = Get-EventField -Event $sampleEvent -Names @("sourceip", "sourceIP", "SourceIP")
$sourcePort = Get-EventField -Event $sampleEvent -Names @("sourceport", "sourcePort", "SourcePort")
$destinationIp = Get-EventField -Event $sampleEvent -Names @("destinationip", "destinationIP", "DestinationIP")
$destinationPort = Get-EventField -Event $sampleEvent -Names @("destinationport", "destinationPort", "DestinationPort")
$username = Get-EventField -Event $sampleEvent -Names @("username", "userName", "Username")
$category = Get-EventField -Event $sampleEvent -Names @("category", "Category")
$logSource = Resolve-LogSourceName -Offense $offense -SampleEvent $sampleEvent

$startTimeRaw = Get-EventField -Event $sampleEvent -Names @("starttime", "startTime", "StartTime")
$startTime = ""
if (-not [string]::IsNullOrWhiteSpace($startTimeRaw)) {
    $startTime = MsEpochToUtc $startTimeRaw
}
elseif ($offense.start_time) {
    $startTime = MsEpochToUtc $offense.start_time
}

$payloadSummaryParts = @()
$payloadSummaryParts += "Status=$($offense.status)"
$payloadSummaryParts += "Magnitude=$($offense.magnitude)"
$payloadSummaryParts += "Severity=$($offense.severity)"
$payloadSummaryParts += "Relevance=$($offense.relevance)"
$payloadSummaryParts += "Credibility=$($offense.credibility)"
$payloadSummaryParts += "EventCount=$($offense.event_count)"
$payloadSummaryParts += "LogSourceCount=$($offense.log_sources.Count)"
$payloadSummaryParts += "Frequency=$freq"
$payloadSummaryParts += "FrequencyWindow=$freqWindowLabel"
$payloadSummaryParts += "SampleWindow=$sampleWindowLabel"

if ($sampleEvent) {
    $payloadSummaryParts += "SampleEvent=" + (Truncate-Json -Object $sampleEvent -MaxLen 600)
}

if ($notes) {
    $payloadSummaryParts += "Notes=" + (Truncate-Json -Object $notes -MaxLen 300)
}

$payloadSummary = ($payloadSummaryParts -join " | ")

# 5) Build current Rulebot template

$template = ""
$template += "offense_id: $offenseId`r`n"
$template += "client_id: default`r`n"
$template += "rule_id: $ruleId`r`n"
$template += "event_name: $eventName`r`n"
$template += "event_description: $eventDescription`r`n"
$template += "source_ip: $sourceIp`r`n"
$template += "source_port: $sourcePort`r`n"
$template += "destination_ip: $destinationIp`r`n"
$template += "destination_port: $destinationPort`r`n"
$template += "username: $username`r`n"
$template += "log_source: $logSource`r`n"
$template += "qid: $qid`r`n"
$template += "category: $category`r`n"
$template += "magnitude: $magnitude`r`n"
$template += "start_time: $startTime`r`n"
$template += "event_count: $eventCount`r`n"
$template += "payload_summary: $payloadSummary`r`n"
$template += "why_false_positive: `r`n"
$template += "desired_outcome: `r`n"
$template += "analyst_notes: `r`n"

$templateText = $template

# 6) Copy to clipboard + print
$templateText | Set-Clipboard

Write-Host ""
Write-Host "OK: Rulebot offense template copied to clipboard." -ForegroundColor Green
Write-Host ""
Write-Host $templateText
Write-Host ""
Write-Host "Notes:"
Write-Host "- Fill why_false_positive, desired_outcome, and analyst_notes before sending to Rulebot."
Write-Host "- If event_name is too generic, you can edit it manually before paste."
