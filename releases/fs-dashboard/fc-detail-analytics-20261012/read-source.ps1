param([string]$Start='2026-09-12',[string]$End='2026-10-11')
$ErrorActionPreference='Stop'
$fcConfig=Get-Content -LiteralPath "$PSScriptRoot/source/fc_detail_config.json" -Raw -Encoding UTF8
$fcModel=Get-Content -LiteralPath "$PSScriptRoot/source/fc_detail_model.py" -Raw -Encoding UTF8
$fcReader=Get-Content -LiteralPath "$PSScriptRoot/source/fc_detail_reader.py" -Raw -Encoding UTF8
$fcStop=[datetime]::ParseExact($End,'yyyy-MM-dd',[cultureinfo]::InvariantCulture).AddDays(1).ToString('yyyy-MM-dd')
$fcArgs=@{config=($fcConfig|ConvertFrom-Json);query=@{period=@{start="$Start 00:00";end="$fcStop 00:00"}}}|ConvertTo-Json -Depth 12 -Compress
$fcScript="import types,sys,json`nm=types.ModuleType('fc_detail_model')`nexec("+($fcModel|ConvertTo-Json -Compress)+",m.__dict__)`nsys.modules['fc_detail_model']=m`nsys.argv=['reader',"+($fcArgs|ConvertTo-Json -Compress)+"]`n$fcReader"
$fcRemote="docker exec -i fc27-p2pah-session python3 - <<'FC_DETAIL_READ'`n$fcScript`nFC_DETAIL_READ"
$fcDirectory=Join-Path "$PSScriptRoot/../.agent_runtime" 'fc27-detail-analytics-20261012'
New-Item -ItemType Directory -Force -Path $fcDirectory|Out-Null
$fcOutput=Join-Path $fcDirectory (([datetime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))+'-snapshot.json')
& "$PSScriptRoot/../server_187/access/Invoke-Server187.ps1" -Action Run -RemoteCommand $fcRemote | Set-Content -LiteralPath $fcOutput -Encoding utf8
$fcData=Get-Content -LiteralPath $fcOutput -Raw -Encoding UTF8|ConvertFrom-Json
if(-not $fcData.snapshot_id){throw 'Read failed; preserve original output for diagnosis.'}
@{path=$fcOutput;snapshot_id=$fcData.snapshot_id;as_of=$fcData.as_of;paid_orders=$fcData.orders.Count;backlog=$fcData.backlog.Count;coverage=$fcData.coverage}|ConvertTo-Json -Depth 8
