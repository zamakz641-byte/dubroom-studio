Option Explicit

Dim fso
Dim shell
Dim scriptDir
Dim rootDir
Dim appDir
Dim electronExe

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("Shell.Application")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
rootDir = fso.GetParentFolderName(scriptDir)
appDir = rootDir & "\apps\desktop"
electronExe = rootDir & "\node_modules\electron\dist\electron.exe"

If Not fso.FileExists(electronExe) Then
  MsgBox "Electron executable not found:" & vbCrLf & electronExe, vbCritical, "Dub Studio"
  WScript.Quit 1
End If

If Not fso.FileExists(appDir & "\dist\index.html") Then
  MsgBox "Desktop build is missing. Run npm run build first.", vbCritical, "Dub Studio"
  WScript.Quit 1
End If

shell.ShellExecute electronExe, """" & appDir & """", appDir, "open", 1
