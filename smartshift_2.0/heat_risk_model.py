"""

this module implements a simulation-based supervised classification model using
randomforestclassifier to predict localized heat risk at a given place and time.

the model answers the question: "is it safe to be outside right now?"

target users:
- municipality workers (road work, maintenance)
- construction workers (outdoor labor)
- building facade cleaners (need to work in shade/shadow)
- joggers, cyclists, and pedestrians (want less sunny routes)

-----------------------------
📥 data sources & inputs
-----------------------------

| input                  | source                          | how to get it                    |
|------------------------|---------------------------------|----------------------------------|
| sun_exposure_duration  | shadow engine (this project)    | from shadow_calculator.py        |
| time_of_day            | system timestamp                | datetime.now()                   |
| temperature            | era5 / meteostat                | pip install meteostat            |
| humidity               | era5 / meteostat                | same as above                    |
| wind_speed             | era5 / meteostat                | same as above                    |
| surface_type           | osm / mapbox                    | mapbox api or osm overpass       |
| past_exposure_window   | derived feature                 | rolling sum of sun exposure      |

weather data sources:
- meteostat: free historical weather api (pip install meteostat)
  docs: https://dev.meteostat.net/python/
- era5: copernicus climate data store (requires account)
  docs: https://cds.climate.copernicus.eu/

surface type data:
- openstreetmap: query via overpass api for surface tags
- mapbox: land use data via mapbox tilequery api

-----------------------------
📤 model output
-----------------------------

heat risk classification:
- 0 = low risk (safe for extended outdoor activity)
- 1 = medium risk (limit exposure, take breaks)
- 2 = high risk (avoid outdoor work if possible)

alternative output:
- probability of unsafe exposure (0.0 to 1.0)

-----------------------------
🏷️ training labels (synthetic)
-----------------------------

labels are generated from established heat stress indices:
- wbgt (wet bulb globe temperature) - industry standard
- osha/niosh heat stress thresholds
- dubai municipality outdoor work guidelines

wbgt formula (simplified):
wbgt = 0.7 * wet_bulb_temp + 0.2 * globe_temp + 0.1 * dry_bulb_temp

risk thresholds (based on osha):
- low:    wbgt < 25°c or heat index < 32°c
- medium: wbgt 25-28°c or heat index 32-40°c
- high:   wbgt > 28°c or heat index > 40°c

"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Tuple, List, Dict, Optional, Any
from dataclasses import dataclass, field
import pickle
import os
import math

# ml imports
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import classification_report, confusion_matrix
import joblib

# import project modules
from config import DUBAI, HEAT_SAFETY
from solar_position import SolarPositionCalculator


# -----------------------------------------------------------------------------
# data classes for structured inputs
# -----------------------------------------------------------------------------

@dataclass
class WeatherData:
    """
    weather data container for a specific time and location.

    all values use metric units (celsius, km/h, percent).
    """
    temperature: float          # celsius - from meteostat/era5
    humidity: float             # percentage (0-100) - from meteostat/era5
    wind_speed: float           # km/h - from meteostat/era5
    pressure: float = 1013.0    # hpa (optional)
    cloud_cover: float = 0.0    # percentage (0-100, optional)
    uv_index: float = 5.0       # 0-11+ scale (optional)


@dataclass
class LocationContext:
    """
    contextual information about the location.

    surface types affect heat absorption and re-radiation:
    - asphalt: absorbs heat, radiates back (high risk multiplier)
    - concrete: moderate heat absorption
    - grass: cooler due to evapotranspiration
    - sand: very hot in direct sun
    - water: cooling effect nearby
    """
    latitude: float
    longitude: float
    surface_type: str           # 'asphalt', 'concrete', 'grass', 'sand', 'water', 'mixed'
    elevation: float = 0.0      # meters above sea level
    urban_density: float = 0.5  # 0.0 (rural) to 1.0 (dense urban)


@dataclass
class SunExposure:
    """
    sun exposure data derived from the shadow engine.

    this is the key integration point with the existing shadow simulation.
    """
    is_in_shadow: bool              # currently in building shadow?
    current_sun_altitude: float     # degrees above horizon
    current_sun_azimuth: float      # compass direction of sun
    minutes_in_sun_last_hour: float # rolling exposure
    direct_sun_intensity: float     # 0.0 (shade) to 1.0 (full sun)


@dataclass
class HeatRiskPrediction:
    """
    output from the heat risk model.
    """
    risk_level: int                 # 0=low, 1=medium, 2=high
    risk_label: str                 # 'low', 'medium', 'high'
    risk_probability: float         # confidence of predicted class
    class_probabilities: Dict[str, float]  # probabilities for each class
    wbgt_estimate: float            # estimated wet bulb globe temp
    heat_index: float               # calculated heat index
    recommended_max_exposure: int   # minutes of safe sun exposure
    safety_message: str             # human-readable safety advice


# -----------------------------------------------------------------------------
# heat index and wbgt calculations
# -----------------------------------------------------------------------------

def calculate_heat_index(temperature: float, humidity: float) -> float:
    """
    calculate heat index (feels like temperature) using noaa formula.

    the heat index combines air temperature and relative humidity to
    determine the human-perceived equivalent temperature.

    args:
        temperature: air temperature in celsius
        humidity: relative humidity as percentage (0-100)

    returns:
        heat index in celsius

    reference: https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml
    """
    # convert to fahrenheit for the noaa formula
    t_f = (temperature * 9/5) + 32
    rh = humidity

    # simple formula for lower temperatures
    if t_f < 80:
        hi_f = 0.5 * (t_f + 61.0 + ((t_f - 68.0) * 1.2) + (rh * 0.094))
    else:
        # full regression equation
        hi_f = (-42.379 +
                2.04901523 * t_f +
                10.14333127 * rh -
                0.22475541 * t_f * rh -
                0.00683783 * t_f**2 -
                0.05481717 * rh**2 +
                0.00122874 * t_f**2 * rh +
                0.00085282 * t_f * rh**2 -
                0.00000199 * t_f**2 * rh**2)

        # adjustments for extreme conditions
        if rh < 13 and 80 <= t_f <= 112:
            adjustment = ((13 - rh) / 4) * math.sqrt((17 - abs(t_f - 95)) / 17)
            hi_f -= adjustment
        elif rh > 85 and 80 <= t_f <= 87:
            adjustment = ((rh - 85) / 10) * ((87 - t_f) / 5)
            hi_f += adjustment

    # convert back to celsius
    return (hi_f - 32) * 5/9


def estimate_wbgt(temperature: float, humidity: float,
                  wind_speed: float, sun_exposure: float,
                  cloud_cover: float = 0.0) -> float:
    """
    estimate wet bulb globe temperature (wbgt) for heat stress assessment.

    wbgt is the gold standard for occupational heat stress assessment,
    used by osha, niosh, and military organizations worldwide.

    this is a simplified estimation - true wbgt requires specialized
    instruments measuring wet bulb, globe, and dry bulb temperatures.

    args:
        temperature: air temperature in celsius
        humidity: relative humidity as percentage
        wind_speed: wind speed in km/h
        sun_exposure: 0.0 (full shade) to 1.0 (full sun)
        cloud_cover: percentage cloud cover

    returns:
        estimated wbgt in celsius

    reference: liljegren et al. (2008) modeling wet bulb globe temperature
    """
    # estimate wet bulb temperature using humidity
    # simplified psychrometric calculation
    wet_bulb = temperature * math.atan(0.151977 * math.sqrt(humidity + 8.313659)) + \
               math.atan(temperature + humidity) - \
               math.atan(humidity - 1.676331) + \
               0.00391838 * humidity**1.5 * math.atan(0.023101 * humidity) - 4.686035

    # estimate globe temperature based on sun exposure and wind
    # globe temp is higher than air temp in direct sunlight
    solar_radiation = 1000 * sun_exposure * (1 - cloud_cover/100)  # w/m^2 estimate

    # wind cooling effect on globe temperature
    wind_factor = max(0.1, 1 - (wind_speed / 50))  # reduces with wind

    globe_temp = temperature + (solar_radiation / 100) * wind_factor

    # standard wbgt formula for outdoor conditions with sun
    # wbgt = 0.7 * twb + 0.2 * tg + 0.1 * ta
    wbgt = 0.7 * wet_bulb + 0.2 * globe_temp + 0.1 * temperature

    return wbgt


def get_risk_level_from_wbgt(wbgt: float) -> Tuple[int, str]:
    """
    determine risk level from wbgt using osha/niosh thresholds.

    these thresholds are for acclimatized workers doing moderate work.
    non-acclimatized workers or heavy work should use lower thresholds.

    args:
        wbgt: wet bulb globe temperature in celsius

    returns:
        tuple of (risk_level_int, risk_label_string)
    """
    # osha action levels for moderate workload, acclimatized workers
    if wbgt < 25.0:
        return 0, 'low'
    elif wbgt < 28.0:
        return 1, 'medium'
    else:
        return 2, 'high'


def get_recommended_exposure(risk_level: int, wbgt: float) -> int:
    """
    get recommended maximum continuous sun exposure in minutes.

    based on niosh work/rest schedules for heat stress.

    args:
        risk_level: 0=low, 1=medium, 2=high
        wbgt: wet bulb globe temperature

    returns:
        recommended max minutes of continuous exposure
    """
    if risk_level == 0:
        return 120  # 2 hours continuous work ok
    elif risk_level == 1:
        # graduated based on wbgt
        if wbgt < 26:
            return 60  # 1 hour, then 15 min rest
        else:
            return 45  # 45 min, then 15 min rest
    else:
        # high risk
        if wbgt < 30:
            return 30  # 30 min work, 30 min rest
        elif wbgt < 32:
            return 15  # 15 min work, 45 min rest
        else:
            return 0   # avoid outdoor work


def get_safety_message(risk_level: int, recommended_exposure: int) -> str:
    """
    generate human-readable safety advice based on risk assessment.

    messages are designed for workers and community members.
    """
    messages = {
        0: f"conditions are safe for outdoor activity. stay hydrated and take normal precautions. recommended max continuous exposure: {recommended_exposure} minutes.",
        1: f"moderate heat risk. limit continuous sun exposure to {recommended_exposure} minutes, take regular shade breaks, and drink water every 15-20 minutes.",
        2: f"high heat risk! minimize outdoor exposure. work in shade when possible. max {recommended_exposure} min in sun, then mandatory rest in shade/ac. watch for heat illness symptoms."
    }

    if recommended_exposure == 0:
        return "extreme heat danger! avoid all non-essential outdoor work. if work is necessary, use continuous shade and cooling measures."

    return messages.get(risk_level, messages[1])


# -----------------------------------------------------------------------------
# feature engineering for ml model
# -----------------------------------------------------------------------------

@dataclass
class HeatRiskFeatures:
    """
    engineered features for the ml model.

    these features are derived from raw inputs and domain knowledge.
    """
    # time features (cyclic encoding for periodicity)
    hour_sin: float             # sin(2π * hour/24) - captures daily cycle
    hour_cos: float             # cos(2π * hour/24) - captures daily cycle
    month_sin: float            # sin(2π * month/12) - captures seasonal cycle
    month_cos: float            # cos(2π * month/12) - captures seasonal cycle

    # weather features
    temperature: float
    humidity: float
    wind_speed: float
    heat_index: float           # derived

    # sun/shadow features
    sun_altitude: float         # degrees
    sun_intensity: float        # 0-1
    shadow_coverage: float      # 0-1 (1 = fully shaded)
    cumulative_exposure: float  # minutes in last hour

    # location features
    surface_heat_factor: float  # multiplier based on surface type
    urban_heat_island: float    # additional heat from urban density

    # combined risk indicators
    wbgt_estimate: float        # wet bulb globe temp estimate


def encode_time_cyclic(value: float, max_value: float) -> Tuple[float, float]:
    """
    encode time values as cyclic features using sin/cos transformation.

    this encoding ensures that e.g., hour 23 is close to hour 0,
    which wouldn't be captured by simple normalization.

    args:
        value: the time value (e.g., hour 0-23, month 1-12)
        max_value: the maximum value in the cycle (24 for hours, 12 for months)

    returns:
        tuple of (sin_encoding, cos_encoding)
    """
    angle = 2 * math.pi * value / max_value
    return math.sin(angle), math.cos(angle)


def get_surface_heat_factor(surface_type: str) -> float:
    """
    get heat absorption/radiation factor for different surface types.

    these factors represent how much a surface contributes to local
    heat stress beyond air temperature alone.

    data based on urban heat island studies.

    args:
        surface_type: type of ground surface

    returns:
        multiplier for heat risk (1.0 = neutral)
    """
    surface_factors = {
        'asphalt': 1.3,     # black asphalt absorbs lots of heat
        'concrete': 1.15,   # lighter but still absorbs heat
        'brick': 1.1,       # moderate heat absorption
        'sand': 1.25,       # very hot in direct sun
        'grass': 0.85,      # cooler due to evapotranspiration
        'water': 0.7,       # cooling effect from evaporation
        'trees': 0.75,      # shade + evapotranspiration
        'mixed': 1.0,       # default urban mix
    }
    return surface_factors.get(surface_type.lower(), 1.0)


def get_urban_heat_island_effect(urban_density: float) -> float:
    """
    estimate additional temperature from urban heat island effect.

    dense urban areas can be 2-5°c warmer than surrounding areas
    due to heat absorption by buildings, reduced vegetation, and
    waste heat from ac/vehicles.

    args:
        urban_density: 0.0 (rural) to 1.0 (dense urban)

    returns:
        additional temperature in celsius
    """
    # maximum uhi effect of 4°c at full urban density
    return urban_density * 4.0


def extract_features(weather: WeatherData,
                     location: LocationContext,
                     sun_exposure: SunExposure,
                     timestamp: datetime) -> HeatRiskFeatures:
    """
    extract and engineer features from raw input data.

    this is the main feature engineering function that prepares
    data for the ml model.

    args:
        weather: weather data from meteostat/era5
        location: location context including surface type
        sun_exposure: exposure data from shadow engine
        timestamp: current datetime

    returns:
        HeatRiskFeatures dataclass ready for model input
    """
    # encode time cyclically
    hour_sin, hour_cos = encode_time_cyclic(timestamp.hour + timestamp.minute/60, 24)
    month_sin, month_cos = encode_time_cyclic(timestamp.month, 12)

    # calculate derived features
    heat_index = calculate_heat_index(weather.temperature, weather.humidity)
    surface_factor = get_surface_heat_factor(location.surface_type)
    uhi_effect = get_urban_heat_island_effect(location.urban_density)

    # effective temperature including local effects
    effective_temp = weather.temperature + uhi_effect

    # calculate wbgt estimate
    wbgt = estimate_wbgt(
        temperature=effective_temp,
        humidity=weather.humidity,
        wind_speed=weather.wind_speed,
        sun_exposure=sun_exposure.direct_sun_intensity,
        cloud_cover=weather.cloud_cover
    )

    return HeatRiskFeatures(
        hour_sin=hour_sin,
        hour_cos=hour_cos,
        month_sin=month_sin,
        month_cos=month_cos,
        temperature=effective_temp,
        humidity=weather.humidity,
        wind_speed=weather.wind_speed,
        heat_index=heat_index,
        sun_altitude=sun_exposure.current_sun_altitude,
        sun_intensity=sun_exposure.direct_sun_intensity,
        shadow_coverage=1.0 if sun_exposure.is_in_shadow else 0.0,
        cumulative_exposure=sun_exposure.minutes_in_sun_last_hour,
        surface_heat_factor=surface_factor,
        urban_heat_island=uhi_effect,
        wbgt_estimate=wbgt
    )


def features_to_array(features: HeatRiskFeatures) -> np.ndarray:
    """
    convert HeatRiskFeatures to numpy array for model input.

    feature order must match training data exactly.
    """
    return np.array([
        features.hour_sin,
        features.hour_cos,
        features.month_sin,
        features.month_cos,
        features.temperature,
        features.humidity,
        features.wind_speed,
        features.heat_index,
        features.sun_altitude,
        features.sun_intensity,
        features.shadow_coverage,
        features.cumulative_exposure,
        features.surface_heat_factor,
        features.urban_heat_island,
        features.wbgt_estimate
    ])


# -----------------------------------------------------------------------------
# synthetic data generation for training
# -----------------------------------------------------------------------------

def generate_synthetic_training_data(n_samples: int = 10000,
                                     random_seed: int = 42) -> Tuple[np.ndarray, np.ndarray]:
    """
    generate synthetic training data using physics-based simulation.

    since we don't have labeled historical data, we generate training
    data by simulating various conditions and labeling them based on
    established heat stress thresholds (wbgt, osha guidelines).

    this is a valid approach because:
    1. the physics of heat stress are well understood
    2. osha/niosh thresholds are empirically validated
    3. the model learns to interpolate between known conditions

    args:
        n_samples: number of training samples to generate
        random_seed: for reproducibility

    returns:
        tuple of (features_array, labels_array)
    """
    np.random.seed(random_seed)

    features_list = []
    labels_list = []

    # dubai-specific ranges for realistic simulation
    # temperatures vary by season and time of day

    for _ in range(n_samples):
        # randomly sample month (1-12) with dubai seasonality
        month = np.random.randint(1, 13)

        # temperature depends on month (dubai climate)
        # summer (may-sep): 35-48°c, winter (nov-mar): 18-28°c
        if month in [6, 7, 8, 9]:  # peak summer
            base_temp = np.random.uniform(35, 48)
        elif month in [5, 10]:  # shoulder summer
            base_temp = np.random.uniform(30, 40)
        elif month in [11, 12, 1, 2, 3]:  # winter
            base_temp = np.random.uniform(18, 28)
        else:  # spring (april)
            base_temp = np.random.uniform(25, 35)

        # hour of day affects temperature
        hour = np.random.uniform(0, 24)

        # diurnal temperature variation
        # peak around 2-4pm, lowest around 5-6am
        hour_factor = math.sin((hour - 6) * math.pi / 12)
        temp_variation = hour_factor * 8  # ±8°c variation
        temperature = base_temp + temp_variation

        # humidity (inversely correlated with temp in dubai)
        if temperature > 40:
            humidity = np.random.uniform(15, 40)
        elif temperature > 30:
            humidity = np.random.uniform(30, 60)
        else:
            humidity = np.random.uniform(40, 80)

        # wind speed (0-40 km/h typical)
        wind_speed = np.random.exponential(8)  # most days light wind
        wind_speed = min(wind_speed, 50)

        # sun exposure and shadow (depends on time of day)
        solar_calc = SolarPositionCalculator(
            latitude=DUBAI.LATITUDE,
            longitude=DUBAI.LONGITUDE,
            timezone_offset=DUBAI.TIMEZONE_OFFSET
        )

        # create a sample datetime
        sample_date = datetime(2024, month, 15, int(hour), int((hour % 1) * 60))
        sun_pos = solar_calc.get_sun_position(sample_date)

        sun_altitude = max(0, sun_pos.altitude)

        # sun intensity based on altitude
        if sun_altitude > 0:
            sun_intensity = min(1.0, sun_altitude / 60)  # peaks at 60°
        else:
            sun_intensity = 0.0

        # random shadow coverage (0 = no shade, 1 = full shade)
        shadow_coverage = np.random.uniform(0, 1)

        # effective sun intensity reduced by shadow
        effective_sun = sun_intensity * (1 - shadow_coverage)

        # cumulative exposure (0-60 minutes in last hour)
        cumulative_exposure = np.random.uniform(0, 60) * (1 - shadow_coverage)

        # surface type (randomly sampled)
        surface_types = ['asphalt', 'concrete', 'grass', 'sand', 'mixed']
        surface_type = np.random.choice(surface_types)
        surface_factor = get_surface_heat_factor(surface_type)

        # urban density
        urban_density = np.random.uniform(0.2, 0.9)  # dubai is mostly urban
        uhi_effect = get_urban_heat_island_effect(urban_density)

        # adjust temperature for local effects
        effective_temp = temperature + uhi_effect * effective_sun

        # encode time cyclically
        hour_sin, hour_cos = encode_time_cyclic(hour, 24)
        month_sin, month_cos = encode_time_cyclic(month, 12)

        # calculate derived metrics
        heat_index = calculate_heat_index(effective_temp, humidity)
        wbgt = estimate_wbgt(effective_temp, humidity, wind_speed,
                           effective_sun, cloud_cover=0)

        # create feature vector
        features = np.array([
            hour_sin,
            hour_cos,
            month_sin,
            month_cos,
            effective_temp,
            humidity,
            wind_speed,
            heat_index,
            sun_altitude,
            effective_sun,
            shadow_coverage,
            cumulative_exposure,
            surface_factor,
            uhi_effect,
            wbgt
        ])

        # generate label based on wbgt and heat index
        # use combination of metrics for more robust labels
        risk_level, _ = get_risk_level_from_wbgt(wbgt)

        # additional factors that increase risk
        if heat_index > 45:
            risk_level = min(2, risk_level + 1)
        if cumulative_exposure > 45 and risk_level < 2:
            risk_level = min(2, risk_level + 1)
        if surface_factor > 1.2 and effective_sun > 0.7:
            risk_level = min(2, risk_level + 1)

        # shade significantly reduces risk
        if shadow_coverage > 0.7:
            risk_level = max(0, risk_level - 1)

        features_list.append(features)
        labels_list.append(risk_level)

    return np.array(features_list), np.array(labels_list)


# -----------------------------------------------------------------------------
# ml model class
# -----------------------------------------------------------------------------

class HeatRiskModel:
    """
    heat risk prediction model using random forest classification.

    this model predicts localized heat risk based on weather, time,
    location, and sun exposure data. it integrates with the shadow
    engine to provide real-time risk assessments.

    usage:
        # initialize and train
        model = HeatRiskModel()
        model.train()

        # make predictions
        prediction = model.predict(weather, location, sun_exposure, timestamp)
        print(f"risk level: {prediction.risk_label}")
    """

    # feature names for reference
    FEATURE_NAMES = [
        'hour_sin', 'hour_cos', 'month_sin', 'month_cos',
        'temperature', 'humidity', 'wind_speed', 'heat_index',
        'sun_altitude', 'sun_intensity', 'shadow_coverage',
        'cumulative_exposure', 'surface_heat_factor',
        'urban_heat_island', 'wbgt_estimate'
    ]

    RISK_LABELS = ['low', 'medium', 'high']

    def __init__(self, model_path: Optional[str] = None):
        """
        initialize the heat risk model.

        args:
            model_path: path to saved model file (optional)
        """
        self.model: Optional[RandomForestClassifier] = None
        self.scaler: Optional[StandardScaler] = None
        self.is_trained: bool = False
        self.model_path = model_path or 'heat_risk_model.pkl'

        # try to load existing model
        if os.path.exists(self.model_path):
            self.load_model(self.model_path)

    def train(self, n_samples: int = 10000, test_size: float = 0.2,
              verbose: bool = True) -> Dict[str, Any]:
        """
        train the model on synthetic data.

        generates synthetic training data based on physics-based
        simulation and established heat stress thresholds.

        args:
            n_samples: number of training samples
            test_size: fraction of data for testing
            verbose: print training progress

        returns:
            dictionary with training metrics
        """
        if verbose:
            print("generating synthetic training data...")

        # generate training data
        X, y = generate_synthetic_training_data(n_samples)

        if verbose:
            print(f"generated {n_samples} samples")
            print(f"class distribution: {np.bincount(y)}")

        # split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )

        # scale features
        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        if verbose:
            print("training random forest classifier...")

        # train model
        self.model = RandomForestClassifier(
            n_estimators=100,           # number of trees
            max_depth=15,               # prevent overfitting
            min_samples_split=5,        # minimum samples to split
            min_samples_leaf=2,         # minimum samples in leaf
            class_weight='balanced',    # handle class imbalance
            random_state=42,
            n_jobs=-1                   # use all cpu cores
        )

        self.model.fit(X_train_scaled, y_train)
        self.is_trained = True

        # evaluate
        y_pred = self.model.predict(X_test_scaled)

        # cross-validation score
        cv_scores = cross_val_score(self.model, X_train_scaled, y_train, cv=5)

        metrics = {
            'accuracy': (y_pred == y_test).mean(),
            'cv_mean': cv_scores.mean(),
            'cv_std': cv_scores.std(),
            'classification_report': classification_report(
                y_test, y_pred, target_names=self.RISK_LABELS, output_dict=True
            ),
            'confusion_matrix': confusion_matrix(y_test, y_pred).tolist(),
            'feature_importance': dict(zip(
                self.FEATURE_NAMES,
                self.model.feature_importances_.tolist()
            ))
        }

        if verbose:
            print(f"\nmodel accuracy: {metrics['accuracy']:.3f}")
            print(f"cross-validation: {metrics['cv_mean']:.3f} (+/- {metrics['cv_std']:.3f})")
            print("\nclassification report:")
            print(classification_report(y_test, y_pred, target_names=self.RISK_LABELS))
            print("\nfeature importance (top 5):")
            importance = sorted(
                metrics['feature_importance'].items(),
                key=lambda x: x[1], reverse=True
            )[:5]
            for name, imp in importance:
                print(f"  {name}: {imp:.3f}")

        # save model
        self.save_model(self.model_path)

        return metrics

    def predict(self, weather: WeatherData, location: LocationContext,
                sun_exposure: SunExposure, timestamp: datetime) -> HeatRiskPrediction:
        """
        predict heat risk for given conditions.

        this is the main prediction method used during inference.

        args:
            weather: current weather data
            location: location context
            sun_exposure: sun exposure from shadow engine
            timestamp: current datetime

        returns:
            HeatRiskPrediction with risk level and recommendations
        """
        if not self.is_trained:
            raise RuntimeError("model not trained. call train() first.")

        # extract features
        features = extract_features(weather, location, sun_exposure, timestamp)
        X = features_to_array(features).reshape(1, -1)

        # scale features
        X_scaled = self.scaler.transform(X)

        # get prediction and probabilities
        risk_level = int(self.model.predict(X_scaled)[0])
        probabilities = self.model.predict_proba(X_scaled)[0]

        risk_label = self.RISK_LABELS[risk_level]

        # calculate additional metrics
        wbgt = features.wbgt_estimate
        heat_index = features.heat_index
        recommended_exposure = get_recommended_exposure(risk_level, wbgt)
        safety_message = get_safety_message(risk_level, recommended_exposure)

        return HeatRiskPrediction(
            risk_level=risk_level,
            risk_label=risk_label,
            risk_probability=float(probabilities[risk_level]),
            class_probabilities={
                'low': float(probabilities[0]),
                'medium': float(probabilities[1]),
                'high': float(probabilities[2])
            },
            wbgt_estimate=wbgt,
            heat_index=heat_index,
            recommended_max_exposure=recommended_exposure,
            safety_message=safety_message
        )

    def predict_batch(self, conditions: List[Dict]) -> List[HeatRiskPrediction]:
        """
        predict heat risk for multiple conditions at once.

        useful for generating predictions across a day or route.

        args:
            conditions: list of dicts with weather, location, sun_exposure, timestamp

        returns:
            list of HeatRiskPrediction objects
        """
        return [
            self.predict(
                weather=c['weather'],
                location=c['location'],
                sun_exposure=c['sun_exposure'],
                timestamp=c['timestamp']
            )
            for c in conditions
        ]

    def save_model(self, path: str):
        """save trained model to disk."""
        if not self.is_trained:
            raise RuntimeError("no trained model to save")

        data = {
            'model': self.model,
            'scaler': self.scaler,
            'feature_names': self.FEATURE_NAMES
        }
        joblib.dump(data, path)
        print(f"model saved to {path}")

    def load_model(self, path: str):
        """load trained model from disk."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"model file not found: {path}")

        data = joblib.load(path)
        self.model = data['model']
        self.scaler = data['scaler']
        self.is_trained = True
        print(f"model loaded from {path}")

    def get_feature_importance(self) -> Dict[str, float]:
        """get feature importance from trained model."""
        if not self.is_trained:
            raise RuntimeError("model not trained")

        return dict(zip(self.FEATURE_NAMES, self.model.feature_importances_.tolist()))


