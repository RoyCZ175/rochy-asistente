' Lanza Rochy completo: el asistente (con la interfaz nueva, UI-ROCHY, ya
' incluida — ver ui_rochy_server.py) y el control por gestos (gestos_control,
' otro proyecto aparte), todo con un solo doble clic. Ninguna ventana de
' consola/terminal aparece para Rochy; la del control por gestos SÍ se ve
' (tiene su propia cámara) — decí "oculta la cámara" para esconderla sin
' cerrar el control por gestos.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
docsDir = shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\Documents"
gestosDir = docsDir & "\gestos_control"

pythonwRochy = baseDir & "\.venv\Scripts\pythonw.exe"
scriptRochy = baseDir & "\voice_assistant.py"
pythonGestos = gestosDir & "\venv\Scripts\python.exe"
scriptGestos = gestosDir & "\main.py"

If Not fso.FileExists(pythonwRochy) Then
    MsgBox "No se encontró el entorno virtual. Corre install.bat primero.", vbExclamation, "Rochy"
    WScript.Quit 1
End If

shell.CurrentDirectory = baseDir
shell.Run """" & pythonwRochy & """ """ & scriptRochy & """", 0, False

' El control por gestos es opcional a propósito: si esta PC todavía no lo
' tiene instalado, Rochy igual abre normal sin él (nada se rompe por esto).
If fso.FileExists(pythonGestos) Then
    WScript.Sleep 4000 ' le da tiempo a Rochy a levantar su servidor WebSocket
    shell.CurrentDirectory = gestosDir
    shell.Run """" & pythonGestos & """ """ & scriptGestos & """", 1, False
End If
