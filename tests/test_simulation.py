import pytest
from fuelsim import SimulationConfig
from fuelsim.engine import run_simulation
REFERENCE_INPUTS = dict(solar_capacity_kw=0.0, current_load_kw=1.0, battery_capacity_kwh=10.0, battery_soc_pct=100.0, gen_start_soc_pct=20.0, gen_stop_soc_pct=100.0, gen_rated_kw=5.0, gen_fuel_lph=2.0, fuel_level_l=50.0, fuel_threshold_l=0.0)

def reference_config(**overrides):
    return SimulationConfig(**{**REFERENCE_INPUTS, **overrides})

def test_reference_day_has_two_generator_windows_and_exact_burn():
    d = run_simulation(reference_config(max_days=1)).days[0]
    assert d.generator_hours == pytest.approx(4.0)
    assert d.fuel_used_l == pytest.approx(8.0)
    assert d.battery_end_kwh == pytest.approx(6.0)
    assert d.generator_start_count == 2

def test_state_and_fuel_carry_across_midnight():
    r = run_simulation(reference_config(max_days=3))
    for a, b in zip(r.days, r.days[1:]):
        assert b.battery_start_kwh == pytest.approx(a.battery_end_kwh)
        assert b.fuel_start_l == pytest.approx(a.fuel_end_l)

def test_fractional_start_stop_and_fuel_exhaustion_are_auditable():
    c = reference_config(battery_soc_pct=93, fuel_level_l=2.4, max_days=1)
    d = run_simulation(c).days[0]
    assert d.generator_hours == pytest.approx(1.2, abs=0.05)
    assert d.fuel_end_l == pytest.approx(0)
    assert d.unserved_load_kwh > 0

def test_cloud_factors_change_solar_but_repeat_by_sequence():
    c = reference_config(solar_capacity_kw=2, solar_hours_per_day=5, daily_solar_factors=(1, 0.5, 0), max_days=3)
    r = run_simulation(c)
    assert r.days[0].solar_kwh == pytest.approx(10)
    assert r.days[1].solar_kwh == pytest.approx(5)
    assert r.days[2].solar_kwh == pytest.approx(0)

def test_to_frame_excludes_nested_steps_and_step_frame_flattens():
    r = run_simulation(reference_config(max_days=1))
    assert len(r.to_frame()) == 1
    assert 'steps' not in r.to_frame().columns
    assert len(r.to_step_frame()) > 1