# -----------------------------------------------------------------------------
# convenience functions for api integration
# -----------------------------------------------------------------------------

def create_sun_exposure_from_shadow_analysis(
    shadow_analysis,  # ShadowAnalysis from shadow_calculator.py
    point_lat: float,
    point_lon: float,
    minutes_tracked: float = 30.0
) -> SunExposure:
    """
    create SunExposure object from shadow analysis data.

    this function bridges the gap between the shadow engine output
    and the heat risk model input.

    args:
        shadow_analysis: ShadowAnalysis from shadow_calculator.calculate_shadows_for_buildings()
        point_lat: latitude of the point to check
        point_lon: longitude of the point to check
        minutes_tracked: assumed minutes of sun exposure to use

    returns:
        SunExposure object for model input
    """
    # get sun position from analysis
    sun_pos = shadow_analysis.sun_position

    # check if point is in any shadow (simplified - would need proper point-in-polygon check)
    # for now, assume not in shadow if far from shadow centroids
    is_in_shadow = False  # simplified - implement proper check with shapely if needed

    # calculate sun intensity based on altitude
    if sun_pos.altitude > 0:
        sun_intensity = min(1.0, sun_pos.altitude / 60)
    else:
        sun_intensity = 0.0

    return SunExposure(
        is_in_shadow=is_in_shadow,
        current_sun_altitude=max(0, sun_pos.altitude),
        current_sun_azimuth=sun_pos.azimuth,
        minutes_in_sun_last_hour=minutes_tracked,
        direct_sun_intensity=sun_intensity if not is_in_shadow else 0.0
    )


