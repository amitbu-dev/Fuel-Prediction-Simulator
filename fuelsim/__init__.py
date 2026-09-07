"""Fuel-prediction PoC simulator.

Estimates how many days remain before a hybrid solar/battery/generator site
runs its fuel tank down to a configured threshold.
"""

from fuelsim.config import SimulationConfig
from fuelsim.controller import ControllerRecord, parse_controller_row
from fuelsim.engine import run_simulation, simulate_day
from fuelsim.results import DayRecord, StepRecord, SimulationResult, format_days_until

__all__ = [
    "SimulationConfig",
    "ControllerRecord",
    "parse_controller_row",
    "DayRecord",
    "StepRecord",
    "SimulationResult",
    "format_days_until",
    "run_simulation",
    "simulate_day",
]
