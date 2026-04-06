@echo off
cls

REM ============================================================
REM  NgpCraft_base_template - Build script (Windows)
REM  MIT License
REM
REM  Flash save uses standalone AMD stubs (no system.lib needed).
REM  See build_official_lib.bat if you want the system.lib path.
REM
REM  CONFIGURATION: Edit the paths below to match your setup.
REM ============================================================

REM --- Toolchain path (Toshiba cc900 compiler) ---
SET compilerPath=C:\t900

REM --- Flash save (standalone -- no system.lib required) ---
REM     0 = disabled (default)   1 = enabled
SET FlashSave=0

REM --- ROM name (also update CartTitle in src/core/carthdr.h) ---
SET romName=main

REM --- Pad ROM to 2MB for flash carts? (1=yes, 0=no) ---
SET ResizeRom=1

REM --- Launch emulator after build? (1=yes, 0=no) ---
SET Run=1

REM --- Emulator executable path ---
SET emuPath="C:\emu\NeoPop\NeoPop-Win32.exe"

REM ============================================================
REM  BUILD (do not edit below unless you know what you are doing)
REM ============================================================

SET THOME=%compilerPath%
SET BinPath=bin
SET romExt=ngc
SET rootPath=%~dp0
path=%path%;%THOME%\bin

echo [NgpCraft_base_template] Building...

if "%FlashSave%"=="1" (
    make -f makefile clean NGP_ENABLE_FLASH_SAVE=1
    make -f makefile NGP_ENABLE_FLASH_SAVE=1
    make -f makefile move_files NGP_ENABLE_FLASH_SAVE=1
) else (
    make -f makefile clean
    make -f makefile
    make -f makefile move_files
)

if "%ResizeRom%"=="1" (
    if exist "%~dp0utils\NGPRomResize.exe" (
        echo [NgpCraft_base_template] Resizing ROM to 2MB...
        MOVE "%~dp0%BinPath%\%romName%.%romExt%" "%~dp0%BinPath%\_%romName%.%romExt%" >/dev/null 2>&1
        "%~dp0utils\NGPRomResize.exe" "%~dp0%BinPath%\_%romName%.%romExt%"
        MOVE "%~dp0%BinPath%\_%romName%.%romExt%" "%~dp0%BinPath%\%romName%.%romExt%" >/dev/null 2>&1
        DEL "%~dp0%BinPath%MB__%romName%.%romExt%" >/dev/null 2>&1
    ) else (
        echo [NgpCraft_base_template] Skip resize: utils\NGPRomResize.exe not found.
    )
)

if "%Run%"=="1" (
    if exist %emuPath% (
        echo [NgpCraft_base_template] Launching emulator...
        %emuPath% "%rootPath:~0,-1%.\%BinPath%\%romName%.%romExt%"
    ) else (
        echo [NgpCraft_base_template] Skip run: emulator not found at %emuPath%.
    )
)

echo [NgpCraft_base_template] Done.
