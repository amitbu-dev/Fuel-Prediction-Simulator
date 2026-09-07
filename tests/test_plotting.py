"""Smoke tests for the notebook plotting helpers."""

import matplotlib
import pytest

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from fuelsim.engine import run_simulation  # noqa: E402
from fuelsim.plotting import plot_daily_energy, plot_intraday, plot_trajectory  # noqa: E402
from tests.test_simulation import reference_config  # noqa: E402


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


class TestPlotTrajectory:
    def test_draws_three_stacked_axes(self):
        result = run_simulation(reference_config())

        fig = plot_trajectory(result)

        assert len(fig.axes) == 3

    def test_marks_the_generator_start_and_fuel_threshold(self):
        result = run_simulation(reference_config(fuel_threshold_l=10.0))

        fig = plot_trajectory(result)
        soc_ax, fuel_ax, _ = fig.axes

        assert "generator start (20%)" in soc_ax.get_legend_handles_labels()[1]
        assert "daily minimum" in soc_ax.get_legend_handles_labels()[1]
        assert "threshold (10 L)" in fuel_ax.get_legend_handles_labels()[1]

    def test_refuses_to_plot_an_empty_simulation(self):
        result = run_simulation(reference_config(fuel_level_l=0.0))

        with pytest.raises(ValueError, match="no days"):
            plot_trajectory(result)


class TestPlotDailyEnergy:
    def test_labels_only_the_sources_that_contributed(self):
        result = run_simulation(reference_config(solar_capacity_kw=2.0))

        fig = plot_daily_energy(result)
        labels = fig.axes[0].get_legend_handles_labels()[1]

        assert set(labels) == {"Solar (direct)", "Battery (discharge)", "Generator"}

    def test_omits_sources_that_never_ran(self):
        result = run_simulation(reference_config(solar_capacity_kw=0.0))

        fig = plot_daily_energy(result)
        labels = fig.axes[0].get_legend_handles_labels()[1]

        assert "Solar (direct)" not in labels

    def test_refuses_to_plot_an_empty_simulation(self):
        result = run_simulation(reference_config(fuel_level_l=0.0))

        with pytest.raises(ValueError, match="no days"):
            plot_daily_energy(result)


class TestPlotIntraday:
    def test_displays_a_full_day_and_preserves_the_initial_soc(self):
        result = run_simulation(reference_config())

        fig = plot_intraday(result)

        assert len(fig.axes) == 3
        assert fig.axes[-1].get_xlim() == pytest.approx((0, 24))
        soc_line = fig.axes[1].lines[0]
        assert soc_line.get_xdata()[0] == pytest.approx(0)
        assert soc_line.get_xdata()[-1] == pytest.approx(24)
        assert soc_line.get_ydata()[0] == pytest.approx(result.config.battery_soc_pct)
        assert soc_line.get_ydata()[-1] == pytest.approx(result.days[0].soc_end_pct)

    def test_rejects_an_unsimulated_day(self):
        result = run_simulation(reference_config(max_days=1))

        with pytest.raises(ValueError, match="was not simulated"):
            plot_intraday(result, day=2)
