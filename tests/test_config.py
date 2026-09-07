"""Validation and derived-value tests for SimulationConfig."""

import math

import pytest

from fuelsim.config import SimulationConfig


def make_config(**overrides) -> SimulationConfig:
    """Baseline config used across tests; override only what a test cares about."""
    defaults = dict(
        battery_soc_pct=100.0,
        fuel_level_l=50.0,
        solar_capacity_kw=0.0,
        current_load_kw=1.0,
        battery_capacity_kwh=10.0,
        gen_start_soc_pct=20.0,
        gen_stop_soc_pct=100.0,
        gen_rated_kw=5.0,
        gen_fuel_lph=2.0,
        fuel_threshold_l=0.0,
    )
    defaults.update(overrides)
    return SimulationConfig(**defaults)


class TestDerivedValues:
    def test_daily_load_is_momentary_load_over_24h(self):
        config = make_config(current_load_kw=1.5)

        assert config.daily_load_kwh == pytest.approx(36.0)

    def test_daily_solar_uses_fixed_production_hours(self):
        config = make_config(solar_capacity_kw=2.0, solar_hours_per_day=5.0)

        assert config.daily_solar_kwh == pytest.approx(10.0)

    def test_soc_percent_converts_to_stored_energy(self):
        config = make_config(battery_capacity_kwh=20.0)

        assert config.battery_kwh_at(50.0) == pytest.approx(10.0)

    def test_stored_energy_converts_back_to_soc_percent(self):
        config = make_config(battery_capacity_kwh=20.0)

        assert config.soc_pct_at(5.0) == pytest.approx(25.0)

    def test_generator_thresholds_expose_energy_levels(self):
        config = make_config(
            battery_capacity_kwh=10.0, gen_start_soc_pct=20.0, gen_stop_soc_pct=90.0
        )

        assert config.gen_start_battery_kwh == pytest.approx(2.0)
        assert config.gen_stop_battery_kwh == pytest.approx(9.0)

    def test_initial_and_max_battery_energy(self):
        config = make_config(
            battery_capacity_kwh=10.0,
            battery_soc_pct=40.0,
            max_soc_pct=95.0,
            gen_stop_soc_pct=95.0,
        )

        assert config.initial_battery_kwh == pytest.approx(4.0)
        assert config.max_battery_kwh == pytest.approx(9.5)


class TestValidation:
    @pytest.mark.parametrize("soc", [-1.0, 100.1, math.nan])
    def test_rejects_out_of_range_battery_soc(self, soc):
        with pytest.raises(ValueError, match="battery_soc_pct"):
            make_config(battery_soc_pct=soc)

    def test_rejects_negative_fuel_level(self):
        with pytest.raises(ValueError, match="fuel_level_l"):
            make_config(fuel_level_l=-1.0)

    def test_rejects_negative_solar_capacity(self):
        with pytest.raises(ValueError, match="solar_capacity_kw"):
            make_config(solar_capacity_kw=-0.1)

    def test_rejects_negative_load(self):
        with pytest.raises(ValueError, match="current_load_kw"):
            make_config(current_load_kw=-0.1)

    def test_rejects_non_positive_battery_capacity(self):
        with pytest.raises(ValueError, match="battery_capacity_kwh"):
            make_config(battery_capacity_kwh=0.0)

    def test_rejects_non_positive_generator_rating(self):
        with pytest.raises(ValueError, match="gen_rated_kw"):
            make_config(gen_rated_kw=0.0)

    def test_rejects_negative_fuel_rate(self):
        with pytest.raises(ValueError, match="gen_fuel_lph"):
            make_config(gen_fuel_lph=-1.0)

    def test_rejects_stop_soc_below_start_soc(self):
        with pytest.raises(ValueError, match="gen_stop_soc_pct"):
            make_config(gen_start_soc_pct=60.0, gen_stop_soc_pct=50.0)

    def test_rejects_stop_soc_above_max_soc(self):
        with pytest.raises(ValueError, match="gen_stop_soc_pct"):
            make_config(gen_stop_soc_pct=100.0, max_soc_pct=90.0)

    @pytest.mark.parametrize("hours", [-1.0, 24.1])
    def test_rejects_impossible_solar_hours(self, hours):
        with pytest.raises(ValueError, match="solar_hours_per_day"):
            make_config(solar_hours_per_day=hours)

    @pytest.mark.parametrize("efficiency", [0.0, 1.1])
    def test_rejects_out_of_range_charge_efficiency(self, efficiency):
        with pytest.raises(ValueError, match="battery_charge_efficiency"):
            make_config(battery_charge_efficiency=efficiency)

    @pytest.mark.parametrize("efficiency", [0.0, 1.1])
    def test_rejects_out_of_range_discharge_efficiency(self, efficiency):
        with pytest.raises(ValueError, match="battery_discharge_efficiency"):
            make_config(battery_discharge_efficiency=efficiency)

    def test_rejects_negative_fuel_threshold(self):
        with pytest.raises(ValueError, match="fuel_threshold_l"):
            make_config(fuel_threshold_l=-1.0)

    def test_rejects_non_positive_max_days(self):
        with pytest.raises(ValueError, match="max_days"):
            make_config(max_days=0)

    def test_rejects_non_positive_report_horizon(self):
        with pytest.raises(ValueError, match="report_horizon_days"):
            make_config(report_horizon_days=0)


class TestImmutability:
    def test_config_is_frozen(self):
        config = make_config()

        with pytest.raises(Exception):
            config.current_load_kw = 2.0  # type: ignore[misc]

    def test_with_changes_returns_new_validated_config(self):
        config = make_config(current_load_kw=1.0)

        updated = config.with_changes(current_load_kw=3.0)

        assert config.current_load_kw == pytest.approx(1.0)
        assert updated.current_load_kw == pytest.approx(3.0)

    def test_with_changes_revalidates(self):
        config = make_config()

        with pytest.raises(ValueError, match="current_load_kw"):
            config.with_changes(current_load_kw=-5.0)
