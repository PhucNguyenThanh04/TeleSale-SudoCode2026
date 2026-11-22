# MCP contracts for BTC data

The user authorized repairing all eight findings from the source/loader/tool
audit, with the earlier autonomous spec → plan → execution workflow. Preserve
general behavior, existing write authorization and source provenance. No trace,
scenario conversation, QA labels or evaluation results are implementation inputs.

## Requirements

1. Preserve verified identity across shared-phone reads and writes. A signed
   write context may select exactly its verified customer among the source
   channel's CRM matches. Pricing and order-status reads use signed identity
   context bound to the actual request and channel. Unsigned ambiguous lookups
   remain ambiguous; raw customer IDs cannot choose an owner. Reject mismatched,
   altered, expired and foreign grants, and retain order ownership checks.
2. Make order updates understand stored order lines, quantities and actual paid
   unit prices. A full return refunds the sum of all units. Partial returns and
   exchanges identify a line and quantity; ambiguous selections fail without a
   ticket. Exchange amounts and stock checks cover the selected quantity. Keep
   the existing transactional operation keys and fee policy. These remain pickup
   requests, not proof of money already paid or completed physical fulfilment.
3. Accept and validate a new delivery address for address updates. Persist it in
   the existing order-update journal and project the latest address when reading
   an owned order, including immutable CRM seed orders. Never acknowledge an
   absent/blank address. Keep private addresses out of model/log output, while
   binding the actual value to semantic authorization and the operation digest.
4. Put business opening hours, holidays and dated exceptions in reviewed calendar
   data with source references. Normalize callback time before semantic review,
   preserve the requested time, and bind the effective stored time to the grant.
   The receipt exposes `moved_from` under the BTC contract. Customer constraints
   that prohibit a shift still deny authorization. Include special opening hours,
   Sunday rules, holidays and timezone-aware inputs; never shift silently after
   an approved effective time. No phrase classifier determines flexibility.
5. Search public catalog attributes as well as product identifiers. Provide typed
   attribute filters, preserving bool/numeric distinctions, existing category,
   price/room filters, variant selection and discontinued behavior. Propagate
   the supported arguments through model tools and MCP.
6. Carry product evidence verified from catalog/order status into signed policy
   context. Satisfy only the `product` requirement actually substantiated by that
   evidence; dates retain their independent provenance. Unknown, mismatched or
   caller-invented products cannot clear applicability conditions. Keep missing
   context and policy dependencies visible.
7. Return consistent validity metadata for every applied promotion in single and
   basket quotes, including unit and order promotions. Derive dates from the
   loaded promotions, preserve price calculations, and support downstream memory
   evidence without inventing an expiry.
8. Detect overlapping catalog/specification facts using generic table parsing
   and reviewed source/field mappings, never per-SKU corrections. Keep raw BTC
   JSON unchanged. Expose conflicting values, resolution/provenance and source
   hashes in catalog output. Technical specification fields may use their
   approved technical source; price, inventory and warranty retain their stated
   catalog priority. Ambiguous/unparseable technical evidence must not silently
   replace a catalog value. The source record `stages=0` is an audit trigger,
   not a special case in runtime code.
9. Keep source loading transactional and non-destructive. Reject a supposedly
   synchronized import if stale extra source rows would remain after upsert;
   roll back rather than automatically deleting them. Keep the existing
   verification/report path and policy release workflow. No live import,
   migration, index encoding, activation or deployment is authorized here.

## Implementation decisions

- Extend the repository's signed-context pattern with a small identity envelope
  for scoped reads. Use the existing MCP secret and schema normalization.
- Add optional `line_index`, `qty` and `address` to order updates. A return with
  no selection means the whole order. A multi-line exchange needs an explicit
  line. Journal entries record the selected units and amounts. Owned order reads
  consume the journal so address changes are real persisted state.
- Use reviewed calendar JSON plus a shared pure normalizer. Callback
  `requested_callback_at` is trusted normalization metadata, not a new model
  permission flag. Approval reviews the effective time and any original request.
- Read existing public policy rows for catalog technical evidence; no new source
  table or overwrite of BTC records is needed. Reviewed document/header mappings
  define source authority. Independent tests supply unrelated documents/SKUs.
- Policy context includes a product and its catalog/order-status provenance;
  the controller verifies the selection against source observations before signing.

## Constraints and verification

Current checkout, no worktrees/subagents/commits, no code comments/docstrings,
new dependencies, model calls, benchmarks or external writes. Existing source
and tests are authoritative; inspect before relying on earlier descriptions.
Use focused offline RED/GREEN tests with blocked sockets and synthetic data,
then relevant regression checks. Do not restore obsolete phrase controllers to
match old conversations. Self-review each requirement and record evidence in
the plan. Live semantic accuracy, load/latency and physical fulfilment remain
unmeasured; these are not public/hidden-score claims.
