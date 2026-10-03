Option Explicit
Dim shell, executable, command, code
Set shell = CreateObject("WScript.Shell")
If WScript.Arguments.Count <> 1 Then WScript.Quit 2
executable = WScript.Arguments(0)
command = Chr(34) & executable & Chr(34) & " background"
code = shell.Run(command, 0, True)
WScript.Quit code