# -----------------------------------------------------------------------------
# main - demonstration and testing
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("smartshift heat risk prediction model")
    print("=" * 70)

    # initialize model
    model = HeatRiskModel()

    # train if not already trained
    if not model.is_trained:
        print("\ntraining model on synthetic data...")
        metrics = model.train(n_samples=10000, verbose=True)

    # demonstrate prediction
    print("\n" + "-" * 70)
    print("sample prediction for dubai conditions")
    print("-" * 70)

    # create sample inputs
    weather = WeatherData(
        temperature=42.0,   # hot summer day
        humidity=35.0,      # moderate humidity
        wind_speed=10.0,    # light breeze
        cloud_cover=0.0     # clear sky
    )

    location = LocationContext(
        latitude=25.2048,
        longitude=55.2708,
        surface_type='asphalt',
        urban_density=0.8
    )

    sun_exposure = SunExposure(
        is_in_shadow=False,
        current_sun_altitude=65.0,
        current_sun_azimuth=180.0,
        minutes_in_sun_last_hour=45.0,
        direct_sun_intensity=0.9
    )

    timestamp = datetime(2024, 7, 15, 14, 0)  # 2pm in summer

    # get prediction
    prediction = model.predict(weather, location, sun_exposure, timestamp)

    print(f"\nconditions:")
    print(f"  temperature: {weather.temperature}°c")
    print(f"  humidity: {weather.humidity}%")
    print(f"  surface: {location.surface_type}")
    print(f"  in shadow: {sun_exposure.is_in_shadow}")

    print(f"\nprediction:")
    print(f"  risk level: {prediction.risk_label.upper()} ({prediction.risk_level})")
    print(f"  confidence: {prediction.risk_probability:.1%}")
    print(f"  wbgt estimate: {prediction.wbgt_estimate:.1f}°c")
    print(f"  heat index: {prediction.heat_index:.1f}°c")
    print(f"  max safe exposure: {prediction.recommended_max_exposure} minutes")
    print(f"\n  {prediction.safety_message}")

    # show prediction in shadow
    print("\n" + "-" * 70)
    print("same conditions but in building shadow:")
    print("-" * 70)

    sun_exposure_shadow = SunExposure(
        is_in_shadow=True,
        current_sun_altitude=65.0,
        current_sun_azimuth=180.0,
        minutes_in_sun_last_hour=10.0,  # mostly in shade
        direct_sun_intensity=0.0        # no direct sun
    )

    prediction_shadow = model.predict(weather, location, sun_exposure_shadow, timestamp)

    print(f"\nprediction (in shadow):")
    print(f"  risk level: {prediction_shadow.risk_label.upper()} ({prediction_shadow.risk_level})")
    print(f"  confidence: {prediction_shadow.risk_probability:.1%}")
    print(f"  max safe exposure: {prediction_shadow.recommended_max_exposure} minutes")
    print(f"\n  {prediction_shadow.safety_message}")

    print("\n" + "=" * 70)
    print("model ready for integration with smartshift api")
    print("=" * 70)

