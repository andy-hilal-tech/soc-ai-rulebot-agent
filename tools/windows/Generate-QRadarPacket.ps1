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
$SAMPLE_HOURS_BACK = 24


$logSourceIds = @()
if ($offense.log_sources) {
    $logSourceIds = $offense.log_sources | ForEach-Object { $_.id }
}

$logSourceFilter = ""
if ($logSourceIds.Count -gt 0) {
    $idList = ($logSourceIds -join ",")
    $logSourceFilter = " AND logsourceid IN ($idList)"
}

if (-not [string]::IsNullOrWhiteSpace($qidOpt)) {
    $aqlCount  = "SELECT COUNT(*) AS cnt FROM events WHERE qid = $qidOpt $logSourceFilter LAST $COUNT_HOURS_BACK HOURS"
    $aqlSample = "SELECT starttime, qid, username, sourceip, sourceport, destinationip, destinationport, logsourceid, category FROM events WHERE qid = $qidOpt $logSourceFilter LAST $SAMPLE_HOURS_BACK HOURS"}
else {
    $aqlCount  = "SELECT COUNT(*) AS cnt FROM events WHERE 1=1 $logSourceFilter LAST $COUNT_HOURS_BACK HOURS"
    $aqlSample = "SELECT starttime, qid, username, sourceip, sourceport, destinationip, destinationport, logsourceid, category FROM events WHERE 1=1 $logSourceFilter LAST $SAMPLE_HOURS_BACK HOURS"}

try {
    Write-Host ""
    #Write-Host "DEBUG: Count AQL:" -ForegroundColor Yellow
    #Write-Host $aqlCount
    Write-Host ""
    #Write-Host "DEBUG: Sample AQL:" -ForegroundColor Yellow
    #Write-Host $aqlSample
    Write-Host ""

    # ----------------------------
    # COUNT SEARCH
    # ----------------------------
    $search1 = Invoke-Qradar `
        -BaseUrl $inst.BaseUrl `
        -Token $inst.Token `
        -Method "POST" `
        -Path ("/api/ariel/searches?query_expression=" + [uri]::EscapeDataString($aqlCount))

    #Write-Host "DEBUG: Count search response:" -ForegroundColor Yellow
    #$search1 | ConvertTo-Json -Depth 20
    Write-Host ""

    $search1Id = Get-QradarSearchId -SearchResponse $search1

    if (-not [string]::IsNullOrWhiteSpace($search1Id)) {
        $countReady = Wait-QradarSearch `
            -BaseUrl $inst.BaseUrl `
            -Token $inst.Token `
            -SearchId $search1Id `
            -MaxWaitSeconds 30

        if ($countReady) {
            $result1 = Invoke-Qradar `
                -BaseUrl $inst.BaseUrl `
                -Token $inst.Token `
                -Method "GET" `
                -Path "/api/ariel/searches/$search1Id/results"

            #Write-Host "DEBUG: Count result raw:" -ForegroundColor Yellow
            #$result1 | ConvertTo-Json -Depth 20
            Write-Host ""

            if ($result1.rows -and $result1.rows.Count -gt 0 -and $result1.rows[0].cnt) {
                $freq = "$($result1.rows[0].cnt)"
            }
            elseif ($result1.events -and $result1.events.Count -gt 0 -and $result1.events[0].cnt) {
                $freq = "$($result1.events[0].cnt)"
            }
        }
        else {
            Write-Host "WARNING: Ariel count search did not complete successfully." -ForegroundColor Red
        }
    }
    else {
        Write-Host "WARNING: Count search_id was empty." -ForegroundColor Red
    }

    # ----------------------------
    # SAMPLE SEARCH
    # ----------------------------
    $search2 = Invoke-Qradar `
        -BaseUrl $inst.BaseUrl `
        -Token $inst.Token `
        -Method "POST" `
        -Path ("/api/ariel/searches?query_expression=" + [uri]::EscapeDataString($aqlSample))

    #Write-Host "DEBUG: Sample search response:" -ForegroundColor Yellow
    #$search2 | ConvertTo-Json -Depth 20
    Write-Host ""

    $search2Id = Get-QradarSearchId -SearchResponse $search2

    if (-not [string]::IsNullOrWhiteSpace($search2Id)) {
        $sampleReady = Wait-QradarSearch `
            -BaseUrl $inst.BaseUrl `
            -Token $inst.Token `
            -SearchId $search2Id `
            -MaxWaitSeconds 30

        if ($sampleReady) {
            $result2 = Invoke-Qradar `
                -BaseUrl $inst.BaseUrl `
                -Token $inst.Token `
                -Method "GET" `
                -Path "/api/ariel/searches/$search2Id/results"

            Write-Host ""
            #Write-Host "DEBUG: Ariel sample result raw:" -ForegroundColor Yellow
            #$result2 | ConvertTo-Json -Depth 20
            Write-Host ""

            if ($result2.events -and $result2.events.Count -gt 0) {
                $sampleEvent = $result2.events[0]
            }
            elseif ($result2.rows -and $result2.rows.Count -gt 0) {
                $sampleEvent = $result2.rows[0]
            }

            if ($sampleEvent) {
                Write-Host ""
                #Write-Host "DEBUG: Sample event fields returned:" -ForegroundColor Yellow
                #$sampleEvent.PSObject.Properties.Name | ForEach-Object { Write-Host " - $_" }
                Write-Host ""

                #Write-Host "DEBUG: Sample event JSON:" -ForegroundColor Yellow
                #$sampleEvent | ConvertTo-Json -Depth 20
                Write-Host ""
            }
            else {
                Write-Host "DEBUG: No sample event was returned from Ariel." -ForegroundColor Red
            }
        }
        else {
            Write-Host "WARNING: Ariel sample search did not complete successfully." -ForegroundColor Red
        }
    }
    else {
        Write-Host "WARNING: Sample search_id was empty." -ForegroundColor Red
    }
}
catch {
    Write-Host "WARNING: Ariel failed - check permissions / query syntax / endpoint behavior." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    $freq = "unknown"
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
$payloadSummaryParts += "FrequencyLast1h=$freq"

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