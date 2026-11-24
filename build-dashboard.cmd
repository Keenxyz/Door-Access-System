@echo off
setlocal
pushd "%~dp0phone" || exit /b 1

where.exe npm.cmd >nul 2>&1
if not errorlevel 1 goto build

set "npmDir=%ProgramFiles%\nodejs"
if exist "%npmDir%\npm.cmd" goto useNpmDirectory
set "npmDir=%ProgramFiles%\Microsoft Visual Studio\2022\Community\MSBuild\Microsoft\VisualStudio\NodeJs"
if exist "%npmDir%\npm.cmd" goto useNpmDirectory

echo npm was not found. Install Node.js or add its installation folder to PATH. 1>&2
popd
exit /b 1

:useNpmDirectory
set "PATH=%npmDir%;%PATH%"

:build
if not exist "node_modules\.bin\tsc.cmd" goto install
if not exist "node_modules\.bin\esbuild.cmd" goto install
goto bundle

:install
call npm.cmd ci
if errorlevel 1 goto done

:bundle
call npm.cmd run build

:done
set "buildExitCode=%ERRORLEVEL%"
popd
exit /b %buildExitCode%
