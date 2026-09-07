"""Independent event-time and physical-limit regressions for chronological dispatch."""

from itertools import pairwise

import pytest

from fuelsim import SimulationConfig, run_simulation, simulate_day
from tests.test_simulation import reference_config


def day_for(config):
    return simulate_day(
        config, day=1, battery_kwh=config.initial_battery_kwh,
        fuel_l=config.fuel_level_l,
    )


def running_windows(day):
    windows = []
    for step in day.steps:
        if not step.generator_running:
            continue
        end = step.start_hour + step.duration_hours
        if windows and abs(windows[-1][1] - step.start_hour) < 1e-9:
            windows[-1] = (windows[-1][0], end)
        else:
            windows.append((step.start_hour, end))
    return windows


def assert_physics(config, day):
    assert sum(step.duration_hours for step in day.steps) == pytest.approx(24.0)
    for step in day.steps:
        dt = step.duration_hours
        assert dt > 0
        assert step.load_kwh == pytest.approx(
            step.solar_to_load_kwh + step.battery_to_load_kwh
            + step.generator_to_load_kwh + step.unserved_load_kwh
        )
        assert step.solar_kwh == pytest.approx(
            step.solar_to_load_kwh + step.solar_to_battery_kwh + step.solar_curtailed_kwh
        )
        assert step.generator_energy_kwh == pytest.approx(
            step.generator_to_load_kwh + step.generator_to_battery_kwh
        )
        charge = step.solar_to_battery_kwh + step.generator_to_battery_kwh
        assert step.battery_end_kwh - step.battery_start_kwh == pytest.approx(
            charge * config.battery_charge_efficiency
            - step.battery_to_load_kwh / config.battery_discharge_efficiency,
            abs=1e-9,
        )
        assert step.battery_charge_loss_kwh == pytest.approx(
            charge * (1 - config.battery_charge_efficiency)
        )
        assert step.battery_discharge_loss_kwh == pytest.approx(
            step.battery_to_load_kwh * (1 / config.battery_discharge_efficiency - 1)
        )
        assert step.fuel_end_l == pytest.approx(step.fuel_start_l - step.fuel_used_l)
        assert 0 <= step.battery_end_kwh <= config.max_battery_kwh + 1e-9
        assert step.battery_to_load_kwh <= 1e-9 or charge <= 1e-9
        assert step.generator_energy_kwh <= config.gen_rated_kw * step.generator_hours + 1e-9
        assert step.generator_hours == pytest.approx(dt if step.generator_running else 0)
        if config.battery_max_charge_kw is not None:
            assert charge <= config.battery_max_charge_kw * dt + 1e-9
        if config.battery_max_discharge_kw is not None:
            assert step.battery_to_load_kwh <= config.battery_max_discharge_kw * dt + 1e-9
    for before, after in pairwise(day.steps):
        assert before.start_hour + before.duration_hours == pytest.approx(after.start_hour)
        assert before.battery_end_kwh == pytest.approx(after.battery_start_kwh)
        assert before.fuel_end_l == pytest.approx(after.fuel_start_l)
        assert before.generator_on_end == after.generator_on_start
    assert day.soc_min_pct == pytest.approx(
        min(min(step.soc_start_pct, step.soc_end_pct) for step in day.steps)
    )
    assert day.soc_max_pct == pytest.approx(
        max(max(step.soc_start_pct, step.soc_end_pct) for step in day.steps)
    )


@pytest.mark.parametrize("timestep", [5, 15, 60])
def test_fractional_generator_events_are_independent_of_timestep(timestep):
    config = reference_config(battery_soc_pct=93, timestep_minutes=timestep)
    day = day_for(config)

    windows = running_windows(day)
    assert len(windows) == 2
    assert windows[0] == pytest.approx((7.3, 9.3))
    assert windows[1] == pytest.approx((17.3, 19.3))
    assert day.generator_hours == pytest.approx(4)
    assert day.battery_end_kwh == pytest.approx(5.3)
    assert day.generator_start_count == 2
    assert_physics(config, day)


def test_fuel_exhaustion_preserves_partial_charging_and_later_battery_supply():
    config = reference_config(battery_soc_pct=93, fuel_level_l=2.4)
    day = day_for(config)

    # 7.3 h on initial battery; 1.2 h on generator charges 4.8 kWh;
    # 4.8 h more on battery; 24 - 7.3 - 1.2 - 4.8 = 10.7 h unserved.
    assert running_windows(day)[0] == pytest.approx((7.3, 8.5))
    assert day.generator_to_load_kwh == pytest.approx(1.2)
    assert day.generator_to_battery_kwh == pytest.approx(4.8)
    assert day.unserved_load_kwh == pytest.approx(10.7)
    assert day.battery_end_kwh == pytest.approx(2)
    assert day.fuel_end_l == 0
    assert day.fuel_limited
    assert not day.generator_on_end
    assert_physics(config, day)


def test_running_generator_crosses_midnight_without_restarting():
    # 23 h until floor, then 5.75 h charging at net 4 kW.
    config = reference_config(battery_capacity_kwh=28.75, max_days=2)
    first, second = run_simulation(config).days

    assert first.generator_hours == pytest.approx(1)
    assert first.generator_on_end
    assert second.generator_on_start
    assert not second.steps[0].generator_started
    assert running_windows(second)[0] == pytest.approx((0, 4.75))
    assert second.generator_start_count == 0
    continued = simulate_day(
        config, day=2, battery_kwh=first.battery_end_kwh, fuel_l=first.fuel_end_l,
        generator_running=first.generator_on_end,
    )
    assert continued == second


