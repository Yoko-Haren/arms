# Export cell ranges of Excel files as PNG pictures (Excel's own rendering), for the upload guides, with the position
# of every column and row of the range (in points from the range's top-left) in a .json next to each picture.
# Each job line: <xlsx path>|<sheet name or index>|<range>|<output png>
param([string]$JobFile)
$ErrorActionPreference = 'Stop'
$jobs = Get-Content -LiteralPath $JobFile | Where-Object { $_.Trim() -ne '' }
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
try {
    foreach ($line in $jobs) {
        $path, $sheet, $range, $out = $line.Split('|')
        $wb = $xl.Workbooks.Open($path, 0, $true)
        try {
            if ($sheet -match '^\d+$') { $ws = $wb.Worksheets.Item([int]$sheet) } else { $ws = $wb.Worksheets.Item($sheet) }
            $ws.Activate()
            $rng = $ws.Range($range)
            $cols = @{}
            foreach ($c in $rng.Columns) { $cols[[string]$c.Column] = @([double]($c.Left - $rng.Left), [double]$c.Width) }
            $rows = @{}
            foreach ($r in $rng.Rows) { $rows[[string]$r.Row] = @([double]($r.Top - $rng.Top), [double]$r.Height) }
            $meta = @{ width = [double]$rng.Width; height = [double]$rng.Height; cols = $cols; rows = $rows }
            $meta | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath ($out -replace '\.png$', '.json') -Encoding utf8
            $rng.CopyPicture(1, 2)                     # as shown on screen, as a bitmap
            $obj = $ws.ChartObjects().Add(0, 0, $rng.Width + 4, $rng.Height + 4)
            $obj.Activate()
            $obj.Chart.Paste()
            $obj.Chart.ChartArea.Border.LineStyle = -4142     # no frame around the picture
            [void]$obj.Chart.Export($out, 'PNG')
            $obj.Delete()
            Write-Output "saved $out"
        } finally {
            $wb.Close($false)
        }
    }
} finally {
    $xl.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($xl) | Out-Null
}
