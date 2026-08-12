\
@echo off
chcp 65001 >nul
title MarketSim AI - Kiem tra an toan
cd /d "%~dp0"
echo ================================================
echo   MarketSim AI - Kiem tra truoc khi cap nhat
echo ================================================
python VERIFY_MARKETSIM_ENTERPRISE.py
if errorlevel 1 (
  echo.
  echo KET QUA: Co muc chua dat. Khong nen deploy truoc khi sua xong.
) else (
  echo.
  echo KET QUA: Tat ca kiem tra quan trong deu dat.
)
echo.
pause
