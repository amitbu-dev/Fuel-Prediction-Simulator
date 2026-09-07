"""Chronological dispatch with exact battery and fuel events inside each interval."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from fuelsim.config import SimulationConfig
from fuelsim.results import DayRecord, SimulationResult, StepRecord

ENERGY_EPSILON_KWH = 1e-9
TIME_EPSILON_HOURS = 1e-12


@dataclass(frozen=True)
class _Dispatch:
    """Constant powers (kW) and fuel rate (L/h) until the next physical event."""

    solar_to_load: float
    solar_to_battery: float
    solar_curtailed: float
    battery_to_load: float
    generator_to_load: float
    generator_to_battery: float
    unserved_load: float
    battery_rate: float
    fuel_rate: float
    running: bool


def _segments(config: SimulationConfig):
    """Split input profiles at both sampling boundaries and daylight edges."""
    dt = config.timestep_minutes / 60.0
    points = {float(hour) for hour in range(25)}
    points.update(i * dt for i in range(24 * 60 // config.timestep_minutes + 1))
    if config.hourly_solar_kw is None:
        start = config.resolved_solar_start_hour
        points.update((start, start + config.resolved_solar_window_hours))
    return pairwise(sorted(points))


def _power(config: SimulationConfig, hour: float) -> tuple[float, float]:
    index = min(int(hour), 23)
    load = (
        config.hourly_load_kw[index]
        if config.hourly_load_kw is not None else config.current_load_kw
    )
    if config.hourly_solar_kw is not None:
        return load, config.hourly_solar_kw[index]
    width = config.resolved_solar_window_hours
    start = config.resolved_solar_start_hour
    solar = (
        config.daily_solar_kwh / width
        if width > 0 and start <= hour < start + width else 0.0
    )
    return load, solar


def _can_run(config: SimulationConfig, fuel_l: float) -> bool:
    # A zero-rate generator is a supported mathematical edge case.
    return config.gen_fuel_lph == 0.0 or fuel_l > 0.0


def _can_stop(config: SimulationConfig, battery_kwh: float, deficit_kw: float) -> bool:
    discharge_limit = config.battery_max_discharge_kw
    return (
        battery_kwh >= config.gen_stop_battery_kwh - ENERGY_EPSILON_KWH
        and (discharge_limit is None or deficit_kw <= discharge_limit + ENERGY_EPSILON_KWH)
    )


def _dispatch(
    config: SimulationConfig, *, battery_kwh: float, fuel_l: float,
    load_kw: float, solar_kw: float, running: bool,
) -> _Dispatch:
    solar_to_load = min(load_kw, solar_kw)
    deficit = load_kw - solar_to_load
    surplus = solar_kw - solar_to_load
    charge_limit = (
        math.inf if config.battery_max_charge_kw is None else config.battery_max_charge_kw
    )
    discharge_limit = (
        math.inf if config.battery_max_discharge_kw is None
        else config.battery_max_discharge_kw
    )
    available_discharge = (
        discharge_limit
        if battery_kwh > config.gen_start_battery_kwh + ENERGY_EPSILON_KWH else 0.0
    )
    if not _can_run(config, fuel_l):
        running = False
    elif running and _can_stop(config, battery_kwh, deficit):
        running = False
    elif not running and deficit > available_discharge + ENERGY_EPSILON_KWH:
        running = True

    solar_to_battery = (
        min(surplus, charge_limit)
        if battery_kwh < config.max_battery_kwh - ENERGY_EPSILON_KWH else 0.0
    )
    generator_to_load = min(deficit, config.gen_rated_kw) if running else 0.0
    battery_to_load = min(deficit - generator_to_load, available_discharge)
    unserved = max(deficit - generator_to_load - battery_to_load, 0.0)
    generator_to_battery = 0.0
    if (
        running and battery_to_load <= ENERGY_EPSILON_KWH
        and battery_kwh < config.gen_stop_battery_kwh - ENERGY_EPSILON_KWH
    ):
        generator_to_battery = min(
            config.gen_rated_kw - generator_to_load,
            max(charge_limit - solar_to_battery, 0.0),
        )
    battery_rate = (
        (solar_to_battery + generator_to_battery) * config.battery_charge_efficiency
        - battery_to_load / config.battery_discharge_efficiency
    )
    fuel_rate = 0.0
    if running:
        if config.gen_idle_fuel_lph is None:
            fuel_rate = config.gen_fuel_lph
        else:
            output = generator_to_load + generator_to_battery
            fuel_rate = config.gen_idle_fuel_lph + (
                config.gen_fuel_lph - config.gen_idle_fuel_lph
            ) * output / config.gen_rated_kw
    return _Dispatch(
        solar_to_load=solar_to_load, solar_to_battery=solar_to_battery,
        solar_curtailed=surplus - solar_to_battery, battery_to_load=battery_to_load,
        generator_to_load=generator_to_load, generator_to_battery=generator_to_battery,
        unserved_load=unserved, battery_rate=battery_rate, fuel_rate=fuel_rate,
        running=running,
    )


def _event_duration(
    config: SimulationConfig, rates: _Dispatch, battery_kwh: float,
    fuel_l: float, remaining_hours: float,
) -> float:
    duration = remaining_hours
    if rates.battery_rate < 0:
        duration = min(
            duration, (battery_kwh - config.gen_start_battery_kwh) / -rates.battery_rate
        )
    elif rates.battery_rate > 0:
        duration = min(
            duration, (config.max_battery_kwh - battery_kwh) / rates.battery_rate
        )
        if rates.running and battery_kwh < config.gen_stop_battery_kwh - ENERGY_EPSILON_KWH:
            duration = min(
                duration, (config.gen_stop_battery_kwh - battery_kwh) / rates.battery_rate
            )
    if rates.fuel_rate > 0:
        duration = min(duration, fuel_l / rates.fuel_rate)
    if duration <= 0:
        raise RuntimeError("dispatch failed to advance to its next physical event")
    return duration


def _aggregate_day(
    config: SimulationConfig, day: int, steps: list[StepRecord],
) -> DayRecord:
    def total(name: str) -> float:
        return math.fsum(getattr(step, name) for step in steps)

    first, last = steps[0], steps[-1]
    return DayRecord(
        day=day, load_kwh=total("load_kwh"), solar_kwh=total("solar_kwh"),
        solar_to_load_kwh=total("solar_to_load_kwh"),
        solar_to_battery_kwh=total("solar_to_battery_kwh"),
        solar_curtailed_kwh=total("solar_curtailed_kwh"),
        battery_to_load_kwh=total("battery_to_load_kwh"),
        generator_to_load_kwh=total("generator_to_load_kwh"),
        generator_to_battery_kwh=total("generator_to_battery_kwh"),
        generator_energy_kwh=total("generator_energy_kwh"),
        generator_hours=total("generator_hours"), fuel_used_l=total("fuel_used_l"),
        fuel_limited=any(step.fuel_limited for step in steps),
        unserved_load_kwh=total("unserved_load_kwh"),
        battery_start_kwh=first.battery_start_kwh, battery_end_kwh=last.battery_end_kwh,
        soc_start_pct=first.soc_start_pct, soc_end_pct=last.soc_end_pct,
        fuel_start_l=first.fuel_start_l, fuel_end_l=last.fuel_end_l,
        soc_min_pct=min(min(step.soc_start_pct, step.soc_end_pct) for step in steps),
        soc_max_pct=max(max(step.soc_start_pct, step.soc_end_pct) for step in steps),
        battery_charge_loss_kwh=total("battery_charge_loss_kwh"),
        battery_discharge_loss_kwh=total("battery_discharge_loss_kwh"),
        generator_start_count=sum(step.generator_started for step in steps),
        generator_on_start=first.generator_on_start,
        generator_on_end=last.generator_on_end, steps=tuple(steps),
    )


def simulate_day(
    config: SimulationConfig, *, day: int, battery_kwh: float, fuel_l: float,
    generator_running: bool | None = None,
) -> DayRecord:
    """Simulate a full day; pass the previous day's ending generator state to resume.

    The SOC start threshold is a reserve floor, not a physical empty-battery level.
    Initial measurements below that floor are accepted but cannot discharge further.
    """
    if not isinstance(day, int) or isinstance(day, bool) or day < 1:
        raise ValueError("day must be a positive integer")
    if not math.isfinite(battery_kwh) or not 0 <= battery_kwh <= config.max_battery_kwh:
        raise ValueError("battery_kwh must be finite and within configured capacity")
    if not math.isfinite(fuel_l) or fuel_l < 0:
        raise ValueError("fuel_l must be finite and nonnegative")
    if generator_running is not None and not isinstance(generator_running, bool):
        raise ValueError("generator_running must be boolean or None")
    running = config.initial_generator_running if generator_running is None else generator_running
    records: list[StepRecord] = []
    factor = config.daily_solar_factors[(day - 1) % len(config.daily_solar_factors)]
    for start, end in _segments(config):
        load_kw, solar_kw = _power(config, (start + end) / 2)
        solar_kw *= factor
        hour = start
        while end - hour > TIME_EPSILON_HOURS:
            before_running = running
            rates = _dispatch(
                config, battery_kwh=battery_kwh, fuel_l=fuel_l,
                load_kw=load_kw, solar_kw=solar_kw, running=running,
            )
            duration = _event_duration(config, rates, battery_kwh, fuel_l, end - hour)
            before_battery, before_fuel = battery_kwh, fuel_l
            battery_kwh += rates.battery_rate * duration
            fuel_used = min(rates.fuel_rate * duration, fuel_l)
            fuel_l -= fuel_used
            # Snap only roundoff at physical boundaries; never correct a dispatch imbalance.
            for boundary in (config.gen_start_battery_kwh, config.gen_stop_battery_kwh,
                             config.max_battery_kwh, 0.0):
                if abs(battery_kwh - boundary) < 1e-12:
                    battery_kwh = boundary
                    break
            exhausted = rates.fuel_rate > 0 and fuel_l <= 1e-12
            if exhausted:
                fuel_used = before_fuel
                fuel_l = 0.0
            deficit = load_kw - rates.solar_to_load
            running = rates.running and _can_run(config, fuel_l)
            if running and _can_stop(config, battery_kwh, deficit):
                running = False
            records.append(StepRecord(
                day=day, start_hour=hour, duration_hours=duration,
                load_kwh=load_kw * duration, solar_kwh=solar_kw * duration,
                solar_to_load_kwh=rates.solar_to_load * duration,
                solar_to_battery_kwh=rates.solar_to_battery * duration,
                solar_curtailed_kwh=rates.solar_curtailed * duration,
                battery_to_load_kwh=rates.battery_to_load * duration,
                generator_to_load_kwh=rates.generator_to_load * duration,
                generator_to_battery_kwh=rates.generator_to_battery * duration,
                generator_energy_kwh=(rates.generator_to_load + rates.generator_to_battery) * duration,
                generator_hours=duration if rates.running else 0.0,
                fuel_used_l=fuel_used, unserved_load_kwh=rates.unserved_load * duration,
                battery_start_kwh=before_battery, battery_end_kwh=battery_kwh,
                soc_start_pct=config.soc_pct_at(before_battery),
                soc_end_pct=config.soc_pct_at(battery_kwh),
                fuel_start_l=before_fuel, fuel_end_l=fuel_l,
                battery_charge_loss_kwh=(rates.solar_to_battery + rates.generator_to_battery)
                * duration * (1 - config.battery_charge_efficiency),
                battery_discharge_loss_kwh=rates.battery_to_load * duration
                * (1 / config.battery_discharge_efficiency - 1),
                generator_running=rates.running, generator_on_start=before_running,
                generator_on_end=running,
                generator_started=rates.running and not before_running,
                fuel_limited=exhausted or (
                    not _can_run(config, before_fuel) and rates.unserved_load > ENERGY_EPSILON_KWH
                ),
            ))
            hour += duration
    return _aggregate_day(config, day, records)


def run_simulation(config: SimulationConfig) -> SimulationResult:
    """Carry chronological state across full days until the refueling threshold."""
    if config.fuel_level_l <= config.fuel_threshold_l:
        return SimulationResult(config=config, days=(), days_until_threshold=0)
    battery_kwh = config.initial_battery_kwh
    fuel_l = config.fuel_level_l
    running = config.initial_generator_running
    days: list[DayRecord] = []
    reached = None
    for day in range(1, config.max_days + 1):
        record = simulate_day(
            config, day=day, battery_kwh=battery_kwh, fuel_l=fuel_l,
            generator_running=running,
        )
        days.append(record)
        battery_kwh, fuel_l = record.battery_end_kwh, record.fuel_end_l
        running = record.generator_on_end
        if fuel_l <= config.fuel_threshold_l + 1e-12:
            reached = day
            break
    return SimulationResult(config=config, days=tuple(days), days_until_threshold=reached)
