"""Adapter from a NanoGridX controller-configuration row to a SimulationConfig.

The controller table is read positionally, so the column order below is the single
source of truth for the mapping. If it turns out to be wrong, fix it here and the
notebook, the tests, and any caller all follow.

Columns marked UNVERIFIED were inferred from the values themselves, not from a
schema. See `docs` in `PLAN.md` for how the inference was checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from fuelsim.config import SimulationConfig

# Positional layout of a controller-configuration row.
CONTROLLER_COLUMNS: tuple[str, ...] = (
    "controller_id",
    "name",
    "site_id",
    "battery_capacity_kwh",   # 30.0   UNVERIFIED (vs. gen_start_soc_pct)
    "solar_capacity_kw",      # 5.0
    "solar_hours_per_day",    # 5.0    UNVERIFIED
    "current_load_kw",        # 5.0    UNVERIFIED - may be live telemetry, not config
    "tank_capacity_l",        # 190.0
    "gen_start_soc_pct",      # 20.0   UNVERIFIED (vs. battery_capacity_kwh)
    "fuel_threshold_l",       # 20.0
    "gen_fuel_lph",           # 3.19
    "gen_rated_kw",           # 6.0
    "fuel_level_l",           # 180.0  UNVERIFIED (vs. tank_capacity_l)
)

TEXT_COLUMNS = frozenset({"controller_id", "name", "site_id"})

# Columns that feed SimulationConfig directly, by identical name.
_PASSTHROUGH = (
    "battery_capacity_kwh",
    "solar_capacity_kw",
    "solar_hours_per_day",
    "current_load_kw",
    "gen_start_soc_pct",
    "fuel_threshold_l",
    "gen_fuel_lph",
    "gen_rated_kw",
    "fuel_level_l",
)


@dataclass(frozen=True)
class ControllerRecord:
    """One parsed controller-configuration row."""

    controller_id: str
    name: str
    site_id: str
    values: Mapping[str, float]

    def to_simulation_config(
        self,
        *,
        battery_soc_pct: float,
        current_load_kw: Optional[float] = None,
        **overrides,
    ) -> SimulationConfig:
        """Build a SimulationConfig from this row.

        ``battery_soc_pct`` is required and has no column here: it is a live
        measurement, not configuration. ``current_load_kw`` overrides the column
        value, which is the right thing to do once a real load reading is
        available - the column is an unverified guess.
        """
        settings = {name: self.values[name] for name in _PASSTHROUGH}
        if current_load_kw is not None:
            settings["current_load_kw"] = current_load_kw
        settings["battery_soc_pct"] = battery_soc_pct
        settings.update(overrides)
        return SimulationConfig(**settings)


def parse_controller_row(row: str, *, columns=CONTROLLER_COLUMNS) -> ControllerRecord:
    """Parse one tab-separated controller row into a ControllerRecord."""
    fields = [field.strip() for field in row.rstrip("\n").split("\t")]
    if len(fields) != len(columns):
        raise ValueError(
            f"expected {len(columns)} columns, got {len(fields)}: {fields!r}"
        )

    text: dict[str, str] = {}
    values: dict[str, float] = {}
    for name, raw in zip(columns, fields):
        if name in TEXT_COLUMNS:
            text[name] = raw
            continue
        try:
            values[name] = float(raw)
        except ValueError as error:
            raise ValueError(f"column {name!r} is not a number: {raw!r}") from error

    return ControllerRecord(
        controller_id=text["controller_id"],
        name=text["name"],
        site_id=text["site_id"],
        values=values,
    )
