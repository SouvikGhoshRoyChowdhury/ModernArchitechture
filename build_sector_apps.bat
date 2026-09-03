@echo off
setlocal enabledelayedexpansion

echo ==============================================
echo BB ESG Evidence Builder
echo Building Food and Agri, Transport Logistics, and Public
echo ==============================================
echo.

if exist build (
    rmdir /s /q build
)

if not exist dist (
    mkdir dist
)

call :build_sector Food_Agri_ESG_Builder
if errorlevel 1 (
    echo Food and Agri build failed.
    exit /b 1
)

call :build_sector Transport_Logistics_ESG_Builder
if errorlevel 1 (
    echo Transport and Logistics build failed.
    exit /b 1
)

call :build_sector Public_ESG_Builder
if errorlevel 1 (
    echo Public build failed.
    exit /b 1
)

echo.
echo ==============================================
echo All sector applications built successfully.
echo ==============================================
echo.
echo Food and Agri:
echo dist\Food_Agri_ESG_Builder\
echo.
echo Transport and Logistics:
echo dist\Transport_Logistics_ESG_Builder\
echo.
echo Public:
echo dist\Public_ESG_Builder\
echo.

pause
exit /b 0


:build_sector
set APP_NAME=%1

echo.
echo Building %APP_NAME%...
echo.

if exist build\%APP_NAME% (
    rmdir /s /q build\%APP_NAME%
)

if exist dist\%APP_NAME% (
    rmdir /s /q dist\%APP_NAME%
)

pyinstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --name %APP_NAME% ^
    --collect-all streamlit ^
    --collect-all altair ^
    --collect-all pyarrow ^
    --collect-all pymupdf ^
    --collect-all pdfplumber ^
    --add-data "app.py:." ^
    --add-data "config:config" ^
    --add-data "reference:reference" ^
    --add-data ".streamlit:.streamlit" ^
    --hidden-import src.evidence_builder ^
    launcher.py

if errorlevel 1 (
    echo Build failed for %APP_NAME%.
    exit /b 1
)

echo Build completed for %APP_NAME%.
exit /b 0