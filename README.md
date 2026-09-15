# Print Quote Engine

Optional quote inputs: `discount_percent` (decimal string, 0–100) and `discount_reason` (required for a positive discount, max 500 characters). Discounts apply to the final service subtotal and shipping; each is rounded to 1 KRW using half-up, and VAT is then recomputed with the supplied tax policy. The returned `discount` breakdown preserves original subtotal/VAT/shipping/total, reductions, percentage, reason, and rounding basis. Applying a new percentage recalculates from the undiscounted inputs rather than compounding the previous discount.

Standalone Decimal-based quote calculation. Call calculate(input, policy). The host supplies its policy; this repository contains no production rates, customer data, server configuration, or credentials. Extracted from PrintOps. Policy validation and portable example fixtures are still being developed.
