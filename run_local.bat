@echo off
chcp 65001 >nul
cd /d %~dp0
echo 正在更新教师比赛信息（本机手动运行）...
python -m pip install -r scraper\requirements.txt -q --disable-pip-version-check
python scraper\scrape.py
echo.
pause
