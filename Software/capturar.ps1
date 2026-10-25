Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr dc, uint flags);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int cx, int cy, uint flags);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
}
"@

$p = Get-Process -Name Nexus -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $p) { Write-Output "Nexus nao esta rodando"; exit 1 }

$h = $p.MainWindowHandle
Write-Output "handle: $h | visivel: $([Win]::IsWindowVisible($h)) | minimizada: $([Win]::IsIconic($h))"

# Restaura se minimizada, e forca para o topo sem mudar o tamanho.
if ([Win]::IsIconic($h)) { [Win]::ShowWindow($h, 9) | Out-Null }
$TOPMOST = [IntPtr](-1)
$SWP = 0x0001 -bor 0x0002 -bor 0x0040   # NOSIZE | NOMOVE | SHOWWINDOW
[Win]::SetWindowPos($h, $TOPMOST, 0, 0, 0, 0, $SWP) | Out-Null
Start-Sleep -Milliseconds 1500

$r = New-Object Win+RECT
[Win]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.R - $r.L; $alt = $r.B - $r.T
Write-Output "tamanho: ${w}x${alt}"

$bmp = New-Object System.Drawing.Bitmap $w, $alt
$g = [System.Drawing.Graphics]::FromImage($bmp)
$dc = $g.GetHdc()
$ok = [Win]::PrintWindow($h, $dc, 2)   # 2 = PW_RENDERFULLCONTENT (captura WebView2)
$g.ReleaseHdc($dc)
Write-Output "PrintWindow: $ok"

$destino = "C:\Users\Lucas\Desktop\DSH\Nexus\Software\captura.png"
$bmp.Save($destino, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "salvo: $destino"
