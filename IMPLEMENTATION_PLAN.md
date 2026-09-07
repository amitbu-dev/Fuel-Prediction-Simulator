# Chronological fuel simulator implementation plan

Status: implemented, reviewed, and verified.

## Objective

Replace daily net-energy dispatch with chronological dispatch. Solar can directly
serve only concurrent load; energy used later must pass through a capacity- and
power-limited battery. Keep the notebook's daily tables while exposing interval
flows. Do not force finite fuel endurance for a site that can sustain its load
under the assumed solar conditions.

The existing engine contains three bare asterisk lines causing a SyntaxError.
Remove them as part of replacing the engine. This folder is not a Git repository;
save a source/notebook backup before editing existing files.

## Scope and allocation

- A cheaper implementation agent owns `fuelsim/config.py`, `fuelsim/engine.py`,
  `fuelsim/results.py`, `fuelsim/__init__.py`, and all tests except
  `tests/test_plotting.py`. Implement the core and its regression tests.
- The parent owns this plan, `PLAN.md`, `fuelsim/plotting.py`,
  `tests/test_plotting.py`, and `fuel_prediction_poc.ipynb`. Integrate notebook
  reporting, review the implementation independently, and execute final checks.
- No cloud services, dependency upgrades, live weather integration, or new UI.
  Real measured load/solar forecasts can be supplied later using the profile API.

## 1. Inputs and explicit assumptions

Preserve existing configuration arguments and the controller adapter. Add:

- `timestep_minutes=15`: a positive integer dividing 60. Integrate events inside
  the interval instead of rounding generator start/stop times to 15 minutes.
- `solar_window_hours: float | None = None`: width of a flat daylight profile.
  None uses `solar_hours_per_day` as the width for an idealized full-output block.
  The existing `solar_hours_per_day` continues to set daily yield via
  `solar_capacity_kw * solar_hours_per_day`. An explicit wider window spreads
  that energy over more daylight hours without changing the daily total.
- `solar_start_hour: float | None = None`: None centers the window at noon.
  Explicit windows must fit within one 24-hour day. Split intervals exactly at
  sunrise/sunset, including fractional-hour boundaries. Zero yield must work.
  Reject a positive-yield window too short to deliver the yield at nameplate power.
- `hourly_load_kw: tuple[float, ...] | None = None` and
  `hourly_solar_kw: tuple[float, ...] | None = None`: optional 24-value actual
  power profiles, piecewise constant each hour, repeated daily. These override
  the respective scalar-derived profile and daily totals. Solar values cannot
  exceed the configured nameplate capacity. Copy sequences to immutable tuples.
- `daily_solar_factors=(1.0,)`: a nonempty repeating sequence of factors in [0, 1]
  multiplying solar output per day, allowing explicit sunny/cloudy scenarios.
  State clearly that this is an assumed repeating scenario, not a weather forecast.
- `battery_max_charge_kw: float | None = None` and
  `battery_max_discharge_kw: float | None = None`: optional nonnegative limits;
  None means unspecified/unlimited for compatibility. Charge limit is input-side
  power before charge losses. Discharge limit is output power delivered to load.
  Solar and generator share the same charging limit.
- `gen_idle_fuel_lph: float | None = None`: optional linear fuel-curve intercept.
  When supplied, fuel rate while running is
  `idle + (gen_fuel_lph - idle) * actual_output_kw / gen_rated_kw`.
  Require 0 <= idle <= rated fuel rate. None preserves a constant `gen_fuel_lph`
  while running; document that this is a simplifying assumption at partial load.

Existing efficiency defaults may stay at 1.0 for API compatibility. The notebook
will explicitly use illustrative charge/discharge efficiencies of 0.95, labeled
as assumptions. Validate all numbers as finite, counts as actual positive integers,
and initial SOC <= max SOC. Require stop SOC strictly above start SOC, documenting
the validation tightening; an empty hysteresis window must not cause an infinite
start/stop loop. Do not infer actual equipment limits or measured efficiencies.

## 2. Chronological dispatch and persistent state

Maintain battery kWh, fuel L, and generator on/off state across every interval and
across midnight. Default measured start state is midnight with generator off;
expose an optional initial running flag if useful, and allow `simulate_day` callers
to pass previous generator state. Retain `simulate_day` and `run_simulation`.

At each piecewise-constant interval:

1. Route solar to the concurrent load first.
2. Route surplus solar into available battery headroom, subject to charge power
   and efficiency; record rejected energy as curtailment.
3. With the generator off, discharge the battery to cover deficit, subject to
   output power and the generator-start SOC floor.
