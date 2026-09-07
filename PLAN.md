# Fuel prediction simulator

The simulator follows load, solar, battery energy, generator operation, and fuel
chronologically. Daily reports aggregate those flows; they do not offset nighttime
load against daytime solar without passing energy through the battery.

The original daily model and notebook are preserved in the source backup under
`artifacts/pre-timestep-upgrade-*.zip`. The implementation and acceptance criteria
are recorded in `IMPLEMENTATION_PLAN.md`.

## Run

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=fuelsim --cov-report=term-missing -p no:cacheprovider
.\.venv\Scripts\jupyter.exe lab fuel_prediction_poc.ipynb
```

To execute every notebook cell with the project's Python and save fresh outputs:

```powershell
.\.venv\Scripts\python.exe -B artifacts\execute_notebook.py
```

## Model

- The simulation begins at midnight. Load is constant unless a 24-value hourly
  power profile is supplied. All profiles are piecewise constant.
- Solar yield is `solar_capacity_kw * solar_hours_per_day`. An independent
  `solar_window_hours` spreads that energy uniformly across daylight. If omitted,
  the default is a full-output block lasting `solar_hours_per_day`, centered at noon.
  `hourly_solar_kw` overrides that simple profile. Solar power cannot exceed nameplate.
- `daily_solar_factors` is a repeating sequence in [0, 1], useful for explicitly
  assumed cloudy-day scenarios. It is not a forecast of actual weather.
- Input intervals default to 15 minutes. The solver also splits at solar/profile
  boundaries, battery floor/stop/full events, and fuel exhaustion, so generator
  runtime is not rounded to the interval size.
- Solar serves concurrent load first, and surplus charges the battery. Battery
  discharge is limited by the generator-start SOC floor and optional output power.
- The generator starts when battery energy or discharge power cannot serve the
  demand. It supplies load first, then charges toward stop SOC. A running generator
  remains on until stop SOC unless it runs out of fuel; a load exceeding battery
  discharge power can require it to remain on even at stop SOC.
- Solar and generator charging share one optional input power limit. The battery
  does not charge and discharge simultaneously. Generator output is limited to
  its rating; a battery above its floor may assist an overloaded generator.
- Default battery efficiencies remain 1.0 for API compatibility. The notebook
  explicitly uses illustrative 0.95 charge and 0.95 discharge efficiencies.
- By default the generator burns constant `gen_fuel_lph` while running, including
  partial output. Optional `gen_idle_fuel_lph` defines a linear fuel curve between
  idle and rated output. Use equipment data to set it.
- Battery kWh, fuel L, and generator on/off state carry across midnight. The start
  SOC is a reserve floor; unmet demand is recorded instead of silently discharging
  below that floor. A measured initial SOC below the floor may charge but cannot
  discharge further.
- Each day is fully accounted for. The run ends after the first day at/below the
  refueling threshold or after `max_days`. Actual tank exhaustion stops generator
  output at its physical time within the day.

## Results and interpretation

`SimulationResult.to_frame()` returns daily totals, ending states, minimum/maximum
SOC, charging/discharging losses, and generator starts. `to_step_frame()` exposes
the chronological constant-dispatch segments for auditing and intraday plots.
`simulate_day(..., generator_running=previous.generator_on_end)` supports manual
continuation; `run_simulation` carries that state automatically.

`*_to_load_kwh` means energy delivered to load. `*_to_battery_kwh` means energy
from the source before charging losses. Battery net change is ending minus starting
stored energy; it is different from gross battery discharge.

An unreached fuel threshold means it was not reached within the simulated window
under the assumed profiles. The summary distinguishes zero fuel consumption from
positive consumption that has not yet reached the threshold. Compact reporting
is capped at 30 days by default and never claims a longer horizon than simulated.
Unmet demand is included in the summary because endurance alone does not establish
successful service.

The main notebook retains the user's saved baseline: 100% SOC, 100 L fuel, 3.2 kW
solar, 0.7 kW load, 30 kWh battery, 20/80% generator SOC thresholds, 5 kW generator,
2.5 L/h fuel rate, 20 L refueling threshold, and a 216-day simulation horizon.

## Code layout

- `fuelsim/config.py`: immutable validated inputs and profile configuration.
- `fuelsim/engine.py`: chronological dispatch, exact events, and daily aggregation.
- `fuelsim/results.py`: step/day records, DataFrames, and prediction wording.
- `fuelsim/plotting.py`: daily trajectories/energy and intraday supply/SOC/runtime.
- `fuelsim/controller.py`: controller-row adapter; its inferred column mapping
  remains explicitly unverified and should be checked against a real schema.
- `tests/`: independent arithmetic, physical limits, continuity, and reporting.
- `fuel_prediction_poc.ipynb`: inputs, examples, scenario comparisons, and charts.

## Remaining assumptions

There is no live weather service, seasonality, battery degradation/temperature,
inverter standby consumption, generator start delay, minimum runtime, or maintenance
exercise policy. Battery power limits are optional and unspecified in the baseline.
The configured efficiencies and repeated profiles are assumptions, not measurements.
Very long endurance under identical sunny days should not be interpreted as a
reliable long-term prediction. Use measured hourly inputs and cloudy sequences.

Generator-start SOC and battery capacity can now affect timing, curtailment, and
fuel use. The old daily model's claims that these parameters had no effect are
obsolete. Controller mapping ambiguity is not validated merely by similar fuel-day
predictions.

Validation now requires stop SOC strictly above start SOC (to avoid an empty
hysteresis window), initial SOC at/below max SOC, and positive integer day horizons
and supported timestep sizes. Invalid configurations previously accepted by the
simplified model may now raise `ValueError`.
