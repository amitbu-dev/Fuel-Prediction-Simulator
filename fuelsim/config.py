"""Configuration for chronological simulation; powers are kW and energies kWh."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

HOURS_PER_DAY = 24.0
DEFAULT_SOLAR_HOURS_PER_DAY = 5.0
DEFAULT_REPORT_HORIZON_DAYS = 30
DEFAULT_MAX_DAYS = 60
PERCENT = 100.0


def _finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def _nonnegative(name: str, value: float) -> None:
    _finite(name, value)
    if value < 0:
        raise ValueError(f"{name} must be >= 0")


def _positive(name: str, value: float) -> None:
    _finite(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be > 0")


def _percent(name: str, value: float) -> None:
    _finite(name, value)
    if not 0 <= value <= PERCENT:
        raise ValueError(f"{name} must be between 0 and 100")


def _positive_integer(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class SimulationConfig:
    """Site measurements, equipment settings, and explicitly assumed input profiles.

    Scalar load repeats all day. Solar yield is capacity x equivalent full-output
    hours, spread uniformly across a separate daylight window (centered at noon by
    default). Hourly profiles override these scalar-derived power profiles.
    Daily solar factors repeat their sequence; they are not a weather forecast.
    """

    battery_soc_pct: float
    fuel_level_l: float
    solar_capacity_kw: float
    current_load_kw: float
    battery_capacity_kwh: float
    gen_start_soc_pct: float
    gen_rated_kw: float
    gen_fuel_lph: float

    gen_stop_soc_pct: float = PERCENT
    max_soc_pct: float = PERCENT
    fuel_threshold_l: float = 0.0
    solar_hours_per_day: float = DEFAULT_SOLAR_HOURS_PER_DAY
    battery_charge_efficiency: float = 1.0
    battery_discharge_efficiency: float = 1.0
    max_days: int = DEFAULT_MAX_DAYS
    report_horizon_days: int = DEFAULT_REPORT_HORIZON_DAYS
    timestep_minutes: int = 15
    solar_window_hours: float | None = None
    solar_start_hour: float | None = None
    hourly_load_kw: tuple[float, ...] | None = None
    hourly_solar_kw: tuple[float, ...] | None = None
    daily_solar_factors: tuple[float, ...] = (1.0,)
    # Charging limit is input-side; discharge limit is power delivered to load.
    # None leaves the rating unspecified. Zero disables that energy path.
    battery_max_charge_kw: float | None = None
    battery_max_discharge_kw: float | None = None
    # None uses constant L/h; otherwise interpolate idle to full-output fuel rate.
    gen_idle_fuel_lph: float | None = None
    initial_generator_running: bool = False

    def __post_init__(self) -> None:
        for name in ("battery_soc_pct", "gen_start_soc_pct", "gen_stop_soc_pct", "max_soc_pct"):
            _percent(name, getattr(self, name))
        for name in (
            "fuel_level_l", "solar_capacity_kw", "current_load_kw", "fuel_threshold_l",
            "gen_fuel_lph",
        ):
            _nonnegative(name, getattr(self, name))
        for name in ("battery_capacity_kwh", "gen_rated_kw"):
            _positive(name, getattr(self, name))
        for name in ("battery_charge_efficiency", "battery_discharge_efficiency"):
            value = getattr(self, name)
            _finite(name, value)
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1]")
        _finite("solar_hours_per_day", self.solar_hours_per_day)
        if not 0 <= self.solar_hours_per_day <= HOURS_PER_DAY:
            raise ValueError("solar_hours_per_day must be between 0 and 24")
        if self.gen_stop_soc_pct <= self.gen_start_soc_pct:
            raise ValueError("gen_stop_soc_pct must be strictly above gen_start_soc_pct")
        if self.gen_stop_soc_pct > self.max_soc_pct:
            raise ValueError("gen_stop_soc_pct must be <= max_soc_pct")
        if self.battery_soc_pct > self.max_soc_pct:
            raise ValueError("battery_soc_pct must be <= max_soc_pct")
        for name in ("max_days", "report_horizon_days", "timestep_minutes"):
            _positive_integer(name, getattr(self, name))
        if 60 % self.timestep_minutes:
            raise ValueError("timestep_minutes must divide 60")
        if not isinstance(self.initial_generator_running, bool):
            raise ValueError("initial_generator_running must be boolean")
        for name in (
            "solar_window_hours", "solar_start_hour", "battery_max_charge_kw",
            "battery_max_discharge_kw", "gen_idle_fuel_lph",
        ):
            value = getattr(self, name)
            if value is not None:
                _nonnegative(name, value)
        if (
            self.gen_idle_fuel_lph is not None
            and self.gen_idle_fuel_lph > self.gen_fuel_lph
        ):
            raise ValueError("gen_idle_fuel_lph must be <= gen_fuel_lph")
        for name in ("hourly_load_kw", "hourly_solar_kw"):
            profile = getattr(self, name)
            if profile is not None:
                profile = tuple(float(value) for value in profile)
                if len(profile) != 24:
                    raise ValueError(f"{name} must contain 24 values")
                for value in profile:
                    _nonnegative(name, value)
                if name == "hourly_solar_kw" and any(
                    value > self.solar_capacity_kw for value in profile
                ):
                    raise ValueError("hourly_solar_kw cannot exceed solar_capacity_kw")
                object.__setattr__(self, name, profile)
        factors = tuple(float(value) for value in self.daily_solar_factors)
        if not factors or any(not math.isfinite(value) or not 0 <= value <= 1 for value in factors):
            raise ValueError("daily_solar_factors must be a nonempty sequence in [0, 1]")
        object.__setattr__(self, "daily_solar_factors", factors)
        width = self.resolved_solar_window_hours
        start = self.resolved_solar_start_hour
        if width > HOURS_PER_DAY or start + width > HOURS_PER_DAY:
            raise ValueError("solar window must fit within one day")
        if self.hourly_solar_kw is None and self.daily_solar_kwh > 0:
            if width == 0:
                raise ValueError("positive solar yield requires a nonzero solar window")
            if self.daily_solar_kwh / width > self.solar_capacity_kw + 1e-9:
                raise ValueError("solar profile exceeds nameplate capacity")

    @property
    def resolved_solar_window_hours(self) -> float:
        return self.solar_hours_per_day if self.solar_window_hours is None else self.solar_window_hours

    @property
    def resolved_solar_start_hour(self) -> float:
        if self.solar_start_hour is not None:
            return self.solar_start_hour
        return (HOURS_PER_DAY - self.resolved_solar_window_hours) / 2

    @property
    def daily_load_kwh(self) -> float:
        """Integral of the repeating load profile over 24 hours."""
        return sum(self.hourly_load_kw) if self.hourly_load_kw is not None else self.current_load_kw * HOURS_PER_DAY

    @property
    def daily_solar_kwh(self) -> float:
        """Unscaled solar production, before the day's solar factor/curtailment."""
        return sum(self.hourly_solar_kw) if self.hourly_solar_kw is not None else self.solar_capacity_kw * self.solar_hours_per_day

    def battery_kwh_at(self, soc_pct: float) -> float:
        return self.battery_capacity_kwh * soc_pct / PERCENT

    def soc_pct_at(self, kwh: float) -> float:
        return kwh / self.battery_capacity_kwh * PERCENT

    @property
    def initial_battery_kwh(self) -> float:
        return self.battery_kwh_at(self.battery_soc_pct)

    @property
    def max_battery_kwh(self) -> float:
        return self.battery_kwh_at(self.max_soc_pct)

    @property
    def gen_start_battery_kwh(self) -> float:
        return self.battery_kwh_at(self.gen_start_soc_pct)

    @property
    def gen_stop_battery_kwh(self) -> float:
        return self.battery_kwh_at(self.gen_stop_soc_pct)

    def with_changes(self, **changes) -> SimulationConfig:
        return replace(self, **changes)
