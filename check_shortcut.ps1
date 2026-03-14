$shell = New-Object -ComObject WScript.Shell
$path = [Environment]::GetFolderPath('ApplicationData') + '\Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\'
$files = Get-ChildItem $path -Filter '*Chrome*.lnk'
if ($files.Count -eq 0) {
    Write-Host "NO_CHROME_SHORTCUT_FOUND in $path"
} else {
    foreach ($f in $files) {
        $lnk = $shell.CreateShortcut($f.FullName)
        Write-Host "File: $($f.Name)"
        Write-Host "Target: $($lnk.TargetPath)"
        Write-Host "Arguments: $($lnk.Arguments)"
    }
}
