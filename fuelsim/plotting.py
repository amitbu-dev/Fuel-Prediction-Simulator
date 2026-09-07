"""Matplotlib views of a simulation run, for use inside the notebook."""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib.pyplot as plt

from fuelsim.results import SimulationResult

if TYPE_CHECKING:  # pragma: no cover - typing only
    from matplotlib.figure import Figure

SOURCE_COLUMNS = (
    ("solar_to_load_kwh", "Solar (direct)", "#f2b134"),
    ("battery_to_load_kwh", "Battery (discharge)", "#4a90d9"),
    ("generator_to_load_kwh", "Generator", "#8c8c8c"),
    ("unserved_load_kwh", "Unserved", "#d0021b"),
)


def _require_days(result: SimulationResult) -> None:
    if not result.days:
        raise ValueError("nothing to plot: the simulation produced no days")


def plot_trajectory(result: SimulationResult, *, figsize=(10, 8)) -> "Figure":
    """SOC, fuel level, and generator runtime over the simulated days."""
    _require_days(result)
    frame = result.to_frame()
    config = result.config

    fig, (soc_ax, fuel_ax, gen_ax) = plt.subplots(
        3, 1, figsize=figsize, sharex=True, constrained_layout=True
    )
    fig.suptitle(result.summary(), fontsize=11)

    soc_ax.plot(
        frame["day"], frame["soc_end_pct"], color="#4a90d9", label="end of day"
    )
    soc_ax.plot(
        frame["day"], frame["soc_min_pct"], color="#22558a", label="daily minimum"
    )
    soc_ax.axhline(
        config.gen_start_soc_pct,
        color="#d0021b",
        linestyle="--",
        linewidth=1,
        label=f"generator start ({config.gen_start_soc_pct:g}%)",
    )
    soc_ax.set_ylabel("Battery SOC (%)")
    soc_ax.set_ylim(0, 105)
    soc_ax.legend(loc="lower left", fontsize=8)
    soc_ax.grid(alpha=0.3)

    fuel_ax.plot(frame["day"], frame["fuel_end_l"], marker="o", color="#417505")
    fuel_ax.axhline(
        config.fuel_threshold_l,
        color="#d0021b",
        linestyle="--",
        linewidth=1,
        label=f"threshold ({config.fuel_threshold_l:g} L)",
    )
    fuel_ax.set_ylabel("Fuel remaining (L)")
    fuel_ax.legend(loc="lower left", fontsize=8)
    fuel_ax.grid(alpha=0.3)

    gen_ax.bar(frame["day"], frame["generator_hours"], color="#8c8c8c")
    gen_ax.set_ylabel("Generator (h/day)")
    gen_ax.set_xlabel("Day")
    gen_ax.set_ylim(0, max(frame["generator_hours"].max() * 1.2, 1.0))
    gen_ax.grid(alpha=0.3, axis="y")

    return fig


def plot_daily_energy(result: SimulationResult, *, figsize=(10, 4)) -> "Figure":
    """Stacked view of which source served the load each day."""
    _require_days(result)
    frame = result.to_frame()

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    bottom = frame["day"] * 0.0
    for column, label, color in SOURCE_COLUMNS:
        values = frame[column]
        if values.abs().max() == 0.0:
            continue
        ax.bar(frame["day"], values, bottom=bottom, label=label, color=color)
        bottom = bottom + values

    ax.set_title("Daily load coverage by immediate source")
    ax.set_xlabel("Day")
    ax.set_ylabel("Energy (kWh)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3, axis="y")

    return fig


def plot_intraday(
    result: SimulationResult, *, day: int = 1, figsize=(11, 8)
) -> "Figure":
    """Load supply, battery SOC, and generator operation in chronological order.

    Dispatch segments may be shorter than the configured interval when a state
    reaches a limit. Dividing each segment's energy by its actual duration keeps
    the displayed power and start/stop times faithful to the simulation.
    """
    _require_days(result)
    frame = result.to_step_frame()
    frame = frame.loc[frame["day"] == day]
    if frame.empty:
        raise ValueError(f"day {day} was not simulated")

    starts = frame["start_hour"].to_numpy()
    durations = frame["duration_hours"].to_numpy()
    ends = starts + durations
    edges = [starts[0], *ends]
    fig, (power_ax, soc_ax, gen_ax) = plt.subplots(
        3, 1, figsize=figsize, sharex=True, constrained_layout=True,
        gridspec_kw={"height_ratios": [2, 1.3, 0.8]},
    )
    fig.suptitle(f"Day {day}: load supply and battery operation", fontsize=12)
    bottom = starts * 0.0
    for column, label, color in SOURCE_COLUMNS:
        power = frame[column].to_numpy() / durations
        if abs(power).max() < 1e-9:
            continue
        power_ax.bar(
            starts, power, width=durations, align="edge", bottom=bottom,
            label=label, color=color, linewidth=0,
        )
        bottom = bottom + power
    power_ax.stairs(
        frame["load_kwh"].to_numpy() / durations, edges, baseline=None,
        color="#222222", linestyle="--", label="Load", linewidth=1.2,
    )
    power_ax.set_ylabel("Power to load (kW)")
    power_ax.legend(loc="upper right", fontsize=8, ncol=2)
    power_ax.grid(alpha=0.2, axis="y")

    soc_ax.plot(
        edges, [frame.iloc[0]["soc_start_pct"], *frame["soc_end_pct"]],
        color="#4a90d9", label="Battery SOC",
    )
    for value, label, color in (
        (result.config.gen_start_soc_pct, "generator start", "#d0021b"),
        (result.config.gen_stop_soc_pct, "generator stop", "#417505"),
    ):
        soc_ax.axhline(value, color=color, linestyle="--", linewidth=1, label=label)
    soc_ax.set_ylabel("Battery SOC (%)")
    soc_ax.set_ylim(0, 105)
    soc_ax.legend(loc="upper right", fontsize=8, ncol=3)
    soc_ax.grid(alpha=0.2)

    gen_ax.stairs(
        frame["generator_hours"].to_numpy() / durations, edges, fill=True,
        color="#8c8c8c", linewidth=0.8,
    )
    gen_ax.set_ylabel("Generator")
    gen_ax.set_yticks([0, 1], ["Off", "On"])
    gen_ax.set_ylim(-0.05, 1.15)
    gen_ax.set_xlim(0, 24)
    gen_ax.set_xticks(range(0, 25, 3))
    gen_ax.set_xlabel("Hour of day (simulation starts at midnight)")
    gen_ax.grid(alpha=0.2, axis="x")
    return fig
