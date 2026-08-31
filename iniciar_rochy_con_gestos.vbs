' Abre Rochy Y el control por gestos juntos, en un solo doble clic.
'
' Son dos proyectos separados a propósito (ver gestos_control, su propio
' venv/repo git) que se conectan entre sí por WebSocket (ver rochy_link.py)
' - este script solo automatiza abrir los dos, uno detrás del otro, no los
' une de verdad. Si algún día no querés la cámara encendida, seguí usando
' run_rochy_silent.vbs normal, que no la toca para nada.
Set fso = CreateObject("Scripting.FileSystemObject")
rochyDir = fso.GetParentFolderName(WScript.ScriptFullName)
gestosDir = "C:\Users\roger\Documents\gestos_control"

pythonwRochy = rochyDir & "\.venv\Scripts\pythonw.exe"
scriptRochy = rochyDir & "\voice_assistant.py"
pythonGestos = gestosDir & "\venv\Scripts\python.exe"
scriptGestos = gestosDir & "\main.py"

If Not fso.FileExists(pythonwRochy) Then
    MsgBox "No se encontró el entorno virtual de Rochy. Corre install.bat primero.", vbExclamation, "Rochy"
    WScript.Quit 1
End If
If Not fso.FileExists(pythonGestos) Then
    MsgBox "No se encontró el entorno virtual de gestos_control en " & gestosDir, vbExclamation, "Rochy"
    WScript.Quit 1
End If

Set shell = CreateObject("WScript.Shell")

shell.CurrentDirectory = rochyDir
shell.Run """" & pythonwRochy & """ """ & scriptRochy & """", 0, False

' Le da tiempo a Rochy a levantar su servidor WebSocket (puerto 8765) antes
' de que el control por gestos intente conectarse — igual reintenta solo
' cada 3s si llega a fallar (ver rochy_link.py), esto solo evita la espera.
WScript.Sleep 4000

shell.CurrentDirectory = gestosDir
shell.Run """" & pythonGestos & """ """ & scriptGestos & """", 1, False
