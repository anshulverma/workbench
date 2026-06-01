# ADR 0002: LLM Extraction Produces Independent Items, Not Bundles

`extract()` returns `list[ExtractedItem]` where each item is a single actionable thing with its own category (action_item, meeting, plan_seed, informational). One raw input (email, meeting notes) may produce N independent items that each flow through filter, enrichment, and triage independently.

We chose this over the bundled model (one ExtractedItem with `action_items: list[str]`, `plan_seeds: list[str]`, etc.) because bundling forces a single relevance score on items with different priorities, makes triage cards unwieldy ("accept all or adjust each"), and couples item lifecycle to the source document rather than the individual action.

**Consequence:** Each extracted item gets its own relevance score, triage card, and `items` table row. The `items` table has a `category` column to distinguish types. Triage cards are simpler (one decision per card).
