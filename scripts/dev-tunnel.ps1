# Optional: expose ONLY the API's OAuth callback over public HTTPS with cloudflared (Windows).
# Off by default. Needed for providers that reject http://localhost redirect URIs (Slack, Meta).
#
#   .\scripts\dev-tunnel.ps1                              quick tunnel (random trycloudflare.com URL)
#   $env:TUNNEL_HOSTNAME='api.example.com'; $env:TUNNEL_NAME='connect-dev'; .\scripts\dev-tunnel.ps1
#
# Writes PUBLIC_API_BASE_URL into apps\api\.env.local and removes it on exit.
# Quick tunnels do not support SSE, so chat keeps using API_BASE_URL (http://localhost:8000).
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$EnvFile = Join-Path $Root 'apps\api\.env.local'
$Config = Join-Path $Root 'apps\api\app\core\config.py'
$Port = if ($env:API_PORT) { $env:API_PORT } else { '8000' }

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host @'
cloudflared is not installed. This script never installs anything; install it yourself:

  Windows:  winget install --id Cloudflare.cloudflared
  macOS:    brew install cloudflared
  Linux:    https://pkg.cloudflare.com/ or https://github.com/cloudflare/cloudflared/releases/latest

Then run this script again.
'@
    exit 1
}

function Set-PublicUrl([string]$Url) {
    $lines = @()
    if (Test-Path $EnvFile) { $lines = Get-Content $EnvFile | Where-Object { $_ -notmatch '^PUBLIC_API_BASE_URL=' } }
    $lines += "PUBLIC_API_BASE_URL=$Url"
    Set-Content -Path $EnvFile -Value $lines -Encoding utf8
    (Get-Item $Config).LastWriteTime = Get-Date    # nudges `uvicorn --reload` to re-read settings
}

function Clear-PublicUrl {
    if (Test-Path $EnvFile) {
        $lines = Get-Content $EnvFile | Where-Object { $_ -notmatch '^PUBLIC_API_BASE_URL=' }
        Set-Content -Path $EnvFile -Value $lines -Encoding utf8
        (Get-Item $Config).LastWriteTime = Get-Date
    }
}

$log = New-TemporaryFile
$err = New-TemporaryFile
$proc = $null
try {
    if ($env:TUNNEL_HOSTNAME) {
        $url = "https://$($env:TUNNEL_HOSTNAME)"
        $args = @('tunnel', 'run')
        if ($env:TUNNEL_NAME) { $args += $env:TUNNEL_NAME }
        $proc = Start-Process cloudflared -ArgumentList $args -NoNewWindow -PassThru `
            -RedirectStandardOutput $log -RedirectStandardError $err
    } else {
        $proc = Start-Process cloudflared -ArgumentList @('tunnel', '--url', "http://localhost:$Port") `
            -NoNewWindow -PassThru -RedirectStandardOutput $log -RedirectStandardError $err
        $url = $null
        for ($i = 0; $i -lt 60 -and -not $url; $i++) {
            Start-Sleep -Milliseconds 500
            $text = (Get-Content $err -Raw) + (Get-Content $log -Raw)
            if ($text -match 'https://[a-z0-9-]+\.trycloudflare\.com') { $url = $Matches[0] }
            if ($proc.HasExited) { Write-Host $text; throw 'cloudflared exited early' }
        }
        if (-not $url) { throw 'Timed out waiting for the trycloudflare.com URL' }
    }

    Set-PublicUrl $url
    Write-Host ""
    Write-Host "PUBLIC_API_BASE_URL=$url   (written to apps\api\.env.local)"
    Write-Host "If your API is not running with --reload, restart it now so it picks this up."
    Write-Host ""
    Write-Host "Register these redirect URIs in each provider's console:"
    foreach ($fam in 'google', 'slack', 'notion', 'github', 'meta') {
        Write-Host "  ${fam}: $url/api/oauth/callback/$fam"
    }
    Write-Host ""
    Write-Host "Chat/SSE still goes to http://localhost:$Port. Press Ctrl+C to stop the tunnel."
    Wait-Process -Id $proc.Id
} finally {
    if ($proc -and -not $proc.HasExited) { Stop-Process -Id $proc.Id -Force }
    Clear-PublicUrl
    Remove-Item $log, $err -ErrorAction SilentlyContinue
    Write-Host "Tunnel stopped; PUBLIC_API_BASE_URL removed (redirect URIs are back to localhost)."
}
