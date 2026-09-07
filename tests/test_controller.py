"""Tests for the controller-configuration row adapter."""

import pytest

from fuelsim.controller import (
    CONTROLLER_COLUMNS,
    ControllerRecord,
    parse_controller_row,
)
from fuelsim.engine import run_simulation

# The AlphaM Config row, verbatim.
ALPHAM_ROW = (
    "a71b90ac-f36d-4530-9eae-422dc0e2ba86\tAlphaM Config\t"
    "c053e9f6-d80b-433d-9647-b547dc6f175e\t"
    "30.0\t5.0\t5.0\t5.0\t190.0\t20.0\t20.0\t3.19\t6.0\t180.0"
)


class TestParse:
    def test_reads_the_identity_columns(self):
        record = parse_controller_row(ALPHAM_ROW)

        assert record.controller_id == "a71b90ac-f36d-4530-9eae-422dc0e2ba86"
        assert record.name == "AlphaM Config"
        assert record.site_id == "c053e9f6-d80b-433d-9647-b547dc6f175e"

    def test_reads_every_numeric_column(self):
        record = parse_controller_row(ALPHAM_ROW)

        assert record.values == {
            "battery_capacity_kwh": 30.0,
            "solar_capacity_kw": 5.0,
            "solar_hours_per_day": 5.0,
            "current_load_kw": 5.0,
            "tank_capacity_l": 190.0,
            "gen_start_soc_pct": 20.0,
            "fuel_threshold_l": 20.0,
            "gen_fuel_lph": 3.19,
            "gen_rated_kw": 6.0,
            "fuel_level_l": 180.0,
        }

    def test_column_layout_covers_every_field_once(self):
        assert len(CONTROLLER_COLUMNS) == len(set(CONTROLLER_COLUMNS))
        assert len(CONTROLLER_COLUMNS) == 13

    def test_tolerates_surrounding_whitespace_and_a_trailing_newline(self):
        record = parse_controller_row(ALPHAM_ROW.replace("\t30.0", "\t 30.0 ") + "\n")

        assert record.values["battery_capacity_kwh"] == pytest.approx(30.0)

    def test_rejects_a_row_with_the_wrong_column_count(self):
        with pytest.raises(ValueError, match="expected 13 columns"):
            parse_controller_row("only\tthree\tcolumns")

    def test_rejects_a_non_numeric_value(self):
        broken = ALPHAM_ROW.replace("\t3.19\t", "\tn/a\t")

        with pytest.raises(ValueError, match="gen_fuel_lph"):
            parse_controller_row(broken)


class TestToSimulationConfig:
    def test_maps_the_columns_onto_the_simulator(self):
        record = parse_controller_row(ALPHAM_ROW)

        config = record.to_simulation_config(battery_soc_pct=100.0)

        assert config.battery_capacity_kwh == pytest.approx(30.0)
        assert config.solar_capacity_kw == pytest.approx(5.0)
        assert config.solar_hours_per_day == pytest.approx(5.0)
        assert config.current_load_kw == pytest.approx(5.0)
        assert config.gen_start_soc_pct == pytest.approx(20.0)
        assert config.fuel_threshold_l == pytest.approx(20.0)
        assert config.gen_fuel_lph == pytest.approx(3.19)
        assert config.gen_rated_kw == pytest.approx(6.0)
        assert config.fuel_level_l == pytest.approx(180.0)

    def test_battery_soc_is_required_because_it_is_not_configuration(self):
        record = parse_controller_row(ALPHAM_ROW)

        with pytest.raises(TypeError):
            record.to_simulation_config()  # type: ignore[call-arg]

    def test_a_live_load_reading_overrides_the_column(self):
        record = parse_controller_row(ALPHAM_ROW)

        config = record.to_simulation_config(battery_soc_pct=100.0, current_load_kw=8.0)

        assert config.current_load_kw == pytest.approx(8.0)

    def test_extra_overrides_reach_the_config(self):
        record = parse_controller_row(ALPHAM_ROW)

        config = record.to_simulation_config(battery_soc_pct=100.0, max_days=90)

        assert config.max_days == 90

    def test_tank_capacity_is_parsed_but_not_a_simulator_input(self):
        record = parse_controller_row(ALPHAM_ROW)

        assert record.values["tank_capacity_l"] == pytest.approx(190.0)
        assert not hasattr(record.to_simulation_config(battery_soc_pct=100.0),
                           "tank_capacity_l")

    def test_invalid_column_values_are_rejected_by_config_validation(self):
        record = ControllerRecord(
            controller_id="x", name="y", site_id="z",
            values={**parse_controller_row(ALPHAM_ROW).values, "gen_rated_kw": 0.0},
        )

        with pytest.raises(ValueError, match="gen_rated_kw"):
            record.to_simulation_config(battery_soc_pct=100.0)


class TestAlphaMPrediction:
    def test_the_alpham_site_prediction_is_pinned(self):
        record = parse_controller_row(ALPHAM_ROW)
        config = record.to_simulation_config(battery_soc_pct=100.0, max_days=90)

        result = run_simulation(config)

        assert result.days_until_threshold == 4
        assert result.days_display == "4 days"

    @pytest.mark.parametrize(
        "battery_capacity_kwh, gen_start_soc_pct",
        [(30.0, 20.0), (20.0, 30.0)],
    )
    def test_swapping_the_ambiguous_battery_columns_does_not_move_the_answer(
        self, battery_capacity_kwh, gen_start_soc_pct
    ):
        record = parse_controller_row(ALPHAM_ROW)

        config = record.to_simulation_config(
            battery_soc_pct=100.0,
            max_days=90,
            battery_capacity_kwh=battery_capacity_kwh,
            gen_start_soc_pct=gen_start_soc_pct,
        )

        assert run_simulation(config).days_until_threshold == 4
