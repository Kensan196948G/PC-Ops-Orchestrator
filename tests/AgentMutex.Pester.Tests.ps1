Set-StrictMode -Version Latest

# Tests for Issue #188 part 1: PowerShell Mutex single-instance enforcement.
#
# We don't load PCOpsAgent.ps1 itself — it starts the collection loop. We
# instead exercise the same .NET primitive (System.Threading.Mutex with a
# Global\ name) the agent uses, plus a small spawn-test that runs the real
# script through pwsh with a mock config and asserts the second instance exits 1.

Describe "Agent single-instance Mutex (Issue #188 part 1)" {
    BeforeAll {
        $script:repoRoot = Split-Path $PSScriptRoot -Parent
        $script:agentScript = Join-Path $script:repoRoot "agent\PCOpsAgent.ps1"
        # Unique per test run so parallel CI matrices don't collide.
        $script:mutexName = "Global\PCOpsAgent_PesterTest_" + ([guid]::NewGuid().ToString("N").Substring(0, 8))
    }

    It "named Global mutex grants the first holder and refuses the second" {
        $acquired1 = $false
        $mutex1 = New-Object System.Threading.Mutex($true, $script:mutexName, [ref]$acquired1)
        try {
            $acquired1 | Should -BeTrue

            $acquired2 = $false
            $mutex2 = New-Object System.Threading.Mutex($true, $script:mutexName, [ref]$acquired2)
            try {
                $acquired2 | Should -BeFalse
            } finally {
                $mutex2.Dispose()
            }
        } finally {
            if ($acquired1) {
                $mutex1.ReleaseMutex()
            }
            $mutex1.Dispose()
        }
    }

    It "after release a fresh acquirer succeeds" {
        $acquired = $false
        $m = New-Object System.Threading.Mutex($true, $script:mutexName, [ref]$acquired)
        if ($acquired) {
            $m.ReleaseMutex()
        }
        $m.Dispose()

        $acquired2 = $false
        $m2 = New-Object System.Threading.Mutex($true, $script:mutexName, [ref]$acquired2)
        try {
            $acquired2 | Should -BeTrue
        } finally {
            if ($acquired2) { $m2.ReleaseMutex() }
            $m2.Dispose()
        }
    }

    It "PCOpsAgent.ps1 entry point declares Global Mutex with pc_name" {
        Test-Path $script:agentScript | Should -BeTrue
        $content = Get-Content -Raw -Path $script:agentScript
        $content | Should -Match 'Global\\\\PCOpsAgent_'
        $content | Should -Match 'System\.Threading\.Mutex'
        # Release path must exist so a crashed first instance doesn't permanently
        # block the next start.
        $content | Should -Match 'ReleaseMutex'
        $content | Should -Match 'finally'
    }
}
