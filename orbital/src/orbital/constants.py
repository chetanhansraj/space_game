"""Physical constants. SI throughout: metres, seconds, kilograms.

Single source of truth. Nothing in this service defines a constant locally.

Values are IAU 2015 nominal / DE440 header values. They are quoted to more
digits than the arcminute accuracy target needs, because rounding a constant
is free to avoid and annoying to debug.
"""

# Gravitational parameters (m^3 / s^2)
GM_SUN = 1.32712440041279419e20
GM_EARTH = 3.986004418e14
GM_MOON = 4.9028000661637961e12
GM_EARTH_MOON = GM_EARTH + GM_MOON

# Body radii (m)
R_MOON = 1_737_400.0
R_EARTH = 6_378_137.0

# Units
AU = 1.495978707e11          # metres, IAU 2012 definition (exact)
DAY = 86_400.0               # seconds
JULIAN_YEAR = 365.25 * DAY
KM = 1_000.0

# Julian date of J2000.0 (2000-01-01T12:00:00 TT)
JD_J2000 = 2_451_545.0

# Obliquity of the ecliptic at J2000.0 (radians). Used to rotate between the
# ecliptic frame (which some analytic ephemerides return) and the equatorial
# ICRF frame this service uses internally.
OBLIQUITY_J2000 = 0.409092600600583  # 23.4392911 degrees
