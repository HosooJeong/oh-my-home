"""Shared coordinate screen and spherical straight-line distance, not routing."""
import math


def distance_m(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    h = math.sin((b-a)/2)**2 + math.cos(a)*math.cos(b)*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, h))))


def in_supported_window(lat, lon):
    # A coarse error screen shared with build_samples, not a city boundary polygon.
    return 34.9 <= lat <= 35.5 and 127.8 <= lon <= 128.5
