"""
Solar Position Calculator for Dubai Sun-Shadow Simulation
==========================================================

This module calculates the sun's position (azimuth and altitude) for any given
date, time, and geographic location. It uses NOAA astronomical algorithms to compute
accurate solar positions needed for shadow projection.

"""

import math
from datetime import datetime, timezone
from typing import Tuple, Dict, Optional
from dataclasses import dataclass


@dataclass
class SunPosition:
    """
    Represents the sun's position in the sky.

    Attributes:
        azimuth: Compass direction in degrees (0-360, clockwise from North)
        altitude: Elevation angle in degrees (-90 to 90, above/below horizon)
        zenith: Angle from directly overhead (90 - altitude)
        is_daylight: Whether sun is above the horizon
        solar_noon: Time of solar noon for the day
        sunrise: Sunrise time (None if no sunrise)
        sunset: Sunset time (None if no sunset)
    """
    azimuth: float
    altitude: float
    zenith: float
    is_daylight: bool
    solar_noon: Optional[datetime] = None
    sunrise: Optional[datetime] = None
    sunset: Optional[datetime] = None


class SolarPositionCalculator:
    """
    Calculates sun position using NOAA Solar Calculator algorithms.

    This implementation is based on the algorithms used by NOAA's
    Solar Calculator, which provides accurate results for dates
    between 1901 and 2099.

    Reference: https://gml.noaa.gov/grad/solcalc/calcdetails.html
    """

    def __init__(self, latitude: float, longitude: float, timezone_offset: float = 4.0):
        """
        Initialize the calculator for a specific location.

        Args:
            latitude: Latitude in decimal degrees (positive = North)
            longitude: Longitude in decimal degrees (positive = East)
            timezone_offset: Hours offset from UTC (Dubai = +4)
        """
        self.latitude = latitude
        self.longitude = longitude
        self.timezone_offset = timezone_offset

        # Validate coordinates
        if not -90 <= latitude <= 90:
            raise ValueError(f"Latitude must be between -90 and 90, got {latitude}")
        if not -180 <= longitude <= 180:
            raise ValueError(f"Longitude must be between -180 and 180, got {longitude}")

    def calculate_julian_day(self, dt: datetime) -> float:
        """
        Convert a datetime to Julian Day Number.

        The Julian Day is a continuous count of days since the beginning
        of the Julian Period (January 1, 4713 BC in the Julian calendar).

        Args:
            dt: Datetime object (should be in UTC or timezone-aware)

        Returns:
            Julian Day Number as a float
        """
        # Extract components
        year = dt.year
        month = dt.month
        day = dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0

        # Adjust for January and February (treat as months 13 and 14 of previous year)
        if month <= 2:
            year -= 1
            month += 12

        # Calculate Julian Day using the standard formula
        A = int(year / 100)
        B = 2 - A + int(A / 4)

        julian_day = (int(365.25 * (year + 4716)) +
                      int(30.6001 * (month + 1)) +
                      day + B - 1524.5)

        return julian_day

    def calculate_julian_century(self, julian_day: float) -> float:
        """
        Convert Julian Day to Julian Century.

        Julian Century is the number of centuries since J2000.0
        (January 1, 2000, 12:00 TT).

        Args:
            julian_day: Julian Day Number

        Returns:
            Julian Century value
        """
        return (julian_day - 2451545.0) / 36525.0

    def calculate_geometric_mean_longitude(self, julian_century: float) -> float:
        """
        Calculate the geometric mean longitude of the sun.

        This is the mean longitude of the sun, corrected for aberration,
        referred to the mean equinox of date.

        Args:
            julian_century: Julian Century value

        Returns:
            Geometric mean longitude in degrees (0-360)
        """
        L0 = (280.46646 +
              julian_century * (36000.76983 + 0.0003032 * julian_century))

        # Normalize to 0-360 range
        return L0 % 360

    def calculate_geometric_mean_anomaly(self, julian_century: float) -> float:
        """
        Calculate the geometric mean anomaly of the sun.

        The mean anomaly is the angle from perihelion that the sun
        would have if it moved at constant angular velocity.

        Args:
            julian_century: Julian Century value

        Returns:
            Mean anomaly in degrees
        """
        return (357.52911 +
                julian_century * (35999.05029 - 0.0001537 * julian_century))

    def calculate_eccentricity(self, julian_century: float) -> float:
        """
        Calculate the eccentricity of Earth's orbit.

        Args:
            julian_century: Julian Century value

        Returns:
            Orbital eccentricity (dimensionless, ~0.017)
        """
        return (0.016708634 -
                julian_century * (0.000042037 + 0.0000001267 * julian_century))

    def calculate_sun_equation_of_center(self, julian_century: float) -> float:
        """
        Calculate the equation of center for the sun.

        The equation of center is the difference between the true
        anomaly and the mean anomaly.

        Args:
            julian_century: Julian Century value

        Returns:
            Equation of center in degrees
        """
        M = self.calculate_geometric_mean_anomaly(julian_century)
        M_rad = math.radians(M)

        sin_M = math.sin(M_rad)
        sin_2M = math.sin(2 * M_rad)
        sin_3M = math.sin(3 * M_rad)

        C = (sin_M * (1.914602 - julian_century * (0.004817 + 0.000014 * julian_century)) +
             sin_2M * (0.019993 - 0.000101 * julian_century) +
             sin_3M * 0.000289)

        return C

    def calculate_sun_true_longitude(self, julian_century: float) -> float:
        """
        Calculate the sun's true longitude.

        Args:
            julian_century: Julian Century value

        Returns:
            True longitude in degrees
        """
        L0 = self.calculate_geometric_mean_longitude(julian_century)
        C = self.calculate_sun_equation_of_center(julian_century)
        return L0 + C

    def calculate_sun_apparent_longitude(self, julian_century: float) -> float:
        """
        Calculate the sun's apparent longitude, corrected for nutation and aberration.

        Args:
            julian_century: Julian Century value

        Returns:
            Apparent longitude in degrees
        """
        O = self.calculate_sun_true_longitude(julian_century)
        omega = 125.04 - 1934.136 * julian_century
        return O - 0.00569 - 0.00478 * math.sin(math.radians(omega))

    def calculate_mean_obliquity_ecliptic(self, julian_century: float) -> float:
        """
        Calculate the mean obliquity of the ecliptic.

        The obliquity is the tilt of Earth's axis relative to its orbital plane.

        Args:
            julian_century: Julian Century value

        Returns:
            Mean obliquity in degrees (~23.4°)
        """
        seconds = (21.448 -
                   julian_century * (46.8150 +
                                     julian_century * (0.00059 -
                                                       julian_century * 0.001813)))
        return 23.0 + (26.0 + seconds / 60.0) / 60.0

    def calculate_obliquity_correction(self, julian_century: float) -> float:
        """
        Calculate the corrected obliquity of the ecliptic.

        This includes the effect of nutation.

        Args:
            julian_century: Julian Century value

        Returns:
            Corrected obliquity in degrees
        """
        e0 = self.calculate_mean_obliquity_ecliptic(julian_century)
        omega = 125.04 - 1934.136 * julian_century
        return e0 + 0.00256 * math.cos(math.radians(omega))

    def calculate_sun_declination(self, julian_century: float) -> float:
        """
        Calculate the sun's declination.

        Declination is the angular distance of the sun north or south
        of the celestial equator.

        Args:
            julian_century: Julian Century value

        Returns:
            Declination in degrees (-23.45 to +23.45)
        """
        e = self.calculate_obliquity_correction(julian_century)
        lambda_sun = self.calculate_sun_apparent_longitude(julian_century)

        sin_dec = math.sin(math.radians(e)) * math.sin(math.radians(lambda_sun))
        return math.degrees(math.asin(sin_dec))

    def calculate_equation_of_time(self, julian_century: float) -> float:
        """
        Calculate the equation of time.

        The equation of time is the difference between apparent solar time
        and mean solar time. It varies throughout the year due to Earth's
        orbital eccentricity and axial tilt.

        Args:
            julian_century: Julian Century value

        Returns:
            Equation of time in minutes
        """
        e = self.calculate_obliquity_correction(julian_century)
        L0 = self.calculate_geometric_mean_longitude(julian_century)
        M = self.calculate_geometric_mean_anomaly(julian_century)
        ecc = self.calculate_eccentricity(julian_century)

        y = math.tan(math.radians(e) / 2) ** 2

        L0_rad = math.radians(L0)
        M_rad = math.radians(M)

        sin_2L0 = math.sin(2 * L0_rad)
        sin_M = math.sin(M_rad)
        cos_2L0 = math.cos(2 * L0_rad)
        sin_4L0 = math.sin(4 * L0_rad)
        sin_2M = math.sin(2 * M_rad)

        Etime = (y * sin_2L0 -
                 2 * ecc * sin_M +
                 4 * ecc * y * sin_M * cos_2L0 -
                 0.5 * y * y * sin_4L0 -
                 1.25 * ecc * ecc * sin_2M)

        return 4 * math.degrees(Etime)  # Convert to minutes

    def calculate_hour_angle(self, dt: datetime, julian_century: float) -> float:
        """
        Calculate the hour angle of the sun.

        The hour angle is the angle between the observer's meridian and
        the hour circle passing through the sun. Negative values indicate
        morning, positive values indicate afternoon.

        Args:
            dt: Current datetime
            julian_century: Julian Century value

        Returns:
            Hour angle in degrees
        """
        # Calculate solar time
        eqtime = self.calculate_equation_of_time(julian_century)

        # Time in minutes from midnight (local time)
        time_offset = self.timezone_offset * 60  # Timezone offset in minutes
        solar_time_minutes = (dt.hour * 60 + dt.minute + dt.second / 60.0 +
                              eqtime + 4 * self.longitude - time_offset)

        # Convert to hour angle (15° per hour, 0° at solar noon)
        hour_angle = (solar_time_minutes / 4.0) - 180.0

        return hour_angle

    def calculate_solar_zenith_angle(self, dt: datetime) -> float:
        """
        Calculate the solar zenith angle.

        The zenith angle is the angle between the sun and the vertical (zenith).
        At solar noon when the sun is highest, this angle is minimized.

        Args:
            dt: Datetime object

        Returns:
            Zenith angle in degrees (0 = overhead, 90 = horizon)
        """
        julian_day = self.calculate_julian_day(dt)
        julian_century = self.calculate_julian_century(julian_day)

        dec = self.calculate_sun_declination(julian_century)
        hour_angle = self.calculate_hour_angle(dt, julian_century)

        lat_rad = math.radians(self.latitude)
        dec_rad = math.radians(dec)
        ha_rad = math.radians(hour_angle)

        cos_zenith = (math.sin(lat_rad) * math.sin(dec_rad) +
                      math.cos(lat_rad) * math.cos(dec_rad) * math.cos(ha_rad))

        # Clamp to valid range to avoid domain errors
        cos_zenith = max(-1.0, min(1.0, cos_zenith))

        return math.degrees(math.acos(cos_zenith))

    def calculate_solar_azimuth(self, dt: datetime, zenith: float) -> float:
        """
        Calculate the solar azimuth angle.

        The azimuth is the compass direction of the sun, measured clockwise
        from north.

        Args:
            dt: Datetime object
            zenith: Solar zenith angle in degrees

        Returns:
            Azimuth angle in degrees (0-360, 0 = North)
        """
        julian_day = self.calculate_julian_day(dt)
        julian_century = self.calculate_julian_century(julian_day)

        dec = self.calculate_sun_declination(julian_century)
        hour_angle = self.calculate_hour_angle(dt, julian_century)

        lat_rad = math.radians(self.latitude)
        dec_rad = math.radians(dec)
        zenith_rad = math.radians(zenith)

        # Calculate azimuth
        sin_zenith = math.sin(zenith_rad)

        if sin_zenith == 0:
            # Sun is at zenith, azimuth is undefined
            return 0.0

        cos_azimuth = ((math.sin(lat_rad) * math.cos(zenith_rad) - math.sin(dec_rad)) /
                       (math.cos(lat_rad) * sin_zenith))

        # Clamp to valid range
        cos_azimuth = max(-1.0, min(1.0, cos_azimuth))

        azimuth = math.degrees(math.acos(cos_azimuth))

        # Determine if we're in the morning (hour_angle < 0) or afternoon
        if hour_angle > 0:
            azimuth = 360.0 - azimuth

        return azimuth

    def calculate_sunrise_sunset(self, dt: datetime) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        Calculate sunrise and sunset times for the given date.

        Args:
            dt: Date to calculate for

        Returns:
            Tuple of (sunrise_time, sunset_time), either may be None
            for polar day/night conditions
        """
        julian_day = self.calculate_julian_day(dt.replace(hour=12, minute=0, second=0))
        julian_century = self.calculate_julian_century(julian_day)

        dec = self.calculate_sun_declination(julian_century)
        eqtime = self.calculate_equation_of_time(julian_century)

        lat_rad = math.radians(self.latitude)
        dec_rad = math.radians(dec)

        # Solar depression angle for sunrise/sunset (top of sun at horizon)
        # 90.833° accounts for atmospheric refraction and sun's apparent radius
        zenith_angle = 90.833

        cos_hour_angle = ((math.cos(math.radians(zenith_angle)) /
                           (math.cos(lat_rad) * math.cos(dec_rad))) -
                          math.tan(lat_rad) * math.tan(dec_rad))

        # Check for polar day/night
        if cos_hour_angle > 1:
            # Polar night - sun never rises
            return (None, None)
        elif cos_hour_angle < -1:
            # Polar day - sun never sets
            return (None, None)

        hour_angle = math.degrees(math.acos(cos_hour_angle))

        # Calculate sunrise time in minutes from midnight
        sunrise_minutes = 720 - 4 * (self.longitude + hour_angle) - eqtime + self.timezone_offset * 60
        sunset_minutes = 720 - 4 * (self.longitude - hour_angle) - eqtime + self.timezone_offset * 60

        # Convert to datetime
        sunrise_hour = int(sunrise_minutes // 60)
        sunrise_min = int(sunrise_minutes % 60)
        sunset_hour = int(sunset_minutes // 60)
        sunset_min = int(sunset_minutes % 60)

        sunrise = dt.replace(hour=max(0, min(23, sunrise_hour)),
                            minute=max(0, min(59, sunrise_min)),
                            second=0, microsecond=0)
        sunset = dt.replace(hour=max(0, min(23, sunset_hour)),
                           minute=max(0, min(59, sunset_min)),
                           second=0, microsecond=0)

        return (sunrise, sunset)

    def get_sun_position(self, dt: datetime) -> SunPosition:
        """
        Get the complete sun position for a given datetime.

        This is the main method to use for shadow calculations.

        Args:
            dt: Datetime object (local time)

        Returns:
            SunPosition object with all calculated values
        """
        # Calculate zenith and altitude
        zenith = self.calculate_solar_zenith_angle(dt)
        altitude = 90.0 - zenith

        # Calculate azimuth
        azimuth = self.calculate_solar_azimuth(dt, zenith)

        # Calculate sunrise/sunset
        sunrise, sunset = self.calculate_sunrise_sunset(dt)

        # Calculate solar noon
        julian_day = self.calculate_julian_day(dt.replace(hour=12))
        julian_century = self.calculate_julian_century(julian_day)
        eqtime = self.calculate_equation_of_time(julian_century)

        # Solar noon in minutes from midnight
        noon_minutes = 720 - 4 * self.longitude - eqtime + self.timezone_offset * 60
        noon_hour = int(noon_minutes // 60)
        noon_min = int(noon_minutes % 60)
        solar_noon = dt.replace(hour=max(0, min(23, noon_hour)),
                                minute=max(0, min(59, noon_min)),
                                second=0, microsecond=0)

        return SunPosition(
            azimuth=azimuth,
            altitude=altitude,
            zenith=zenith,
            is_daylight=altitude > 0,
            solar_noon=solar_noon,
            sunrise=sunrise,
            sunset=sunset
        )

    def get_positions_for_day(self, date: datetime, interval_minutes: int = 30) -> Dict[str, SunPosition]:
        """
        Calculate sun positions for an entire day at regular intervals.

        Useful for generating shadow animation data.

        Args:
            date: Date to calculate for
            interval_minutes: Time between calculations (default 30 min)

        Returns:
            Dictionary mapping time strings to SunPosition objects
        """
        positions = {}

        current = date.replace(hour=0, minute=0, second=0, microsecond=0)

        for minutes in range(0, 24 * 60, interval_minutes):
            hour = minutes // 60
            minute = minutes % 60
            time_dt = current.replace(hour=hour, minute=minute)
            time_key = f"{hour:02d}:{minute:02d}"

            positions[time_key] = self.get_sun_position(time_dt)

        return positions


# Convenience function for quick calculations
def get_dubai_sun_position(dt: datetime) -> SunPosition:
    """
    Quick helper to get sun position for Dubai.

    Dubai coordinates: 25.2048° N, 55.2708° E
    Timezone: UTC+4

    Args:
        dt: Local datetime in Dubai

    Returns:
        SunPosition object
    """
    calculator = SolarPositionCalculator(
        latitude=25.2048,
        longitude=55.2708,
        timezone_offset=4.0
    )
    return calculator.get_sun_position(dt)


# Example usage and testing
if __name__ == "__main__":
    # Create calculator for Dubai
    dubai_calc = SolarPositionCalculator(
        latitude=25.2048,
        longitude=55.2708,
        timezone_offset=4.0
    )

    # Test with current time
    now = datetime.now()
    position = dubai_calc.get_sun_position(now)

    print("=" * 60)
    print("Dubai Sun Position Calculator - Test Results")
    print("=" * 60)
    print(f"Date/Time: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Location: Dubai (25.2048°N, 55.2708°E)")
    print("-" * 60)
    print(f"Sun Azimuth:  {position.azimuth:.2f}°")
    print(f"Sun Altitude: {position.altitude:.2f}°")
    print(f"Sun Zenith:   {position.zenith:.2f}°")
    print(f"Is Daylight:  {position.is_daylight}")
    print("-" * 60)
    if position.sunrise:
        print(f"Sunrise:      {position.sunrise.strftime('%H:%M')}")
    if position.sunset:
        print(f"Sunset:       {position.sunset.strftime('%H:%M')}")
    if position.solar_noon:
        print(f"Solar Noon:   {position.solar_noon.strftime('%H:%M')}")
    print("=" * 60)










