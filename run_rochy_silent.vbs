' Lanza Rochy (con la interfaz nueva, UI-ROCHY, ya incluida — ver
' ui_rochy_server.py), sin ninguna ventana de consola/terminal.
'
' El control por gestos (gestos_control, otro proyecto aparte) YA NO se abre
' solo con esto a propósito — decí "activa los gestos" una vez Rochy esté
' abierto, así la cámara nunca se enciende sin que lo hayas pedido.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)

pythonwRochy = baseDir & "\.venv\Scripts\pythonw.exe"
scriptRochy = baseDir & "\voice_assistant.py"

If Not fso.FileExists(pythonwRochy) Then
    MsgBox "No se encontró el entorno virtual. Corre install.bat primero.", vbExclamation, "Rochy"
    WScript.Quit 1
End If

shell.CurrentDirectory = baseDir
shell.Run """" & pythonwRochy & """ """ & scriptRochy & """", 0, False
