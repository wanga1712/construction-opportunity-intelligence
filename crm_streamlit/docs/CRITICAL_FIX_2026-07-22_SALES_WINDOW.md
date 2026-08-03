# Critical fix 2026-07-22: sales window and CRM ordering

Context: user found expired/useless procurement `0173200000225000105` in the active CRM/daemon flow.

## Business rule

For material sales, an object is useful only if there are at least 90 days until delivery/execution end.

On 2026-07-22 the practical cutoff is about 2026-10-20.

Objects with `COALESCE(delivery_end_date, end_date)` earlier than the cutoff are treated as lost and must not be shown in active CRM lists or added to the document-processing queue.

## Done

- CRM now filters out objects outside the 90-day sales window.
- CRM priority order now follows:
  1. new/non-awarded objects with document matches;
  2. awarded objects with document matches and valid sales window;
  3. new/non-awarded objects with documents queued;
  4. awarded objects with documents queued and valid sales window.
- Background AI precompute skips lost/out-of-window objects.
- Local AI classifier treats objects with less than 90 days left as low-chance/lost for material sales.
- Document daemon queue manager now uses the same 90-day sales-window rule before claiming/adding work.
- Added daemon-side purge for pending queue rows that are already outside the sales window.
- Procurement `0173200000225000105` was marked as `error` in `document_processing_queue` with `sales_window_expired`.
- Wanga DB queue cleanup moved stale pending rows to `error`; pending count went from about 1817 to 396.
- Updated Linux worker `10.0.0.13` and restarted `tender-docs-daemon.service`.
- Removed ordinary object-card `Гидро-потенциал` quick action. Waterproofing remains a separate CRM section.

## Files touched

- `src/services/objects_service.py`
- `src/services/object_ai_classifier.py`
- `src/ui/object_detail.py`
- `scripts/ai_precompute_objects.py`
- `C:\Users\Lenovo\Projects\tender_documents_research\document_processor\queue_manager.py`

