import pytest
from fuelsim import SimulationConfig
from fuelsim.engine import simulate_day

def cfg(**kw):
    d = dict(battery_soc_pct=60, fuel_level_l=100, solar_capacity_kw=2.4, current_load_kw=12.8 / 24, battery_capacity_kwh=30, gen_start_soc_pct=20, gen_stop_soc_pct=80, gen_rated_kw=5, gen_fuel_lph=2, max_days=1)
    d.update(kw)
    return SimulationConfig(**d)

def test_temporal_arithmetic_example():
    d = simulate_day(cfg(), day=1, battery_kwh=18, fuel_l=100)
    assert d.solar_to_load_kwh == pytest.approx(2.6666666667)
    assert d.solar_to_battery_kwh == pytest.approx(9.3333333333)
    assert d.battery_to_load_kwh == pytest.approx(10.1333333333)
    assert d.fuel_used_l == pytest.approx(0)
    assert d.battery_end_kwh == pytest.approx(17.2)

def test_solar_never_serves_night_load():
    d = simulate_day(cfg(solar_capacity_kw=4.8, current_load_kw=1), day=1, battery_kwh=5, fuel_l=100)
    assert sum((s.solar_to_load_kwh for s in d.steps if s.start_hour >= 15 or s.start_hour < 9)) == pytest.approx(0)

def test_energy_and_fuel_balances_each_step():
    c = cfg(battery_charge_efficiency=0.9, battery_discharge_efficiency=0.8, current_load_kw=1)
    d = simulate_day(c, day=1, battery_kwh=c.initial_battery_kwh, fuel_l=100)
    for s in d.steps:
        assert s.load_kwh == pytest.approx(s.solar_to_load_kwh + s.battery_to_load_kwh + s.generator_to_load_kwh + s.unserved_load_kwh)
        assert s.solar_kwh == pytest.approx(s.solar_to_load_kwh + s.solar_to_battery_kwh + s.solar_curtailed_kwh)
        assert s.generator_energy_kwh == pytest.approx(s.generator_to_load_kwh + s.generator_to_battery_kwh)
        assert s.fuel_end_l == pytest.approx(s.fuel_start_l - s.fuel_used_l)

def test_fractional_window_and_timestep_conservation():
    c = cfg(solar_capacity_kw=2, solar_hours_per_day=3.14, solar_window_hours=3.14, solar_start_hour=9.13, timestep_minutes=15)
    d = simulate_day(c, day=1, battery_kwh=18, fuel_l=100)
    assert d.solar_kwh == pytest.approx(6.28)
    assert sum((s.duration_hours for s in d.steps)) == pytest.approx(24)

def test_five_and_fifteen_minute_constant_inputs_agree():
    a = simulate_day(cfg(timestep_minutes=15), day=1, battery_kwh=18, fuel_l=100)
    b = simulate_day(cfg(timestep_minutes=5), day=1, battery_kwh=18, fuel_l=100)
    assert a.battery_end_kwh == pytest.approx(b.battery_end_kwh)
    assert a.fuel_used_l == pytest.approx(b.fuel_used_l)

def test_zero_burn_low_load_is_possible():
    c = cfg(solar_capacity_kw=3.2, current_load_kw=0.5, battery_capacity_kwh=30, battery_soc_pct=100, gen_start_soc_pct=20, gen_stop_soc_pct=80, gen_fuel_lph=2.5, battery_charge_efficiency=0.95, battery_discharge_efficiency=0.95, max_days=3)
    d = simulate_day(c, day=1, battery_kwh=c.initial_battery_kwh, fuel_l=100)
    assert d.fuel_used_l == pytest.approx(0)
    assert d.generator_hours == pytest.approx(0)
    assert d.battery_to_load_kwh > 0
