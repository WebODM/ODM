@echo off

setlocal
call win32env.bat

start "ODX Console" cmd /k "echo /============================\ && echo ^|^|    ___    ____   __  __  ^|^| && echo ^|^|   / _ \  ^|  _ \  \ \/ /  ^|^| && echo ^|^|  ^| ^| ^| ^| ^| ^| ^| ^|  \  /   ^|^| && echo ^|^|  ^| ^|_^| ^| ^| ^|_^| ^|  /  \   ^|^| && echo ^|^|   \___/  ^|____/  /_/\_\  ^|^| && echo ^|^|                          ^|^| && echo \============================/ && @echo off && FOR /F %%i in (VERSION) do echo        version: %%i && @echo on && echo. && run --help

endlocal
