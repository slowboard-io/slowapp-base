"""The moon's phase from the time alone (mean synodic month; good to a few hours)."""
import math
from datetime import datetime, timedelta, timezone

SYNODIC_DAYS = 29.530588853
NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)   # a known new moon
NAMES = ["New moon", "Waxing crescent", "First quarter", "Waxing gibbous",
         "Full moon", "Waning gibbous", "Last quarter", "Waning crescent"]


def age(t):
    """Days since the last new moon, 0 <= age < SYNODIC_DAYS."""
    return ((t - NEW_MOON) / timedelta(days=1)) % SYNODIC_DAYS


def illumination(t):
    """Lit fraction of the disc, 0..1."""
    return (1 - math.cos(2 * math.pi * age(t) / SYNODIC_DAYS)) / 2


def name(t):
    return NAMES[int(age(t) / SYNODIC_DAYS * 8 + 0.5) % 8]


def next_phase(t, fraction):
    """The next time the age reaches `fraction` of a month (0 new, 0.5 full) after t."""
    days = (fraction * SYNODIC_DAYS - age(t)) % SYNODIC_DAYS
    return t + timedelta(days=days)
