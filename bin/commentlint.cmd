@echo off
rem Run the linter without naming an interpreter. Put this directory on PATH.
rem
rem The launcher lives in bin\ rather than the repository root because the root
rem already holds a directory named commentlint\, and on Windows a file cannot
rem share a name with a sibling directory.
setlocal
set "ROOT=%~dp0.."

rem A virtualenv inside the checkout is used without being activated, matching
rem task.py's use of sys.executable. Otherwise the py launcher, then python.
if exist "%ROOT%\.venv\Scripts\python.exe" goto :venv
where py >nul 2>nul
if not errorlevel 1 goto :launcher
where python >nul 2>nul
if not errorlevel 1 goto :python
echo commentlint: no python found on PATH 1>&2
exit /b 127

rem Each interpreter gets its own line so that the path can stay quoted. The
rem exit code is forwarded outside any parenthesized block, because cmd expands
rem %ERRORLEVEL% when it parses a block and would forward a stale value.
:venv
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\predict.py" %*
exit /b %ERRORLEVEL%

:launcher
py -3 "%ROOT%\predict.py" %*
exit /b %ERRORLEVEL%

:python
python "%ROOT%\predict.py" %*
exit /b %ERRORLEVEL%
