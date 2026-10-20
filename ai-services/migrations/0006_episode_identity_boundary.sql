-- Older claim_pending versions assigned the resolved customer to every earlier
-- anonymous turn in the session. Recover the boundary from the first claim and
-- the first commit after it, then restore earlier turns to anonymous ownership.
WITH first_claim AS (
    SELECT LEFT(operation_key, 36)::uuid AS session_id,
           MIN(created_at) AS claimed_at
    FROM ai_memory.write_operations
    WHERE operation_key ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:.*:claim_pending$'
      AND jsonb_typeof(result->'memory_writes') = 'array'
    GROUP BY LEFT(operation_key, 36)::uuid
), first_verified_turn AS (
    SELECT claim.session_id,
           MIN((operation.result->>'turn_no')::integer) AS turn_no
    FROM first_claim AS claim
    JOIN ai_memory.write_operations AS operation
      ON LEFT(operation.operation_key, 36) = claim.session_id::text
     AND operation.operation_key LIKE '%:commit_turn'
     AND operation.created_at >= claim.claimed_at
     AND operation.result->>'turn_no' ~ '^[0-9]+$'
    GROUP BY claim.session_id
)
UPDATE ai_memory.turns AS turn_row
SET customer_id = NULL
FROM first_claim AS claim
LEFT JOIN first_verified_turn AS verified ON verified.session_id = claim.session_id
WHERE turn_row.session_id = claim.session_id
  AND (verified.turn_no IS NULL OR turn_row.turn_no < verified.turn_no);

-- Rebuild legacy episodes that combined attributed and unattributed turns.
-- Only turns already attributed to the episode owner may enter its summary.
-- Earlier claim_pending versions could also promote anonymous facts. Retract
-- any such active fact before the customer profile is read by the new runtime.
-- The claim result records each inserted fact_id even when the original
-- anonymous commit had no operation key to connect its message to a turn.
UPDATE ai_memory.facts AS fact
SET status = 'retracted'
WHERE fact.status = 'active'
  AND EXISTS (
      SELECT 1 FROM ai_memory.write_operations AS operation
      CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN jsonb_typeof(operation.result->'memory_writes') = 'array'
               THEN operation.result->'memory_writes' ELSE '[]'::jsonb END
      ) AS written(item)
      WHERE operation.operation_key ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:.*:claim_pending$'
        AND jsonb_typeof(operation.result->'memory_writes') = 'array'
        AND LEFT(operation.operation_key, 36) = fact.source_session_id::text
        AND written.item->>'fact_id' = fact.fact_id::text
  );

UPDATE ai_memory.facts AS fact
SET status = 'retracted'
WHERE fact.status = 'active'
  AND fact.source_turn_id IS NOT NULL
  AND EXISTS (
      SELECT 1 FROM ai_memory.write_operations AS operation
      JOIN ai_memory.turns AS turn_row
        ON turn_row.session_id = fact.source_session_id
       AND turn_row.turn_no = (operation.result->>'turn_no')::integer
      WHERE operation.operation_key =
            fact.source_session_id::text || ':' || fact.source_turn_id::text || ':commit_turn'
        AND turn_row.customer_id IS NULL
  );

WITH mixed AS (
    SELECT episode.session_id, episode.customer_id
    FROM ai_memory.episodes AS episode
    WHERE EXISTS (
        SELECT 1 FROM ai_memory.turns AS turn_row
        WHERE turn_row.session_id = episode.session_id
          AND turn_row.customer_id IS DISTINCT FROM episode.customer_id
    )
), rebuilt AS (
    SELECT mixed.session_id,
           LEFT(STRING_AGG(
               'Khách: ' || owned.customer_text || ' Trợ lý: ' || owned.agent_text,
               ' | ' ORDER BY owned.turn_no
           ), 800) AS summary
    FROM mixed
    JOIN LATERAL (
        SELECT turn_no, customer_text, agent_text
        FROM ai_memory.turns
        WHERE session_id = mixed.session_id AND customer_id = mixed.customer_id
        ORDER BY turn_no DESC
        LIMIT 3
    ) AS owned ON TRUE
    GROUP BY mixed.session_id
)
UPDATE ai_memory.episodes AS episode
SET summary = rebuilt.summary, updated_at = now()
FROM rebuilt
WHERE episode.session_id = rebuilt.session_id;

-- An episode with no attributed turns has no verified source to summarize.
DELETE FROM ai_memory.episodes AS episode
WHERE EXISTS (
    SELECT 1 FROM ai_memory.turns AS turn_row
    WHERE turn_row.session_id = episode.session_id
      AND turn_row.customer_id IS DISTINCT FROM episode.customer_id
)
AND NOT EXISTS (
    SELECT 1 FROM ai_memory.turns AS turn_row
    WHERE turn_row.session_id = episode.session_id
      AND turn_row.customer_id = episode.customer_id
);
