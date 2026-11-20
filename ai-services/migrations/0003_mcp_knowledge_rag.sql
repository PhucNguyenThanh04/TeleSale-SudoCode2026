CREATE TABLE IF NOT EXISTS knowledge.policy_sources (
    id text PRIMARY KEY,
    data jsonb NOT NULL CHECK (jsonb_typeof(data)='object')
);
CREATE TABLE IF NOT EXISTS knowledge.policy_revocations (
    id text PRIMARY KEY,
    data jsonb NOT NULL CHECK (jsonb_typeof(data)='object')
);
CREATE INDEX IF NOT EXISTS policy_sources_release ON knowledge.policy_sources ((data->>'release_id'));
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='mcp_knowledge') THEN
   CREATE ROLE mcp_knowledge NOLOGIN;
 END IF;
 GRANT USAGE ON SCHEMA knowledge TO mcp_knowledge;
 GRANT SELECT ON knowledge.policy_sources, knowledge.policy_revocations,
   knowledge.releases, knowledge.active TO mcp_knowledge;
 GRANT SELECT ON knowledge.policy_sources,knowledge.policy_revocations TO knowledge_reviewer,knowledge_worker;
 GRANT INSERT,UPDATE ON knowledge.policy_sources,knowledge.policy_revocations TO knowledge_reviewer;
END $$;
