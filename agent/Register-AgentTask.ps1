<#
.SYNOPSIS
    PC-Ops Agent タスクスケジューラー登録スクリプト
.DESCRIPTION
    AgentをWindows Task Schedulerに登録し、5分間隔で自動実行する。
.NOTES
    Version: 1.0.0
#>

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$agentScript = Join-Path $scriptDir "PCOpsAgent.ps1"
$configPath = Join-Path $scriptDir "config.json"

if (-not (Test-Path $agentScript)) {
    Write-Error "Agentスクリプトが見つかりません: $agentScript"
    exit 1
}

$taskName = "PC-Ops Orchestrator Agent"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$agentScript`" -ConfigPath `"$configPath`" -WindowStyle Hidden"
$trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force
    Write-Host "Agentタスクを登録しました: $taskName" -ForegroundColor Green
    Start-ScheduledTask -TaskName $taskName
    Write-Host "Agentを起動しました" -ForegroundColor Green
} catch {
    Write-Error "タスク登録に失敗: $_"
    exit 1
}
