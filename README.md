## SmartShift: Real-Time Shade Tracking Model with Scheduling and Navigation Engines

SmartShift is an intelligent scheduling system that uses urban 3D mapping and solar position modeling to track and predict real-time and forecasted shadow patterns across urban environments. By identifying shaded zones throughout the day, the system generates optimized shift schedules and analyses shadow patterns for urban development. 

Key Features
- **3D Urban Modeling**: Uses 3D building maps via MapBox API to achieve LOD2 building model centered at Dubai City.
- **Solar Path**: Calculates solar positions using NOAA Solar Position Calculation Algorithm in Python.
- **Shadow Prediction**: Predicts sun shadows dynamically throughout the day using two key parameters, i.e, Altitude & Azimuth over shadow polygons. 
- **Heat Risk Model**: A Simulation-Based Supervised Classification Model using RandomForestClassifier to predict localized heat risk at a given place & time by fetching accurate data upto 7 days through Open-Meteo's official SDK.
- **Intelligent Scheduling & Routing Engine**: Generates worker schedules and pedestrian routes recommendations based on highest shadow exposure.

## How to run
**Prerequisites:** Python 3.10+, [Node.js](https://nodejs.org/) and **npm**. Mapbox / Google API keys in `smartshift_2.0/backend/.env` for full map and directions features.

### 1. Backend API (Flask)
```bash
cd smartshift_2.0/backend
pip install -r requirements.txt
python api_server.py
```

### 2. Frontend (Vite + React)
In a second terminal:
```bash
cd smartshift_2.0/frontend
npm install
npm run dev
```
Dev UI is served on **`http://localhost:8080`** - run the backend first.

### 3. Tests (pytest)
```bash
cd smartshift_2.0
pip install pytest
python -m pytest tests -v
```
