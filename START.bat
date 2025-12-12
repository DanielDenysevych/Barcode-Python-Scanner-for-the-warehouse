@echo off
echo ========================================
echo Equipment Tracker - Setup and Start
echo ========================================
echo.

echo Installing requirements...
pip install -r requirements.txt

echo.
echo Starting server...
echo.
echo Open your browser and go to: http://localhost:5000
echo Press CTRL+C to stop the server
echo.

python app.py

pause