# LangMem Primary Long-Term Memory

The customer chose to retire the old fact and episode runtime. LangMem now
proposes typed profile facts and call episodes after each identified turn. The
memory worker checks proposals against the committed turn and successful tool
observations. Accepted knowledge is stored in the verified customer's namespace
of `AsyncPostgresStore` in the `langmem_store` PostgreSQL schema.

`ai_memory` remains operational storage for masked session turns, order links,
idempotent operation results, durable distillation jobs, and verified erasure
barriers. It is not read for long-term facts or episodes when
`LANGMEM_MODE=enabled`. The service now accepts only `enabled`; `off` and
`shadow` are retired from runtime and new benchmark runs. Historical SQL
tables and records are retained so existing data is not deleted by deployment.

The agent does not expose the old fact proposal tool in the primary mode. A
committed turn queues a job and returns without waiting for model extraction.
The worker processes jobs in session order. It persists admitted proposals in
the durable job before touching the store, so a retry replays the same accepted
data. Accepted facts replace a stable customer/scope/key in the LangGraph
store; revisions and tombstones prevent an older retry from reviving a deleted
fact. Store records from unfinished jobs are hidden on reads. Session episodes
are bounded and stored separately. A missing store fails customer memory reads
closed.

The setup sequence is: apply migrations through `0013`, run
`scripts.setup_langmem_store` once as an admin, grant the `mcp_memory` role,
then run `scripts.backfill_langmem_store` once for existing sourced records.
Start the memory MCP and LangMem worker together; the local launcher starts
both. Erasure holds the customer
barrier while deleting both operational rows and all LangGraph namespaces.

The BTC harness waits for worker completion after each call and obtains the
accepted writes of each source turn from the durable job record. It does not
report model proposals as writes. Run the official evaluator on an isolated
database before using the score to guide further changes. The previous public
sample result did not show a measured gain, so deployment alone is not evidence
of a higher BTC score.
