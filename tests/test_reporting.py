import pytest
from fuelsim.engine import run_simulation
from fuelsim.results import format_days_until
from tests.test_simulation import reference_config

@pytest.mark.parametrize("days, expected", [
    (0, "0 days"), (1, "1 day"), (6, "6 days"), (30, "30 days"),
    (31, ">30 days"), (None, ">30 days"),
])
def test_format_days_until_compatibility(days, expected):
    assert format_days_until(days, horizon_days=30) == expected


@pytest.mark.parametrize("days, horizon", [(-1, 30), (1, 0), (1, -1)])
def test_invalid_reporting_inputs_are_rejected(days, horizon):
    with pytest.raises(ValueError):
        format_days_until(days, horizon_days=horizon)


def test_unreached_display_is_bounded_by_actual_horizon():
    r = run_simulation(reference_config(solar_capacity_kw=20, max_days=3))
    assert r.days_until_threshold is None
    assert r.days_display == '>3 days'
    assert '3-day simulated horizon' in r.summary()

def test_summary_distinguishes_burn_and_unserved_load():
    r = run_simulation(reference_config(fuel_level_l=1, max_days=1))
    text = r.summary()
    assert 'unmet load' in text
    assert 'fuel consumption' in text

def test_empty_simulation_frame_is_valid():
    r = run_simulation(reference_config(fuel_level_l=0, max_days=3))
    assert r.to_frame().empty
