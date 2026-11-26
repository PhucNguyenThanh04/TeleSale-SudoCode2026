# Trace recovery and completion

The user delegated specification, planning and execution of fixes from the latest trace diagnosis. Work inline in the existing checkout, preserve its uncommitted fixes, and leave a reviewable diff. No agents, worktrees, commits, paid inference, deployment or changes to saved traces and BTC labels.

## Evidence

The saved btc74 run contains 39 turns: nine fallbacks, two successful creates, no update, and six unknown-identity turns. Offline reference scoring gives TSR 28.6%, CCR 33.3%, RQR 25%, TTFT p50 2699 ms. The current working tree already patches gift admission, fallback target selection, update receipt checks and bounded completion. Verify those paths rather than reimplementing them.

## Requirements

1. Reading a gift's catalog, price or stock must not make it the advised purchase. Failed order attempts cannot establish that role. Explicit independent customer selection and successful receipts remain valid sources. Fallback must not select a product from a rejected draft.
2. A current explicit purchase or exchange request must get one opportunity to use the existing tools even if the semantic reviewer accepts an unfulfilled draft. Cover natural purchase/exchange phrasing, questions, negation and conditions. Continuation never authorizes a write; retain the existing authorizer, receipts, idempotency and budgets.
3. Propagate explicitly supplied backend-verified identity through evaluation preparation, turns and voice receipts. Never substitute a phone for a missing Facebook/Zalo account ID or derive authenticated identity from conversation text. Incomplete verified-identity pairs are input errors. Missing CRM mappings still require real trusted identity input; do not fabricate mappings or change frozen data.
4. Avoid repeated semantic model requests for the same answer and unchanged review context within one verification pass. Changed evidence must be reviewed again; unavailable reviews must be retryable. Keep whole-answer publication and independent write authorization. This removes duplicate work, not a claim of a new latency percentile.
5. Each new behavior needs a failing regression, focused passing checks and connected integration coverage. Replay relevant frozen rows read-only. Verify existing gift, preview/update and final-publication patches as part of the final change. Report limits of fake-model tests and live metrics explicitly.

## Decisions

Keep the existing Python/LangGraph/MCP architecture and model. Do not replace business execution with regex-triggered writes or stream unchecked drafts. Broaden only the bounded recovery signal; the existing authorization boundary decides what may execute. Use the existing explicit verified-customer transport for simulations that actually supply a trusted actor. Missing external identity data cannot be repaired by treating descriptive phone metadata as authentication.

Completion means the code contracts above are implemented and verified offline. Live TSR and latency improvements remain unmeasured and are not acceptance claims for this code repair. The earlier plan's live metric targets are not silently claimed achieved.
