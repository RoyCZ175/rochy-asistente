' Arranca el detector de doble aplauso (clap_launcher.py) sin ninguna
' consola visible. Para que abra solo con Windows: copiá este archivo a la
' carpeta de Inicio (Windows+R, escribí "shell:startup", Enter, y pegalo
' ahí) — Roger lo hace a mano a propósito, es un cambio permanente a cómo
' arranca la PC.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)

pythonw = baseDir & "\.venv\Scripts\pythonw.exe"
script = baseDir & "\clap_launcher.py"

If Not fso.FileExists(pythonw) Then
    WScript.Quit 1
End If

shell.CurrentDirectory = baseDir
shell.Run """" & pythonw & """ """ & script & """", 0, False
