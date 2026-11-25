@echo off
setlocal
cd /d "%~dp0"
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul
if errorlevel 1 exit /b 1

if /I "%1"=="test" (
    C:\Users\Infer\.cargo\bin\rustc.exe --edition 2021 --test src\main.rs -o run_tests.exe
    if errorlevel 1 exit /b 1
    run_tests.exe
    exit /b %ERRORLEVEL%
)

rc /nologo /fo app.res app.rc
if errorlevel 1 exit /b 1

C:\Users\Infer\.cargo\bin\rustc.exe --edition 2021 -C opt-level=z -C lto=fat -C codegen-units=1 -C strip=symbols -C panic=abort -C link-arg=app.res src\main.rs -o MouseBatteryControl.exe
if errorlevel 1 exit /b 1
del /q *.pdb 2>nul
echo Built MouseBatteryControl.exe successfully.
