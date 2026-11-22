# Read-only order preview and product details

The user approved implementing order.preview_update and catalog.get_details.
Current checkout contains the previous MCP data-contract repairs; preserve them.

## Requirements

1. order.preview_update accepts an owned order, return/exchange action, optional
   line_index/qty and replacement SKU. It uses the same current selection, paid
   amounts, replacement basket pricing, stock and fee calculation as order.update.
   It reports estimates, net payment/refund including fees, selected lines and
   replacement availability. It does not insert/update/claim an operation, reserve
   stock, complete a refund or establish policy eligibility. Reads require channel
   identity and ownership; verified shared-phone membership uses the signed read
   context. Model-controlled identity/proof fields cannot select an owner.
2. Executing order.update still needs current customer authorization and recomputes
   source data. A preview never authorizes a write or replaces policy verification.
3. catalog.get_details accepts one exact parent/variant SKU and returns a single
   catalog item, variant context, technical specifications and public source
   provenance. Approved SKU tables yield exact-row properties; ambiguous technical
   values remain unresolved. Existing catalog/spec authority is preserved.
4. Public prose and size tables are included through reviewed SKU-to-section
   bindings in data, with full contextual scope visible. No code guesses a product
   from a substring, borrows a current model's specs for an old model, or invents
   missing facts. Unknown SKU fails; known SKU without technical sources remains
   useful from catalog and explicitly reports missing technical information.
5. Both tools are registered through schemas, MCP handlers, gateway, model aliases,
   controller preparation and grounding. Detail results provide trusted catalog
   evidence for later SKU selection, policy context and durable observations.
   Preview amounts are estimates and cannot prove completed actions.

## Constraints and verification

No subagents/worktrees/commits, dependencies, comments/docstrings, live models,
traces/evaluation results, DB writes/imports, index work or deployment. Use current
source BTC catalog/public specification documents and independent synthetic tests.
Focused offline tests block sockets and disable dotenv/provider telemetry. Preserve
existing grants, exact payload binding, privacy and ownership. Self-review source,
end-to-end tool availability and write denial before marking complete.
