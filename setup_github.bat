@echo off
chcp 65001 >nul
set HOSTS=%SystemRoot%\System32\drivers\etc\hosts
findstr /c:"140.82.112.4 github.com" "%HOSTS%" >nul 2>nul || >>"%HOSTS%" echo 140.82.112.4 github.com
findstr /c:"140.82.112.4 www.github.com" "%HOSTS%" >nul 2>nul || >>"%HOSTS%" echo 140.82.112.4 www.github.com
ipconfig /flushdns >nul
echo hosts 文件已更新，GitHub 现在可以访问了！
echo.
pause
