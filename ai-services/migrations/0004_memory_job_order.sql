-- Different customers may extract concurrently; one customer's revisions stay ordered across channels.
CREATE INDEX IF NOT EXISTS langmem_customer_pending_job_idx
    ON runtime.langmem_distillation_jobs(customer_id, job_id)
    WHERE status IN ('pending', 'leased');
