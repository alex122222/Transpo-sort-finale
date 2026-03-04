@echo off
echo Installing dependencies...
python -m pip install -r requirements.txt

echo.
echo Starting Transpo-Sort Web App...
python web_app.py
pause