4. Start the generator if deficit exists and SOC reaches the start threshold,
   or if the battery's power limit prevents it meeting the deficit. A battery
   already below the threshold may charge but must not discharge further.
5. A running generator supplies the remaining load first, then charges toward
   stop SOC using remaining rating and the charging limit after solar charging.
   Actual generator output is at most nameplate and equals useful allocated power.
   Battery assistance for loads beyond generator rating is allowed only above
   its floor and within discharge limits. Never charge and discharge together.
6. Stop at stop SOC when the remaining demand is within battery discharge power;
   otherwise keep supplying required demand. A generator already running can
   continue charging toward stop SOC even if solar now covers all load.
7. Split at battery floor, stop SOC, max SOC, and actual fuel exhaustion. Apply
   efficiencies and fuel consumption only to actual durations. Handle zero charge
   limits, zero solar/load/fuel, and insufficient generator power without spinning.
8. Record unmet load if the available sources cannot serve it. Never create energy
   or discharge below the configured reserve floor to conceal an infeasible site.

Use a small numerical tolerance only for roundoff, not a minimum fuel burn or a
forced minimum forecast duration. Preserve the current day-level stopping contract:
finish the day's accounting and stop the multi-day run after the first day whose
fuel reaches/breaches the refueling threshold. Handle true empty-tank events at
their actual time within the day. All days therefore remain full 24-hour records.

## 3. Results and API contract for integration

- Add immutable `StepRecord` records for actual constant-dispatch segments, with
  `day`, `start_hour` (within day), `duration_hours`, and the same energy-flow,
  battery, fuel, and SOC fields as appropriate from `DayRecord`. Include
  `battery_charge_loss_kwh`, `battery_discharge_loss_kwh`, and generator state.
  `generator_hours` describes actual running duration, not energy / rated power.
- Preserve existing `DayRecord` columns as sums over these segments. Add
  `soc_min_pct`, `soc_max_pct`, charge/discharge losses, generator start count,
  `generator_on_start`, and `generator_on_end`. Store day segments in a
  `steps` tuple excluded from the daily DataFrame.
- Preserve `SimulationResult.days`, `days_until_threshold`, and `to_frame()`.
  Add `to_step_frame()` exposing flattened segment records for plotting and audit.
  Avoid nested segment data in daily DataFrame rows.
- `days_until_threshold=None` means only that the threshold was not reached within
  the actual simulated horizon. `summary()` must say that explicitly, and must
  distinguish zero modeled fuel consumption from positive consumption that simply
  did not reach the threshold. Do not claim perpetual operation.
- Keep `format_days_until` compatibility where possible. For unreached runs,
  `days_display` must not claim `>30 days` if fewer than 30 days were simulated;
  bound its displayed horizon by actual simulated days. Explain the actual horizon
  in `summary()` even when the compact display is capped for reporting.
- Include unmet demand in summary output when nonzero, so endurance is not mistaken
  for continuous successful service.

Per-segment and per-day invariants:

```
load = solar_to_load + battery_to_load + generator_to_load + unserved
solar = solar_to_load + solar_to_battery + solar_curtailed
generator_energy = generator_to_load + generator_to_battery
battery_end - battery_start = eta_charge * (solar_to_battery + generator_to_battery)
                            - battery_to_load / eta_discharge
fuel_end = fuel_start - fuel_used
```

## 4. Required behavioral tests

Replace assertions that deliberately encode the old daily netting model with
independently calculated temporal expectations. Preserve valid config, controller,
and reporting coverage. Do not merely update expected values to whatever code emits.

- User's example: constant 12.8/24 kW load, 2.4 kW solar for five hours centered
  at noon, 30 kWh battery starting at 60%, floor 20%, stop 80%, ideal efficiency.
  Day 1: direct solar 2.6666667 kWh, solar charging 9.3333333 kWh, battery output
  10.1333333 kWh, net battery decline 0.8 kWh, no generator/curtailment.
- Equal daily solar/load with a small battery must use generator fuel or have
  unserved overnight demand. Direct solar must never serve nighttime load.
- Ample storage and adequate solar: battery cycles overnight while fuel can remain
  unchanged. A 0.5 kW load must not be assigned arbitrary positive fuel burn.
- Losses apply to the full energy passing through the battery, including solar
  charging and nighttime discharge, rather than only to the daily net deficit.
- Generator start/stop at fractional intervals, repeated cycles, running across
  midnight, full/empty battery, fuel exhaustion, and overload/charge/discharge limits.
- Solar windows not aligned with intervals and hourly profile boundaries conserve
  exact input energy. Zero-length solar with zero yield remains valid.
