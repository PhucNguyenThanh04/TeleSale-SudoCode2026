ALTER TABLE runtime.tool_orders ADD COLUMN IF NOT EXISTS lines jsonb NOT NULL DEFAULT '[]';
UPDATE runtime.tool_orders
SET lines = jsonb_build_array(jsonb_build_object('sku', sku, 'qty', qty, 'price_vnd', price_vnd))
WHERE lines = '[]'::jsonb;
