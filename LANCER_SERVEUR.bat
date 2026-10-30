@echo off
chcp 65001 >nul
title SO-ARM101 Controller Web

echo ========================================================
echo         SO-ARM101 - Lancement du Controleur Web
echo ========================================================
echo.

:: Se placer dans le dossier du projet
cd /d "%~dp0"

:: Configuration de l'encodage UTF-8 pour Python
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:: Chemin vers l'executable Python de l'environnement conda lerobot
set PYTHON_EXE=C:\Users\Benjamin\anaconda3\envs\lerobot\python.exe

if not exist "%PYTHON_EXE%" (
    echo [ERREUR] Impossible de trouver l'environnement Conda lerobot :
    echo %PYTHON_EXE%
    echo.
    pause
    exit /b 1
)

echo [1/2] Demarrage du serveur Flask...
echo       Serveur accessible sur : http://127.0.0.1:5000
echo.

:: Ouvrir automatiquement la page dans le navigateur par defaut apres 2 secondes
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:5000"

echo [2/2] Ouverture de l'interface dans votre navigateur...
echo.
echo ========================================================
echo  Pour arreter le serveur : fermez cette fenetre (ou Ctrl+C)
echo ========================================================
echo.

"%PYTHON_EXE%" start_web.py

pause
