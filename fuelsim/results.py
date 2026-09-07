"""Immutable chronological records, daily aggregates, and forecast reporting."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    import pandas as pd
    from fuelsim.config import SimulationConfig


@dataclass(frozen=True)
class StepRecord:
    """A constant-dispatch segment, split at input changes and physical events.

    Load fields are delivered energy; charging fields are source energy before
    charging losses. generator_running describes operation throughout this
    segment; on_start/on_end describe carried state at its boundaries.
    """

    day: int
    start_hour: float
    duration_hours: float
    load_kwh: float
    solar_kwh: float
    solar_to_load_kwh: float
    solar_to_battery_kwh: float
    solar_curtailed_kwh: float
    battery_to_load_kwh: float
    generator_to_load_kwh: float
    generator_to_battery_kwh: float
    generator_energy_kwh: float
    generator_hours: float
    fuel_used_l: float
    unserved_load_kwh: float
    battery_start_kwh: float
    battery_end_kwh: float
    soc_start_pct: float
    soc_end_pct: float
    fuel_start_l: float
    fuel_end_l: float
    battery_charge_loss_kwh: float = 0.0
    battery_discharge_loss_kwh: float = 0.0
    generator_running: bool = False
    generator_on_start: bool = False
    generator_on_end: bool = False
    fuel_limited: bool = False
    generator_started: bool = False


@dataclass(frozen=True)
class DayRecord:
    """One full day's segment sums plus state endpoints and extrema."""

    day: int
    load_kwh: float
    solar_kwh: float
    solar_to_load_kwh: float
    solar_to_battery_kwh: float
    solar_curtailed_kwh: float
    battery_to_load_kwh: float
    generator_to_load_kwh: float
    generator_to_battery_kwh: float
    generator_energy_kwh: float
    generator_hours: float
    fuel_used_l: float
    fuel_limited: bool
    unserved_load_kwh: float
    battery_start_kwh: float
    battery_end_kwh: float
    soc_start_pct: float
    soc_end_pct: float
    fuel_start_l: float
    fuel_end_l: float
    soc_min_pct: float = 0.0
    soc_max_pct: float = 0.0
    battery_charge_loss_kwh: float = 0.0
    battery_discharge_loss_kwh: float = 0.0
    generator_start_count: int = 0
    generator_on_start: bool = False
    generator_on_end: bool = False
    steps: tuple[StepRecord, ...] = field(default_factory=tuple, repr=False)


def format_days_until(days_until_threshold: int | None, *, horizon_days: int) -> str:
    """Compact display; callers supply a horizon supported by the simulated run."""
    if horizon_days < 1:
        raise ValueError("horizon_days must be >= 1")
    if days_until_threshold is None or days_until_threshold > horizon_days:
        return f">{horizon_days} days"
    if days_until_threshold < 0:
        raise ValueError("days_until_threshold must be >= 0")
    unit = "day" if days_until_threshold == 1 else "days"
    return f"{days_until_threshold} {unit}"


@dataclass(frozen=True)
class SimulationResult:
    config: SimulationConfig
    days: Sequence[DayRecord] = field(default_factory=tuple)
    days_until_threshold: int | None = None

    @property
    def reached_threshold(self) -> bool:
        return self.days_until_threshold is not None

    @property
    def days_display(self) -> str:
        horizon = self.config.report_horizon_days
        if self.days_until_threshold is None:
            if not self.days:
                return "Not simulated"
            horizon = min(horizon, len(self.days))
        return format_days_until(self.days_until_threshold, horizon_days=horizon)

    def summary(self) -> str:
        threshold = self.config.fuel_threshold_l
        if self.days_until_threshold is None:
            status = (
                f"Fuel threshold ({threshold:g} L) was not reached within the "
                f"{len(self.days)}-day simulated horizon"
            )
        else:
            status = f"Fuel reaches the {threshold:g} L threshold in {self.days_display}"
        used = sum(day.fuel_used_l for day in self.days)
        unmet = sum(day.unserved_load_kwh for day in self.days)
        load = (
            "hourly load profile" if self.config.hourly_load_kw is not None
            else f"load {self.config.current_load_kw:g} kW"
        )
        details = (
            f" (from {self.config.fuel_level_l:g} L, {load}, "
            f"solar capacity {self.config.solar_capacity_kw:g} kW); "
            f"modeled fuel consumption {used:g} L"
        )
        if self.days_until_threshold is None:
            details += " under the assumed repeating profiles"
        if unmet > 1e-9:
            details += f"; unmet load {unmet:g} kWh"
        return status + details + "."

    def to_frame(self) -> pd.DataFrame:
        """Daily scalar values, without copying/serializing nested step records."""
        import pandas as pd

        columns = [entry.name for entry in DAY_RECORD_FIELDS if entry.name != "steps"]
        rows = [{name: getattr(day, name) for name in columns} for day in self.days]
        return pd.DataFrame(rows, columns=columns)

    def to_step_frame(self) -> pd.DataFrame:
        """Flattened chronological segments; start_hour is within each day."""
        import pandas as pd

        rows = [asdict(step) for day in self.days for step in day.steps]
        return pd.DataFrame(rows, columns=[entry.name for entry in STEP_RECORD_FIELDS])


DAY_RECORD_FIELDS = fields(DayRecord)
STEP_RECORD_FIELDS = fields(StepRecord)
