Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Coding\Komdigi"
WshShell.Run "cmd /c C:\Coding\Komdigi\run_residential_proxy.bat", 0, False
