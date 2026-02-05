SmartShift: Real-Time Shade Tracking and Scheduling Model

Overview:
SmartShift is an intelligent scheduling system that uses urban 3D mapping and solar position modeling to track and predict real-time and forecasted shadow patterns across urban environments. By identifying shaded zones throughout the day, the system generates optimized shift schedules and analyses shadow patterns for urban development. 

Key Features
- 3D Urban Modeling: Uses OSM to build 2D building footprints overlaid with 3D building maps via MapBox API to achieve LOD2 building model centered at Dubai City.
- Solar Path: Calculates solar positions using NOAA Solar Position Calculation Algorithm in Python.
- Shadow Prediction: Predicts sun shadows dynamically throughout the day using two key parameters, i.e, Altitude & Azimuth over shadow polygons. 
- Heat Risk Model: A Simulation-Based Supervised Classification Model using RandomForestClassifier to predict localized heat risk at a given place & time by fetching accurate data upto 7 days through Open-Meteo's official SDK.
- TODO: Intelligent Scheduling Engine: Optimizes worker schedules and pedestrian routes to align with shaded intervals and areas.
- TODO: Real-Time Heat Alerts: Issues automatic warnings when conditions exceed safe exposure thresholds.
- TODO: Dashboard Visualization: Interactive UI for monitoring shadows and worker routes.

System Architecture (Tentative) 
- Data Input Layer:
(Base Layer): MapBox 3D Buildings | 
(Real-time weather data): Open-Meteo SDK  

- Processing Layer:
3D geometry simulation for solar position-based shadow modeling
Heat risk scoring algorithm

- TODO: Optimization Layer:
Worker scheduling engine using dynamic optimization (e.g., linear programming, heuristic search)
Safe-zone prediction module

- TODO: Output Layer:
Shift schedule recommendations
Alert notifications for unsafe conditions
Interactive Web Viewer

Currently under development as part of a 5-month academic project.
Special thanks to University of Birmingham Dubai and supporting mentors for their guidance.
