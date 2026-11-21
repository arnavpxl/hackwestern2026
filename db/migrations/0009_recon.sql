-- Reconciliation result (deterministic diagnosis + verified narrative) per invoice.
ALTER TABLE ap_invoices ADD COLUMN recon jsonb;
ALTER TABLE ap_invoices ADD COLUMN reconciled_at timestamptz;
