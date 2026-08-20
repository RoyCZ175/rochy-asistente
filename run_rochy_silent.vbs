' Lanza Rochy sin mostrar ninguna ventana de consola/terminal, solo el widget.
Set fso = CreateObject("Scripting.FileSystemObject")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)

pythonw = baseDir & "\.venv\Scripts\pythonw.exe"
script = baseDir & "\voice_assistant.py"

If Not fso.FileExists(pythonw) Then
    MsgBox "No se encontró el entorno virtual. Corre install.bat primero.", vbExclamation, "Rochy"
    WScript.Quit 1
End If

Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = baseDir
shell.Run """" & pythonw & """ """ & script & """", 0, False