- A repeating cloudy-day sequence differs from repeating full-solar days.
- Optional fuel curve uses actual output and actual running time; constant default
  remains explicit. Validate zero fuel rate behavior as a mathematical edge case.
- Check all energy/fuel balances and state continuity on representative scenarios;
  compare 15- and 5-minute results for constant/block inputs to catch timing drift.
- Unreached forecasts with zero and nonzero burn, horizons shorter than reporting
  cap, and unmet demand get accurate wording.

## 5. Notebook, documentation, and verification

Preserve the user's saved baseline measurements (100% SOC, 100 L fuel, 3.2 kW solar,
0.7 kW load, 30 kWh battery, 20/80% thresholds, 5 kW generator, 2.5 L/h fuel).
Expose new settings explicitly. Use a clearly labeled idealized five-hour solar
window initially so the contribution comparison is easy to follow; demonstrate a
wider daylight window separately. Keep the 30-day reporting cap and the user's
216-day computation horizon. Explain assumed 0.95 charge/discharge efficiencies.

Update daily contribution and SOC plots; show daily minimum SOC as well as ending
SOC, and add an intraday plot of power contributions, SOC, and generator operation.
Add examples for 0.5 versus 0.7 kW, the 12.8 kWh arithmetic check, a small battery,
and cloudy days. Replace obsolete claims that generator-start SOC has no effect or
that the notebook still runs the AlphaM baseline. Update `PLAN.md` to describe the
implemented chronological model and distinguish remaining forecast assumptions.

Run `.venv/Scripts/python.exe -m pytest --cov=fuelsim --cov-report=term-missing`.
Review coverage for consequential untested dispatch branches; do not chase 100%
through redundant assertions. Execute the notebook end to end with fresh outputs,
inspect representative plots and the baseline low-load results, and record final
verification here. No dependency installs are expected.

## Acceptance

- Source imports successfully and all meaningful tests pass.
- Gross energy contributions have correct timing and match independent examples.
- Battery and generator states survive midnight; power/energy/fuel limits hold.
- Legitimate zero-burn operation remains possible and is reported conditionally.
- Updated notebook runs cleanly and visibly explains daily net versus gross flows.
- Parent review and actual verification outcomes are recorded before completion.

## Completion and verification

- The cheaper implementation agent was GPT-5.6 Luna. It implemented the initial
  core/configuration/results changes and revised regression tests. Parent review
  identified missing event splitting and several physical-limit issues. The
  parent completed the event-based solver, corrected fuel-exhaustion accounting,
  added independent event/limit tests, and integrated the notebook and plots.
- Original files were backed up before editing at
  `artifacts/pre-timestep-upgrade-20260906-115052.zip`.
- Final pytest run: **116 passed**, **99% statement coverage** (528 statements,
  7 uncovered, primarily invalid manual-state guards and unexecuted display states).
  The only warning was an environment permission warning writing pytest's optional
  cache; assertions and coverage completed successfully. Use `-p no:cacheprovider`
  when running tests in a restricted Windows environment.
- The full notebook executed successfully with a fresh project-venv Python kernel:
  **21 cells**, no cell errors, and all notebook conservation assertions passed.
  Jupyter required local Windows permission operations for its connection file;
  execution succeeded using the approved local process permissions, without
  disabling connection-file security or installing packages.
- Reviewed the saved daily trajectory and intraday charts. Generator intervals
  end at the configured stop SOC, nighttime supply comes from battery/generator,
  and daily minimum SOC is visible alongside ending SOC.
- The independent 12.8 kWh example matches direct solar **2.6667 kWh**, solar
  charging **9.3333 kWh**, battery discharge **10.1333 kWh**, and net depletion
  **0.8 kWh**, with no fuel used.
- Notebook scenarios with explicitly assumed 0.95 charge/discharge efficiencies:

  | Scenario | Threshold result | Modeled fuel consumed |
  | --- | --- | --- |
  | 0.7 kW, 30 kWh battery, repeated full solar | Day 73 | 86.65 L |
  | 0.5 kW, 30 kWh battery, repeated full solar | Not reached within 216 days | 0 L |
  | 0.5 kW, 2 kWh battery, repeated full solar | Day 17 | 82.81 L |
  | 0.5 kW, 30 kWh battery, two 10%-solar days per week | Day 53 | 84.21 L |

  These are scenario results, not calibrated real-world forecasts. Fuel totals may
  pass the 80 L available above the threshold because the final day is completed
  before termination, as specified by the day-level reporting contract.
- Remaining assumptions are documented in `PLAN.md` and the notebook: repeated
  profiles, assumed efficiencies, unspecified baseline battery power ratings,
  and no measured weather/controller calibration.
