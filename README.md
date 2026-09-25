# Print Quote Engine

Release: **v0.7.0** · 7 recorded code revisions (6 updates after initial import). [Commit ledger](VERSION_HISTORY.json).

Count includes reachable non-merge commits touching the engine package, including merged development history; excludes documentation-only, tests-only, host-app changes and generated _version.py. It counts commits, not individual features or validated accuracy. Version convention: 0.<code revision count>.<release metadata fix>. Past results without a recorded version remain unknown.


Optional host-supplied `energy_model` and `energy_telemetry` snapshots enable estimated electricity costs. Matched historical print-phase average power is preferred; different bed sizes/temperatures use an explicitly low-confidence thermal scaling model. The host supplies geometry with provenance and telemetry grouped by observed heater temperatures. This package never connects to Home Assistant or stores connection credentials.

The result's `energy` field preserves estimated kWh, steady average W, assumed cold-start Wh, reference sample hours, geometry, temperature sources and assumptions. Direct `energy_kwh` input takes precedence. Old snapshots without `energy_model` retain legacy behavior. This is not metered consumption of a proposed job. The provisional model assumes a 35 W electronics/motor baseline, 12 W/m²/K effective bed heat loss, 0.12 W/K per heated hotend, and 3.5 W/m²/K active-chamber loss. A cold-start allowance uses a 3 mm aluminium-equivalent bed and 80% efficiency. These are configurable-model development assumptions, not verified manufacturer heater ratings. Unknown toolchanger standby heat, chamber leakage, fan speed, heat-up phase timing, auxiliary MMU/dryer circuits, insulation, and ambient conditions limit accuracy; real per-job calibration remains necessary.

Run portable tests with `python -m unittest discover -s tests`.

Optional quote inputs: `discount_percent` (decimal string, 0–100) and `discount_reason` (required for a positive discount, max 500 characters). Discounts apply to the final service subtotal and shipping; each is rounded to 1 KRW using half-up, and VAT is then recomputed with the supplied tax policy. The returned `discount` breakdown preserves original subtotal/VAT/shipping/total, reductions, percentage, reason, and rounding basis. Applying a new percentage recalculates from the undiscounted inputs rather than compounding the previous discount.

Standalone Decimal-based quote calculation. Call calculate(input, policy). The host supplies its policy; this repository contains no production rates, customer data, server configuration, or credentials. Extracted from PrintOps. Policy validation and portable example fixtures are still being developed.
