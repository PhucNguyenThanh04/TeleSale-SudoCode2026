GRANT USAGE ON SCHEMA btc_source TO mcp_catalog, mcp_order, mcp_memory;
GRANT USAGE ON SCHEMA runtime TO mcp_catalog, mcp_order, mcp_memory;
GRANT SELECT ON btc_source.products, btc_source.variants, btc_source.promotions,
    btc_source.inventory_events, btc_source.customers, btc_source.crm_orders,
    btc_source.crm_sessions TO mcp_catalog, mcp_order;
GRANT SELECT ON btc_source.policy_chunks TO mcp_catalog;
GRANT SELECT ON btc_source.variants TO mcp_memory;
GRANT SELECT ON runtime.tool_operations TO mcp_memory;
GRANT SELECT ON runtime.tool_orders, runtime.promo_uses TO mcp_catalog;
GRANT SELECT, INSERT, UPDATE ON runtime.tool_orders, runtime.tool_updates,
    runtime.tool_callbacks, runtime.tool_handoffs, runtime.promo_uses,
    runtime.tool_operations TO mcp_order;
GRANT USAGE, SELECT ON SEQUENCE runtime.tool_order_seq,
    runtime.tool_updates_id_seq, runtime.tool_callbacks_callback_id_seq,
    runtime.tool_handoffs_ticket_id_seq TO mcp_order;
GRANT SELECT, INSERT, UPDATE, DELETE ON runtime.turns,
    runtime.order_links, runtime.write_operations, runtime.erasure_requests,
    runtime.langmem_distillation_jobs TO mcp_memory;
GRANT USAGE, SELECT ON SEQUENCE runtime.langmem_distillation_jobs_job_id_seq TO mcp_memory;
DO $$ BEGIN
    IF to_regclass('system_boot.current') IS NOT NULL THEN
        GRANT USAGE ON SCHEMA system_boot TO mcp_catalog, mcp_order, mcp_memory, mcp_knowledge;
        GRANT SELECT ON system_boot.current TO mcp_catalog, mcp_order, mcp_memory, mcp_knowledge;
    END IF;
    IF to_regclass('runtime.store') IS NOT NULL THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON runtime.store,
            runtime.store_migrations TO mcp_memory;
    END IF;
    IF to_regnamespace('knowledge') IS NOT NULL THEN
        GRANT USAGE ON SCHEMA knowledge TO mcp_catalog, mcp_memory;
        IF to_regclass('knowledge.policy_sources') IS NOT NULL THEN
            GRANT USAGE ON SCHEMA knowledge TO mcp_knowledge;
            GRANT SELECT ON knowledge.policy_sources,knowledge.policy_revocations,
                knowledge.active,knowledge.releases TO mcp_knowledge;
            GRANT SELECT,INSERT,UPDATE ON knowledge.policy_sources,knowledge.policy_revocations TO mcp_memory;
        END IF;
        GRANT SELECT,INSERT,UPDATE ON knowledge.events,knowledge.jobs,knowledge.erasures,
            knowledge.gaps,knowledge.revisions,knowledge.regression_cases,knowledge.decisions,
            knowledge.releases,knowledge.active,knowledge.backend_outbox TO mcp_memory;
    END IF;
END $$;
