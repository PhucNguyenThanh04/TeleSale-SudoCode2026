# Fresh demo/eval startup

User requirement: retain only imported BTC data; automatically create managed
backend/AI tables and reset runtime + all knowledge state for every new demo or
eval session. No external/manual migration commands. Restore required demo
accounts/permissions and the BTC-only policy release, not old approved knowledge.

Implementation boundary: a managed system startup command owns a boot ID and
initializes before starting dependent servers/workers. Individual workers must
not reset another server's data. A knowledge-loop experiment shares one boot ID
across K0, review and K1; resume must not begin a new boot.

1. Add startup schema initialization using the existing checked-in DDL internally,
   explicit DB identity, administrative connection and an advisory lock. BTC import
   remains separate. Ensure LangGraph store setup and application role grants.
2. Retain/revalidate only a BTC-only base index cache when compatible; delete
   generated knowledge releases and restore or build the base release. Never
   restore approved supplements. Restore configured account/permission defaults.
3. Add the managed demo/eval entrypoint with ordered service startup and a shared
   boot marker; no separate operator migration step. Reset once before servers
   accept requests, not per eval configuration. Preserve resume within a boot.
4. Focused offline tests for repeated/concurrent boot initialization, complete
   managed-data reset, source preservation, DDL ordering, process startup order,
   configuration failures and knowledge experiment resume. No reset of the user's
   live database, model calls or real index rebuild during implementation.

Verification:
- Focused AI/bootstrap/launcher/policy/triplet checks: 42 passed.
- Existing chat/knowledge API checks: 9 passed with a synthetic internal token;
  without this test configuration their setup fails because the token is absent.
- Focused backend managed-boot/auth/knowledge checks: 23 passed.
- Temporary PostgreSQL integration passed during implementation, including
  concurrent initialization and BTC fingerprint preservation. The final rerun
  could not connect to localhost:5432 (PostgreSQL stopped); it did not modify DBs.
- CLI help, shell syntax and diff whitespace checks passed. No managed launch
  against the user's database, live LLM eval or Cloudflare build was performed.