def test_solar_and_generator_share_one_charge_limit_and_curve_uses_actual_output():
    config = reference_config(
        battery_soc_pct=20, gen_stop_soc_pct=80, current_load_kw=0,
        solar_capacity_kw=0.4, hourly_solar_kw=(0.4,) * 24,
        battery_max_charge_kw=1, initial_generator_running=True,
        gen_idle_fuel_lph=0.2, fuel_level_l=100,
    )
    day = day_for(config)

    # 0.4 kW solar + 0.6 kW generator charge from 2 to 8 kWh in 6 h.
    # Then solar alone reaches full capacity in 5 h, with the rest curtailed.
    assert day.generator_hours == pytest.approx(6)
    assert day.generator_to_battery_kwh == pytest.approx(3.6)
    assert day.fuel_used_l == pytest.approx(6 * (0.2 + 1.8 * 0.6 / 5))
    assert day.battery_end_kwh == pytest.approx(10)
    assert day.generator_start_count == 0
    assert_physics(config, day)


@pytest.mark.parametrize("idle, expected_fuel", [(None, 48), (0.2, 22.08)])
def test_battery_power_limit_starts_generator_even_with_full_battery(idle, expected_fuel):
    config = reference_config(
        current_load_kw=2, battery_max_discharge_kw=0.5,
        gen_idle_fuel_lph=idle, fuel_level_l=100,
    )
    day = day_for(config)
    assert day.generator_hours == pytest.approx(24)
    assert day.fuel_used_l == pytest.approx(expected_fuel)
    assert day.unserved_load_kwh == 0
    assert day.generator_on_end
    assert_physics(config, day)


@pytest.mark.parametrize("changes", [
    {"battery_max_charge_kw": 0},
    {"battery_max_discharge_kw": 0},
    {"current_load_kw": 8, "fuel_level_l": 100},
    {"current_load_kw": 8, "fuel_level_l": 1.3},
    {"battery_soc_pct": 10},
    {"fuel_level_l": 0},
    {"fuel_level_l": 0, "gen_fuel_lph": 0},
    {"current_load_kw": 0, "solar_capacity_kw": 0, "initial_generator_running": True},
    {"solar_capacity_kw": 4, "battery_charge_efficiency": 0.85,
     "battery_discharge_efficiency": 0.9, "battery_max_charge_kw": 0.3},
])
def test_limits_and_conservation_in_degenerate_and_overloaded_cases(changes):
    config = reference_config(**changes)
    assert_physics(config, day_for(config))


def test_hourly_profiles_and_solar_factors_are_integrated_exactly():
    config = reference_config(
        solar_capacity_kw=4, hourly_load_kw=tuple([0.2] * 8 + [2.0] * 8 + [0.5] * 8),
        hourly_solar_kw=tuple([0.0] * 6 + [3.0] * 12 + [0.0] * 6),
        daily_solar_factors=(0.5, 1), max_days=3, fuel_level_l=100,
    )
    result = run_simulation(config)
    assert [day.solar_kwh for day in result.days] == pytest.approx([18, 36, 18])
    assert [day.load_kwh for day in result.days] == pytest.approx([21.6] * 3)
    for day in result.days:
        assert_physics(config, day)


def test_zero_solar_window_and_24_hour_window_are_supported():
    zero = day_for(reference_config(solar_hours_per_day=0, solar_window_hours=0))
    assert zero.solar_kwh == 0
    always = day_for(reference_config(solar_capacity_kw=1, solar_hours_per_day=24))
    assert always.solar_to_load_kwh == pytest.approx(24)
    assert always.generator_hours == 0


def test_same_daily_solar_energy_with_small_storage_still_needs_generator():
    day = day_for(reference_config(solar_capacity_kw=4.8, battery_capacity_kwh=1))
    assert day.solar_kwh == pytest.approx(day.load_kwh)
    assert day.generator_hours > 0
    assert day.solar_to_load_kwh == pytest.approx(5)


@pytest.mark.parametrize("name, value", [
    ("max_days", 1.5), ("max_days", True), ("report_horizon_days", float("nan")),
    ("timestep_minutes", 7), ("timestep_minutes", False),
    ("solar_window_hours", 0), ("solar_window_hours", 4),
    ("solar_start_hour", 23), ("solar_start_hour", float("inf")),
    ("hourly_load_kw", [0] * 23), ("hourly_load_kw", [-1] * 24),
    ("hourly_solar_kw", [6] * 24), ("hourly_solar_kw", [float("nan")] * 24),
    ("daily_solar_factors", ()), ("daily_solar_factors", (1.1,)),
    ("battery_max_charge_kw", -1), ("battery_max_discharge_kw", float("inf")),
    ("gen_idle_fuel_lph", 3), ("initial_generator_running", 1),
])
def test_new_configuration_rejects_invalid_physical_or_temporal_inputs(name, value):
    with pytest.raises(ValueError):
        reference_config(solar_capacity_kw=2, **{name: value})


def test_profile_inputs_are_copied_and_override_daily_totals():
    load = [0.3] * 24
    solar = [0.5] * 24
    config = reference_config(solar_capacity_kw=1, hourly_load_kw=load, hourly_solar_kw=solar)
    load[0] = 100
    solar[0] = 100
    assert config.daily_load_kwh == pytest.approx(7.2)
    assert config.daily_solar_kwh == pytest.approx(12)
    assert isinstance(config.hourly_load_kw, tuple)


def test_configuration_rejects_empty_hysteresis_and_soc_above_max():
    with pytest.raises(ValueError, match="strictly above"):
        reference_config(gen_stop_soc_pct=20)
    with pytest.raises(ValueError, match="battery_soc_pct"):
        reference_config(max_soc_pct=90, gen_stop_soc_pct=80)
