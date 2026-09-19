Option Explicit

Dim fso, shell, rootDir, appDir, electronExe, indexHtml, logFile, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

rootDir = fso.GetParentFolderName(WScript.ScriptFullName)
appDir = rootDir & "\apps\desktop"
electronExe = rootDir & "\node_modules\electron\dist\electron.exe"
indexHtml = appDir & "\dist\index.html"
logFile = rootDir & "\projects\one-click-launcher.log"

If Not fso.FolderExists(rootDir & "\projects") Then
  fso.CreateFolder(rootDir & "\projects")
End If

Call LogLine("=== Lancement DubRoom Studio ===")
Call LogLine("Racine: " & rootDir)

If Not fso.FileExists(electronExe) Then
  Call Fail("Electron n'est pas installé dans le projet." & vbCrLf & vbCrLf & _
            "Fichier attendu :" & vbCrLf & electronExe)
End If

If Not fso.FileExists(indexHtml) Then
  Call Fail("L'interface compilée est absente." & vbCrLf & vbCrLf & _
            "Fichier attendu :" & vbCrLf & indexHtml)
End If

' Electron démarre lui-même le backend FastAPI avec le Python local du projet.
' Le verrou d'instance unique remet simplement la fenêtre au premier plan si elle tourne déjà.
shell.CurrentDirectory = appDir
command = """" & electronExe & """ ."
Call LogLine("Commande: " & command)
shell.Run command, 1, False
Call LogLine("Application demandée. Electron prend en charge le backend et l'interface.")

Sub LogLine(message)
  Dim stream
  On Error Resume Next
  Set stream = fso.OpenTextFile(logFile, 8, True)
  stream.WriteLine "[" & Now & "] " & message
  stream.Close
  On Error GoTo 0
End Sub

Sub Fail(message)
  Call LogLine("ERREUR: " & Replace(message, vbCrLf, " | "))
  MsgBox message & vbCrLf & vbCrLf & "Journal :" & vbCrLf & logFile, _
         vbCritical, "DubRoom Studio"
  WScript.Quit 1
End Sub
