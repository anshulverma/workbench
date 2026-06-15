// dev-mock-server.mjs — standalone mock API for the WorkBench UI dev environment.
//
// Pure Node.js built-in `http` (no npm deps). Vite proxies /api → :8421.
// Data values are lifted from /tmp/design_v4/workbench/project/app/data.js;
// response *shapes* follow the UI hooks (src/hooks/*.ts) and src/test/server.ts.
//
// Run:  node dev-mock-server.mjs
// Unknown endpoints return an empty-but-valid 200 ([] or {}); mutations return
// 200 {ok:true} (or an echo of the posted body).

import http from 'node:http'
import { URL } from 'node:url'

const HOST = '0.0.0.0'
const PORT = 8421

// ---- relative-time helpers (mirror data.js) -------------------------------
const NOW = Date.now()
const m = (mins) => new Date(NOW - mins * 60000).toISOString()
const h = (hrs) => new Date(NOW - hrs * 3600000).toISOString()
const d = (days) => new Date(NOW - days * 86400000).toISOString()

// ===========================================================================
// Data (values from data.js; structure adjusted to match UI hook types)
// ===========================================================================

// useStats.ts StatsOverview: needs items.by_status, queue{in_flight,dead_letters},
// metrics{signal_velocity, throughput, efficiency_peak, auto_resolved_pct,
// avg_triage_seconds, growth_velocity, ingestion_success_rate}.
const overview = {
  pending_triage: 14,
  in_flight: 6,
  dead_letters: 2,
  active_items: 47,
  sources_enabled: 4,
  sources_total: 5,
  items: {
    total: 1284,
    by_status: { active: 47, pending_triage: 14, archived: 980, dropped: 243 },
    by_priority: { P0: 3, P1: 17, P2: 64, P3: 142 },
    by_category: { action_item: 96, meeting: 38, plan_seed: 12, informational: 80 },
    by_source: { github: 612, email: 388, calendar: 144, chat: 140 },
  },
  queue: { in_flight: 6, dead_letters: 2 },
  metrics: {
    signal_velocity: 23,
    throughput: 0.72,
    efficiency_peak: 0.86,
    auto_resolved_pct: 0.41,
    avg_triage_seconds: 38,
    growth_velocity: 23,
    ingestion_success_rate: 0.97,
  },
}

// useStats.ts QueueStats: by_status, by_source, queued, processing, dead_letter.
const queueStats = {
  queued: 6,
  processing: 2,
  dead_letter: 2,
  by_status: { queued: 6, processing: 2, completed: 1842, failed: 11, dead_letter: 2 },
  by_source: { github: 4, email: 2, calendar: 1, chat: 1 },
}

// useStats.ts SourceRollup[].
const sources = [
  { id: 'src_github_main', adapter_type: 'github', enabled: true, schedule: '*/15 * * * *', last_run: m(4), items_stored: 612, raw_enqueued: 41, in_flight: 3, health_status: 'healthy', config: {}, relevance: null },
  { id: 'src_email_work', adapter_type: 'email', enabled: true, schedule: '0 * * * *', last_run: m(26), items_stored: 388, raw_enqueued: 18, in_flight: 1, health_status: 'healthy', config: {}, relevance: null },
  { id: 'src_calendar', adapter_type: 'calendar', enabled: true, schedule: '0 */6 * * *', last_run: h(3), items_stored: 144, raw_enqueued: 6, in_flight: 0, health_status: 'healthy', config: {}, relevance: null },
  { id: 'src_gchat', adapter_type: 'chat', enabled: true, schedule: '*/15 * * * *', last_run: m(9), items_stored: 140, raw_enqueued: 9, in_flight: 2, health_status: 'erroring', config: {}, relevance: null },
  { id: 'src_phab', adapter_type: 'phabricator', enabled: false, schedule: '*/15 * * * *', last_run: d(2), items_stored: 73, raw_enqueued: 0, in_flight: 0, health_status: 'disabled', config: {}, relevance: null },
]

// useStats.ts IngestionPoint[] {date,count}.
const ingestionSeries = [42, 51, 38, 60, 73, 49, 55, 80, 66, 71, 58, 90, 77, 84].map(
  (count, i) => ({ date: d(13 - i), count }),
)
// useStats.ts MetricPoint[] {bucket,count}. signal_velocity (hourly) / throughput.
const signalVelocity = [3, 5, 2, 6, 4, 7, 9, 6, 8, 5, 4, 7, 10, 8, 6, 9, 12, 7, 5, 8, 6, 9, 11, 7].map(
  (count, i) => ({ bucket: h(23 - i), count }),
)
const throughputSeries = [4, 6, 3, 7, 5, 8, 6, 9].map((count, i) => ({ bucket: h(7 - i), count }))

// useStats.ts JobsResponse {jobs,total,limit,offset}. Job {id,trigger,status,items_extracted,created_at}.
const TRIGGERS = ['scheduled', 'manual', 'scheduled', 'scheduled', 'webhook']
const STATUSES = ['completed', 'completed', 'running', 'completed', 'failed', 'completed', 'queued', 'completed']
const allJobs = Array.from({ length: 34 }, (_, i) => ({
  id: 'job_' + (8842 - i),
  trigger: TRIGGERS[i % TRIGGERS.length],
  status: STATUSES[i % STATUSES.length],
  items_extracted: [12, 0, 5, 8, 0, 3, 0, 21, 14, 6][i % 10],
  created_at: m(8 + i * 17),
  source: ['github', 'email', 'calendar', 'chat', 'github'][i % 5],
}))

// useStats.ts ActivityItem[] {id,status,source_type,summary,created_at}.
const ACT_SUMMARIES = [
  'PR opened: fix the thing', 'email thread: re: Q3 plan', 'meeting created: arch review',
  'chat message: on-call handoff', 'PR merged: D12840 landed', 'issue updated: P1 escalation',
  'calendar invite accepted', 'PR comment: requested changes', 'email flagged: from manager',
]
const activity = Array.from({ length: 24 }, (_, i) => ({
  id: 'evt_' + (5000 - i),
  source_type: ['github', 'email', 'calendar', 'chat'][i % 4],
  status: ['active', 'pending_triage', 'archived', 'active'][i % 4],
  summary: ACT_SUMMARIES[i % ACT_SUMMARIES.length],
  created_at: m(2 + i * 9),
}))

// topology — data.js shape (nodes/edges). No strict UI type; served as-is.
const topology = {
  nodes: [
    { id: 'app', label: 'app', kind: 'app', status: 'healthy' },
    { id: 'postgres', label: 'postgres', kind: 'storage', status: 'healthy' },
    { id: 'queue', label: 'queue worker', kind: 'worker', status: 'degraded' },
    { id: 'scheduler', label: 'scheduler', kind: 'worker', status: 'healthy' },
    { id: 'memory', label: 'zep memory', kind: 'service', status: 'healthy' },
    { id: 'messenger', label: 'gchat', kind: 'service', status: 'healthy' },
    { id: 'plugboard', label: 'plugboard', kind: 'service', status: 'healthy' },
  ],
  edges: [
    { from: 'app', to: 'postgres' }, { from: 'app', to: 'queue' },
    { from: 'app', to: 'scheduler' }, { from: 'app', to: 'memory' },
    { from: 'app', to: 'messenger' }, { from: 'app', to: 'plugboard' },
  ],
}

// useStats.ts Connection[] {name,healthy}.
const connections = [
  { name: 'google_oauth', healthy: true },
  { name: 'plugboard', healthy: true },
  { name: 'zep_memory', healthy: false },
]

// useStats.ts HealthResponse {status,version,components{storage,connections},queue}.
const health = {
  status: 'degraded',
  version: '0.4.2',
  components: {
    storage: { status: 'healthy' },
    connections: {
      google_oauth: { status: 'healthy' },
      plugboard: { status: 'healthy' },
      zep_memory: { status: 'degraded' },
    },
  },
  queue: { ingestion_depth: 6, triage_pending: 14, dead_letters: 2 },
}

// useStats.ts DeadLetterEntry[] — richer than data.js; fill required fields.
const deadLetters = [
  { id: 'dl_3391', raw_content: '{"space":"AAAA1b2C3d4"}', source_type: 'chat', source_id: 'src_gchat', urgency_score: 40, job_id: 'job_8830', status: 'dead_letter', attempt: 3, max_attempts: 3, error: 'GoogleChat 503: space unavailable', created_at: h(4), updated_at: h(4) },
  { id: 'dl_3388', raw_content: '{"pr":"D12871"}', source_type: 'github', source_id: 'src_github_main', urgency_score: 55, job_id: 'job_8825', status: 'dead_letter', attempt: 3, max_attempts: 3, error: 'rate-limited: secondary limit, retry exhausted', created_at: h(9), updated_at: h(9) },
]

// useTriage.ts TriageCard[].
const triageCards = [
  {
    id: 'tc_94f12', item_id: 'D12871', relevance_score: 94, confidence_score: 88, status: 'pending_triage', created_at: m(6),
    card_content: { summary: 'CI is red on D12871 and you are the blocking reviewer. The failure is in the queue-worker integration suite.', priority: 'P0', source_type: 'github' },
    options: [
      { label: 'Add todo', action: 'add_todo', suggestion_reason: 'You typically self-assign blocking reviews within the hour; the diff author is waiting on you.' },
      { label: 'Defer 4h', action: 'defer', suggestion_reason: 'CI may be a flaky infra failure — a re-run could clear it before you spend reviewer time.' },
      { label: 'Skip', action: 'skip' },
    ],
  },
  {
    id: 'tc_77a03', item_id: 'eml_5521', relevance_score: 91, confidence_score: 82, status: 'pending_triage', created_at: m(22),
    card_content: { summary: 'VP Eng flagged the Q3 reliability plan and asked for sign-off before EOD. Two open questions remain on the rollback budget.', priority: 'P0', source_type: 'email' },
    options: [
      { label: 'Add todo', action: 'add_todo', suggestion_reason: 'Sender is in your management chain and the message contains an explicit deadline.' },
      { label: 'Reply', action: 'reply' },
      { label: 'Skip', action: 'skip' },
    ],
  },
  {
    id: 'tc_5b210', item_id: 'D12863', relevance_score: 78, status: 'pending_triage', created_at: m(48),
    card_content: { summary: 'D12863 has 3 approvals pending your rebase onto main. The branch is 11 commits behind.', priority: 'P1', source_type: 'github' },
    options: [
      { label: 'Add todo', action: 'add_todo' },
      { label: 'Defer 4h', action: 'defer' },
      { label: 'Mute source', action: 'mute' },
    ],
  },
  {
    id: 'tc_3c8e1', item_id: 'cal_8841', relevance_score: 64, status: 'pending_triage', created_at: h(1),
    card_content: { summary: 'Architecture review moved to 14:00. The agenda doc has not been posted yet — you are the listed owner.', priority: 'P2', source_type: 'calendar' },
    options: [
      { label: 'Add todo', action: 'add_todo' },
      { label: 'Skip', action: 'skip' },
    ],
  },
  {
    id: 'tc_1f9d4', item_id: 'chat_2207', relevance_score: 52, status: 'pending_triage', created_at: h(2),
    card_content: { summary: 'On-call thread requests a post-mortem for the queue-depth alarm that cleared at 02:14. No action assigned yet.', priority: 'P2', source_type: 'chat' },
    options: [
      { label: 'Add todo', action: 'add_todo' },
      { label: 'Defer', action: 'defer' },
      { label: 'Skip', action: 'skip' },
    ],
  },
  {
    id: 'tc_0a772', item_id: 'itm_8841', relevance_score: 33, status: 'pending_triage', created_at: h(5),
    card_content: { summary: 'Weekly dependency digest: 4 transitive bumps, no advisories. Auto-included at P3 after 7-day expiry window.', priority: 'P3', source_type: 'github' },
    options: [
      { label: 'Archive', action: 'archive' },
      { label: 'Skip', action: 'skip' },
    ],
  },
]

// useTriage.ts single-card detail (GET /api/triage/cards/:id). Rich diff card.
const triageDetail = {
  id: 'tc_94f12', status: 'pending_triage', relevance_score: 94, item_id: 'D12871',
  card_content: {
    summary: 'D12871 — Harden queue worker against SKIP LOCKED contention',
    priority: 'P0', source_type: 'github',
    sections: {
      metadata: { author: 'alice', team: 'Ingestion Platform', status: 'Needs Review' },
      change: 'Author pushed a new diff version after CI failed. The retry-backoff change moved from the worker into the dead-letter path.',
      summary: 'D12871 — Harden queue worker against SKIP LOCKED contention',
      why_care: 'You are the blocking reviewer and CI is red. The change touches the dequeue ordering path that caused last week\'s queue-depth alarm, so a regression here directly affects ingestion latency.',
      diff_url: 'https://phabricator.internal/D12871',
      risk: {
        factors: [
          'Modifies SELECT ... FOR UPDATE SKIP LOCKED ordering — concurrency-sensitive.',
          'Changes max_attempts default from 3 to 5, increasing dead-letter latency.',
        ],
        watch_outs: [
          'No test covers the exponential backoff ceiling.',
          'Migration not included — relies on existing ingestion_queue columns.',
        ],
      },
      hunks: [
        { file: 'src/workbench/queue/worker.py', header: '@@ -118,7 +118,9 @@ async def _dequeue', rank: 1, annotation: 'core dequeue ordering', code: ' async def _dequeue(self, conn):\n-    rows = await conn.fetch(SELECT_READY)\n+    rows = await conn.fetch(SELECT_READY_SKIP_LOCKED)\n+    if not rows:\n+        return []\n     return [RawItem.from_row(r) for r in rows]' },
        { file: 'src/workbench/queue/config.py', header: '@@ -22,1 +22,1 @@ class QueueConfig', rank: 2, annotation: 'retry ceiling', code: ' class QueueConfig(BaseModel):\n-    max_attempts: int = 3\n+    max_attempts: int = 5' },
        { file: 'tests/test_queue_worker.py', header: '@@ -40,0 +41,6 @@', rank: 3, annotation: 'new contention test', code: '+async def test_skip_locked_contention(pool):\n+    async with concurrent_workers(pool, n=4) as ws:\n+        results = await drain(ws)\n+    assert no_double_dequeue(results)' },
      ],
    },
  },
  options: [
    { label: 'Approve', action: 'approve' },
    { label: 'Request changes', action: 'request_changes' },
    { label: 'Defer 4h', action: 'defer' },
  ],
}

// useActions.ts ActionsResponse {categories:Record<string,Action[]>, total}.
const actionList = [
  { id: 'act_771', priority: 'P0', summary: 'Review D12871 — unblock CI before the release cut', action_category: 'review', action_source: 'github', created_at: m(12), parent_item: { id: 'D12871', summary: 'CI red on D12871' } },
  { id: 'act_770', priority: 'P0', summary: 'Sign off Q3 reliability plan rollback budget', action_category: 'decision', action_source: 'email', created_at: m(40), parent_item: { id: 'eml_5521', summary: 'VP Eng flagged Q3 plan' } },
  { id: 'act_765', priority: 'P1', summary: 'Rebase D12863 onto main and re-request review', action_category: 'update', action_source: 'github', created_at: h(2), parent_item: null },
  { id: 'act_762', priority: 'P1', summary: 'Post architecture review agenda doc', action_category: 'creation', action_source: 'calendar', created_at: h(6), parent_item: null },
  { id: 'act_758', priority: 'P1', summary: 'Delegate the dependency-bump triage to the on-call', action_category: 'delegation', action_source: 'github', created_at: d(1), parent_item: null },
  { id: 'act_754', priority: 'P2', summary: 'Schedule a post-mortem for the queue-depth alarm', action_category: 'scheduling', action_source: 'chat', created_at: d(1), parent_item: null },
  { id: 'act_749', priority: 'P2', summary: 'Reply to the platform sync thread about adapter SLAs', action_category: 'communication', action_source: 'chat', created_at: d(2), parent_item: null },
  { id: 'act_741', priority: 'P3', summary: 'Investigate the intermittent gchat thread-tracking drift', action_category: 'investigation', action_source: 'github', created_at: d(3), parent_item: null },
  { id: 'act_733', priority: 'P3', summary: 'Update the ingestion runbook with the new backoff defaults', action_category: 'update', action_source: 'github', created_at: d(5), parent_item: null },
]
function actionsResponse(category) {
  const list = category ? actionList.filter((a) => a.action_category === category) : actionList
  const categories = {}
  for (const a of list) {
    const k = a.action_category || 'uncategorized'
    ;(categories[k] ||= []).push(a)
  }
  return { categories, total: list.length }
}

// useFacts.ts FactsEnvelope {available, memory_type, facts:[{id,content,source,timestamp}]}.
const facts = [
  { id: 'f_201', source: 'github', content: 'Always prioritize PRs where reviewers are blocked on your rebase.', timestamp: d(2) },
  { id: 'f_198', source: 'github', content: 'Deprioritize dependency-bump PRs with no advisories.', timestamp: d(4) },
  { id: 'f_195', source: 'email', content: 'Messages from your management chain are never auto-dropped.', timestamp: d(5) },
  { id: 'f_190', source: 'email', content: 'Newsletter digests are informational unless they name a current project.', timestamp: d(8) },
  { id: 'f_187', source: 'calendar', content: 'Meetings you own that lack an agenda surface as action items.', timestamp: d(9) },
  { id: 'f_184', source: 'chat', content: 'On-call threads are P2 unless an alarm is currently firing.', timestamp: d(11) },
  { id: 'f_180', source: 'chat', content: 'Direct mentions from the platform team are always triaged.', timestamp: d(14) },
]
const factsEnvelope = { available: true, memory_type: 'zep', facts }

// useMessenger.ts MessengerInfo {configured,type,class,config{space_id,timeout_seconds},reachable,checked_at}.
const messenger = {
  configured: true,
  type: 'google_chat',
  class: 'GoogleChatMessenger',
  reachable: true,
  checked_at: m(3),
  config: { space_id: 'spaces/AAAA1b2C3d4', timeout_seconds: 30 },
}

// useSettings.ts DebugConfigResponse {config}. Redacted config from data.js.
const debugConfig = {
  config: {
    version: '0.4.2',
    pipeline: { extraction_model: 'claude-opus-4-8', worker_concurrency: 2, record_drop_decisions: false, relevance_threshold: 35, caps: { entity_facts: 5, preference_facts: 20, relationships: 10 } },
    scheduler: { timezone: 'America/Los_Angeles', morning_briefing: '0 8 * * *', retention_sweep: '0 3 * * *', poll_jitter_seconds: 30 },
    retention: { archived_items_days: 90, expired_cards_days: 30, enrichment_traces_days: 14, dead_letters_days: 30, interaction_log: 'never' },
    alerting: { messenger: 'google_chat', cooldown_seconds: 1800, conditions: ['connection_unhealthy', 'dead_letters', 'adapter_failures', 'queue_depth'], queue_depth_threshold: 100 },
  },
}

// useSources.ts AdapterType[] {adapter_type, requires_connection, json_schema}.
const adapterTypes = [
  { adapter_type: 'github', requires_connection: true, json_schema: { type: 'object', properties: { repo: { type: 'string' }, labels: { type: 'array' } } } },
  { adapter_type: 'email', requires_connection: true, json_schema: { type: 'object', properties: { query: { type: 'string' } } } },
  { adapter_type: 'calendar', requires_connection: true, json_schema: { type: 'object', properties: { calendar_id: { type: 'string' } } } },
  { adapter_type: 'chat', requires_connection: true, json_schema: { type: 'object', properties: { space_id: { type: 'string' } } } },
  { adapter_type: 'phabricator', requires_connection: true, json_schema: { type: 'object', properties: { query_key: { type: 'string' } } } },
]

// ---- Funnel (types/funnel.ts) ---------------------------------------------

// FilterRuleExtended[] — needs order_index (data.js lacks it; added by index).
const filterRules = [
  { id: 'fr_31', prompt: 'Drop dependency-bump PRs that carry no security advisory.', action: 'drop', sources: ['github'], confidence: 92, origin: 'learned', matched: 184, enabled: true },
  { id: 'fr_29', prompt: 'Always surface PRs where I am the blocking reviewer.', action: 'include', sources: ['github'], confidence: 96, origin: 'explicit', matched: 41, enabled: true },
  { id: 'fr_27', prompt: 'Drop automated CI status comments and bot chatter.', action: 'drop', sources: ['github'], confidence: 88, origin: 'learned', matched: 132, enabled: true },
  { id: 'fr_09', prompt: 'Label promotional and transactional email as noise.', action: 'label', label: 'noise', sources: ['email'], confidence: 80, origin: 'learned', matched: 71, enabled: true },
  { id: 'fr_24', prompt: 'Drop newsletter and digest emails unless they name a project I am actively working on.', action: 'drop', sources: ['email'], confidence: 85, origin: 'learned', matched: 96, enabled: true },
  { id: 'fr_22', prompt: 'Never drop messages from anyone in my management chain.', action: 'include', sources: ['email'], confidence: 98, origin: 'explicit', matched: 58, enabled: true },
  { id: 'fr_19', prompt: 'Drop calendar invites I have already accepted with no agenda change.', action: 'drop', sources: ['calendar'], confidence: 90, origin: 'learned', matched: 47, enabled: true },
  { id: 'fr_16', prompt: 'Drop on-call thread chatter unless an alarm is actively firing.', action: 'drop', sources: ['chat'], confidence: 78, origin: 'learned', matched: 64, enabled: false },
  { id: 'fr_12', prompt: 'Always include any item mentioning "rollback", "incident", or "SEV".', action: 'include', sources: ['github', 'email', 'calendar', 'chat'], confidence: 94, origin: 'explicit', matched: 23, enabled: true },
].map((r, i) => ({ ...r, order_index: i }))

// Enricher[] — types/funnel.ts requires avg_ms, enriched (data.js has both).
const enrichers = [
  { id: 'en_github', type: 'github', label: 'GitHub enricher', enabled: true, depth: 'deep', adds: ['author', 'author_team', 'review_status', 'ci', 'files_changed', 'labels'], records: ['person', 'repo'], budget: { max_calls: 1, max_time_ms: 30000 }, enriched: 612, avg_ms: 240 },
  { id: 'en_email', type: 'email', label: 'Gmail enricher', enabled: true, depth: 'shallow', adds: ['subject', 'sender', 'thread_id', 'attachments'], records: ['person'], budget: { max_calls: 0, max_time_ms: 5000 }, enriched: 388, avg_ms: 12 },
  { id: 'en_calendar', type: 'calendar', label: 'Calendar enricher', enabled: true, depth: 'shallow', adds: ['organizer', 'attendee_count', 'location', 'is_recurring', 'start', 'end'], records: ['person'], budget: { max_calls: 0, max_time_ms: 5000 }, enriched: 144, avg_ms: 9 },
  { id: 'en_chat', type: 'chat', label: 'Google Chat enricher', enabled: true, depth: 'shallow', adds: ['space_name', 'thread_name', 'participant_count', 'message_count'], records: ['person', 'space'], budget: { max_calls: 0, max_time_ms: 5000 }, enriched: 140, avg_ms: 14 },
]

// LoopBack[] — types/funnel.ts shape (label,trigger,condition,max_loops,enabled,looped,avg_loops).
const loopbacks = [
  { id: 'lb_repush', label: 'Re-push loop-back', enabled: true, trigger: 'Source item changed after a verdict (new diff revision, new reply, agenda edit).', condition: 'verdict !== pending && source_updated_at > triaged_at', max_loops: 3, looped: 38, avg_loops: 1.2 },
]

// FunnelOrderEntry[] {kind,id} — enrichers then filters then loopbacks.
const funnelOrder = [
  ...enrichers.map((e) => ({ kind: 'enricher', id: e.id })),
  ...filterRules.map((f) => ({ kind: 'filter', id: f.id })),
  ...loopbacks.map((l) => ({ kind: 'loopback', id: l.id })),
]

// FunnelItem[] {id,summary,source,created_at,stages,verdict}.
const funnelItems = [
  {
    id: 'itm_8841', summary: 'Bump lodash 4.17.20 → 4.17.21', source: 'github', created_at: h(3),
    verdict: { decision: 'dropped', confidence: 91, rationale: 'First decisive rule (fr_31) dropped it; no downstream include signal contested the decision, so the merged confidence equals the drop confidence.' },
    stages: [
      { filterId: 'en_github', outcome: 'context', reason: 'No linked diff; tagged as a pure dependency PR with no CI run.', context: 'no associated diff · dependency PR' },
      { filterId: 'fr_31', outcome: 'drop', confidence: 91, reason: 'Dependency bump; scanned PR body and changelog — no CVE or advisory referenced.' },
      { filterId: 'fr_29', outcome: 'pass', reason: 'You are not a requested reviewer.' },
      { filterId: 'fr_27', outcome: 'pass', reason: 'Not a CI status comment.' },
      { filterId: 'fr_12', outcome: 'pass', reason: 'No rollback / incident / SEV keyword.' },
    ],
  },
  {
    id: 'itm_8839', summary: 'CI is red on D12871', source: 'github', created_at: m(22),
    verdict: { decision: 'triaged', priority: 'P0', confidence: 96, rationale: 'Two include signals (blocking-reviewer 96%, CI-on-owned-diff 70%) were merged against one weak drop signal (CI-chatter 45%). The LLM aggregator kept the strongest include and escalated to P0 — a human is blocked.' },
    stages: [
      { filterId: 'en_github', outcome: 'context', reason: 'Resolved the linked diff and its live CI + review state.', context: 'diff D12871 · CI: failing · you = blocking reviewer' },
      { filterId: 'fr_31', outcome: 'pass', reason: 'Not a dependency bump.' },
      { filterId: 'fr_29', outcome: 'include', confidence: 96, reason: 'You are the blocking reviewer on the linked diff.', context: 'blocking-reviewer' },
      { filterId: 'fr_27', outcome: 'drop', confidence: 45, reason: 'Surface form resembles a CI status line — but it names a human action, so confidence stays low.', weak: true },
      { filterId: 'fr_12', outcome: 'include', confidence: 70, reason: 'References failing CI on a diff you own.' },
    ],
  },
  {
    id: 'itm_8836', summary: 'Re: Q3 reliability plan', source: 'email', created_at: m(40),
    verdict: { decision: 'triaged', priority: 'P0', confidence: 97, rationale: 'Two independent include signals — management-chain sender (98%) and a rollback-budget keyword (82%) — were joined by the LLM aggregator. Agreement between independent rules raised the merged confidence to 97% and the priority to P0.' },
    stages: [
      { filterId: 'fr_09', outcome: 'pass', reason: 'Not promotional or transactional.' },
      { filterId: 'fr_24', outcome: 'pass', reason: 'Names an active project (Q3 reliability).' },
      { filterId: 'fr_22', outcome: 'include', confidence: 98, reason: 'Sender alice@ is in your management chain.', context: 'management-chain sender' },
      { filterId: 'fr_12', outcome: 'include', confidence: 82, reason: 'Body references the “rollback budget”.', context: 'mentions rollback' },
    ],
  },
  {
    id: 'itm_8834', summary: 'Weekly engineering digest', source: 'email', created_at: h(5),
    verdict: { decision: 'dropped', confidence: 86, rationale: 'Labeled noise (84%) then matched the newsletter drop rule (88%). Both signals agree on direction, so the aggregator settled on a merged 86% drop with no include to contest it.' },
    stages: [
      { filterId: 'fr_09', outcome: 'label', label: 'noise', confidence: 84, reason: 'Bulk sender with an unsubscribe header.', context: 'label: noise' },
      { filterId: 'fr_24', outcome: 'drop', confidence: 88, reason: 'Matches the newsletter/digest pattern; none of your active projects named.' },
      { filterId: 'fr_22', outcome: 'pass', reason: 'Sender not in your management chain.' },
      { filterId: 'fr_12', outcome: 'pass', reason: 'No rollback / incident / SEV keyword.' },
    ],
  },
  {
    id: 'itm_8831', summary: 'Your receipt from Datadog', source: 'email', created_at: h(9),
    verdict: { decision: 'dropped', confidence: 74, rationale: 'No rule dropped it outright, but the “noise” label (79%) combined with a low base relevance score. The LLM aggregator converted the transactional label into a 74% drop.' },
    stages: [
      { filterId: 'fr_09', outcome: 'label', label: 'noise', confidence: 79, reason: 'Transactional receipt; machine-generated sender.', context: 'label: noise (transactional)' },
      { filterId: 'fr_24', outcome: 'pass', reason: 'Not a newsletter or digest.' },
      { filterId: 'fr_22', outcome: 'pass', reason: 'Sender not in your management chain.' },
      { filterId: 'fr_12', outcome: 'pass', reason: 'No rollback / incident / SEV keyword.' },
    ],
  },
  {
    id: 'itm_8829', summary: 'Standup (recurring)', source: 'calendar', created_at: h(2),
    verdict: { decision: 'dropped', confidence: 90, rationale: 'Single decisive drop rule; nothing downstream contested it.' },
    stages: [
      { filterId: 'fr_19', outcome: 'drop', confidence: 90, reason: 'Recurring invite already accepted, no agenda change since last instance.' },
      { filterId: 'fr_12', outcome: 'pass', reason: 'No rollback / incident / SEV keyword.' },
    ],
  },
  {
    id: 'itm_8826', summary: 'Architecture review (no agenda)', source: 'calendar', created_at: h(1),
    verdict: { decision: 'queued', priority: 'P2', confidence: 41, rationale: 'No filter was decisive — no drop, no force-include. The item was routed to your triage queue with a low-confidence estimated priority for you to decide.' },
    stages: [
      { filterId: 'fr_19', outcome: 'pass', reason: 'You own the meeting and it has no agenda yet — not a stale accepted invite.' },
      { filterId: 'fr_12', outcome: 'pass', reason: 'No rollback / incident / SEV keyword.' },
    ],
  },
  {
    id: 'itm_8822', summary: 'on-call handoff thread', source: 'chat', created_at: h(2),
    verdict: { decision: 'queued', priority: 'P2', confidence: 38, rationale: 'The only matching rule (fr_16) is disabled, and nothing else fired. Routed to the triage queue with a weak estimated priority — no auto-decision was made.' },
    stages: [
      { filterId: 'fr_16', outcome: 'skip', reason: 'Rule is disabled — not evaluated.' },
      { filterId: 'fr_12', outcome: 'pass', reason: 'No alarm currently firing; keyword not present.' },
    ],
  },
  {
    id: 'itm_8818', summary: 'Issue #2204: intermittent gchat thread-tracking drift', source: 'github', created_at: h(4),
    verdict: { decision: 'queued', priority: 'P3', confidence: 44, rationale: 'Two enrichers added context but no filter matched with any confidence — neither drop nor include fired. Sent to your triage queue at a low estimated P3; you decide whether it’s worth tracking.' },
    stages: [
      { filterId: 'en_github', outcome: 'context', reason: 'Resolved the issue; open, unassigned, 0 comments.', context: 'issue #2204 · unassigned · 0 comments' },
      { filterId: 'fr_31', outcome: 'pass', reason: 'Not a dependency bump.' },
      { filterId: 'fr_29', outcome: 'pass', reason: 'You are not a requested reviewer.' },
      { filterId: 'fr_27', outcome: 'pass', reason: 'Not a CI status comment.' },
      { filterId: 'fr_12', outcome: 'pass', reason: 'No rollback / incident / SEV keyword.' },
    ],
  },
]

// EnrichmentSample map keyed by enricher id. context values stringified per type.
const enrichmentSamples = {
  en_github: [
    { id: 'D12871', summary: 'Harden queue worker against SKIP LOCKED contention', context: { author: 'alice', author_team: 'Ingestion Platform', review_status: 'changes_requested', ci: 'failing', files_changed: 3, labels: 'queue, reliability' }, entities: ['person:alice', 'repo:workbench'] },
    { id: 'D12863', summary: 'Rebase reviewer-assignment refactor', context: { author: 'you', review_status: 'approved', ci: 'passing', files_changed: 1 }, entities: ['person:you', 'repo:workbench'] },
    { id: 'itm_8841', summary: 'Bump lodash 4.17.20 → 4.17.21', context: { author: 'dependabot', ci: 'pending', files_changed: 1, labels: 'dependencies' }, entities: ['person:dependabot', 'repo:example'] },
  ],
  en_email: [
    { id: 'eml_5521', summary: 'Re: Q3 reliability plan', context: { sender: 'alice@workbench.dev', subject: 'Re: Q3 reliability plan', thread_id: 'thr_8841', attachments: 0 }, entities: ['person:alice@workbench.dev'] },
    { id: 'eml_5488', summary: 'Weekly engineering digest', context: { sender: 'digest@pragmaticengineer.com', subject: 'This week in engineering', thread_id: 'thr_2201', attachments: 0 }, entities: ['person:digest@pragmaticengineer.com'] },
  ],
  en_calendar: [
    { id: 'cal_8841', summary: 'Architecture review (no agenda)', context: { organizer: 'you', attendee_count: 4, location: 'Mission Control / Zoom', is_recurring: false }, entities: ['person:you'] },
    { id: 'itm_8829', summary: 'Standup (recurring)', context: { organizer: 'bob', attendee_count: 8, location: 'Zoom', is_recurring: true }, entities: ['person:bob'] },
  ],
  en_chat: [
    { id: 'chat_2207', summary: 'On-call: queue-depth alarm cleared', context: { space_name: 'platform-oncall', thread_name: 'queue-depth alarm', participant_count: 5, message_count: 4 }, entities: ['space:platform-oncall', 'person:carol'] },
  ],
}

// ---- Search items (/api/items/search) — searchItems from data.js ----------
const searchItems = [
  {
    id: 'D12871', kind: 'diff', source: 'github', summary: 'Harden queue worker against SKIP LOCKED contention', created_at: m(22), state: 'triaged', priority: 'P0', relevance: 94, tags: ['queue', 'reliability', 'ci-red'],
    llm_summary: 'You are the blocking reviewer and CI is red. This diff touches the exact dequeue-ordering path that caused last week’s queue-depth alarm — a regression here hits ingestion latency directly. Author pushed a new revision after the failure; the retry-backoff moved into the dead-letter path. Worth a careful pass before the release cut.',
    context: { type: 'diff', author: 'alice', team: 'Ingestion Platform', status: 'Needs Review', url: 'https://phabricator.internal/D12871', hunks: [
      { file: 'src/workbench/queue/worker.py', header: '@@ -118,7 +118,9 @@ async def _dequeue', rank: 1, code: ' async def _dequeue(self, conn):\n-    rows = await conn.fetch(SELECT_READY)\n+    rows = await conn.fetch(SELECT_READY_SKIP_LOCKED)\n+    if not rows:\n+        return []\n     return [RawItem.from_row(r) for r in rows]' },
      { file: 'src/workbench/queue/config.py', header: '@@ -22,1 +22,1 @@ class QueueConfig', rank: 2, code: ' class QueueConfig(BaseModel):\n-    max_attempts: int = 3\n+    max_attempts: int = 5' },
    ] },
    stages: [
      { filterId: 'en_github', outcome: 'context', reason: 'Resolved the linked diff and its live CI + review state.', context: 'diff D12871 · CI: failing · you = blocking reviewer' },
      { filterId: 'fr_29', outcome: 'include', confidence: 96, reason: 'You are the blocking reviewer on the linked diff.', context: 'blocking-reviewer' },
      { filterId: 'fr_27', outcome: 'drop', confidence: 45, reason: 'Surface form resembles a CI status line — but it names a human action, so confidence stays low.', weak: true },
      { filterId: 'fr_12', outcome: 'include', confidence: 70, reason: 'References failing CI on a diff you own.' },
    ],
    verdict: { decision: 'triaged', priority: 'P0', confidence: 96, rationale: 'Two include signals (blocking-reviewer 96%, CI-on-owned-diff 70%) outweighed a weak drop (45%); merged → escalate to P0.' },
  },
  {
    id: 'D12863', kind: 'diff', source: 'github', summary: 'Rebase reviewer-assignment refactor onto main', created_at: m(48), state: 'action_item', priority: 'P1', relevance: 78, tags: ['review', 'rebase'],
    llm_summary: 'Three approvals are parked behind your rebase — the branch is 11 commits behind main and has a trivial conflict in the reviewer-assignment module. Low risk, but you are the bottleneck for three other people.',
    context: { type: 'diff', author: 'you', team: 'Ingestion Platform', status: 'Changes requested', url: 'https://phabricator.internal/D12863', hunks: [
      { file: 'src/workbench/review/assign.py', header: '@@ -40,6 +40,6 @@ def pick_reviewer', rank: 1, code: ' def pick_reviewer(diff):\n-    return round_robin(diff.team)\n+    return load_balanced(diff.team, diff.size)' },
    ] },
    stages: [
      { filterId: 'en_github', outcome: 'context', reason: 'Linked diff; 3 approvals pending, branch 11 commits behind.', context: 'diff D12863 · 3 approvals pending' },
      { filterId: 'fr_29', outcome: 'include', confidence: 81, reason: 'Reviewers are blocked on your action.', context: 'reviewers blocked' },
    ],
    verdict: { decision: 'triaged', priority: 'P1', confidence: 81, rationale: 'Single include signal (reviewers blocked on you); promoted to an action item at P1.' },
  },
  {
    id: 'eml_5521', kind: 'email', source: 'email', summary: 'Re: Q3 reliability plan — sign-off needed', created_at: m(40), state: 'triaged', priority: 'P0', relevance: 91, tags: ['q3', 'decision', 'rollback'],
    llm_summary: 'From your management chain, with an explicit EOD deadline. Two open questions remain on the rollback budget before you can sign off. This is the highest-leverage thing in your inbox today.',
    context: { type: 'email', from: 'alice@workbench.dev', to: 'you@workbench.dev', when: m(40), body: 'Hi — we need your sign-off on the Q3 reliability plan before end of day.\n\nTwo open questions on the rollback budget:\n1. Does the 5-attempt dead-letter ceiling change the SLA math?\n2. Who owns the runbook update?\n\nThe arch review at 14:00 will cover the rest. Thanks.' },
    stages: [
      { filterId: 'fr_22', outcome: 'include', confidence: 98, reason: 'Sender alice@ is in your management chain.', context: 'management-chain sender' },
      { filterId: 'fr_12', outcome: 'include', confidence: 82, reason: 'Body references the “rollback budget”.', context: 'mentions rollback' },
    ],
    verdict: { decision: 'triaged', priority: 'P0', confidence: 97, rationale: 'Two independent include signals (mgmt-chain 98%, rollback keyword 82%) merged and raised to P0.' },
  },
  {
    id: 'cal_8841', kind: 'meeting', source: 'calendar', summary: 'Architecture review (no agenda)', created_at: h(1), state: 'pending_triage', priority: 'P2', relevance: 41, tags: ['meeting', 'arch'],
    llm_summary: 'You own this meeting and it has no agenda posted yet — it moved to 14:00. Nothing dropped it, so it surfaced at P2 by default scoring. Posting the agenda would also clear an action item.',
    context: { type: 'meeting', when: h(-3), duration: '45m', attendees: ['you', 'alice', 'bob', 'carol'], agenda: null, location: 'Mission Control / Zoom' },
    stages: [
      { filterId: 'fr_19', outcome: 'pass', reason: 'You own the meeting and it has no agenda yet — not a stale accepted invite.' },
      { filterId: 'fr_12', outcome: 'pass', reason: 'No rollback / incident / SEV keyword.' },
    ],
    verdict: { decision: 'queued', priority: 'P2', confidence: 41, rationale: 'No filter was decisive — routed to your triage queue with a low-confidence estimated priority for you to decide.' },
  },
  {
    id: 'chat_2207', kind: 'chat', source: 'chat', summary: 'On-call: queue-depth alarm cleared, post-mortem requested', created_at: h(2), state: 'pending_triage', priority: 'P2', relevance: 38, tags: ['on-call', 'post-mortem'],
    llm_summary: 'The queue-depth alarm cleared at 02:14 and the thread asks for a post-mortem — no owner assigned yet. Not urgent now that it’s cleared, but it ties back to the D12871 diff you’re reviewing.',
    context: { type: 'chat', channel: '#platform-oncall', messages: [
      { who: 'pagerduty', when: h(5), text: 'TRIGGERED: ingestion_queue depth > 100 (was 142)' },
      { who: 'bob', when: h(3), text: 'looking — looks like the SKIP LOCKED change on D12871' },
      { who: 'pagerduty', when: h(2), text: 'RESOLVED: ingestion_queue depth back to 6' },
      { who: 'carol', when: h(2), text: 'can someone own a quick post-mortem? @you you reviewed the diff' },
    ] },
    stages: [
      { filterId: 'fr_16', outcome: 'skip', reason: 'Rule is disabled — not evaluated.' },
      { filterId: 'fr_12', outcome: 'pass', reason: 'No alarm currently firing; keyword not present.' },
    ],
    verdict: { decision: 'queued', priority: 'P2', confidence: 38, rationale: 'The only matching rule is disabled and nothing else fired — routed to the triage queue with a weak estimated priority; no auto-decision was made.' },
  },
  {
    id: 'itm_8841', kind: 'pr', source: 'github', summary: 'Bump lodash 4.17.20 → 4.17.21', created_at: h(3), state: 'dropped', priority: null, relevance: 12, tags: ['dependency'],
    llm_summary: 'A routine dependency bump with no advisory attached — the noise filter dropped it automatically. Nothing here needs you; included only so you can see why it was filtered.',
    context: { type: 'diff', author: 'dependabot', team: '—', status: 'Open', url: 'https://github.com/example/pr/4821', hunks: [{ file: 'package.json', header: '@@ -18,1 +18,1 @@', rank: 1, code: '-    "lodash": "4.17.20",\n+    "lodash": "4.17.21",' }] },
    stages: [
      { filterId: 'en_github', outcome: 'context', reason: 'No linked diff; tagged as a pure dependency PR.', context: 'dependency PR · no CI run' },
      { filterId: 'fr_31', outcome: 'drop', confidence: 91, reason: 'Dependency bump; no CVE or advisory referenced.' },
    ],
    verdict: { decision: 'dropped', confidence: 91, rationale: 'First decisive rule (fr_31) dropped it; no downstream include contested the decision.' },
  },
  {
    id: 'eml_5488', kind: 'email', source: 'email', summary: 'Weekly engineering digest', created_at: h(5), state: 'dropped', priority: null, relevance: 8, tags: ['newsletter', 'noise'],
    llm_summary: 'Bulk digest with no active project named — labeled noise and dropped. No action needed.',
    context: { type: 'email', from: 'digest@pragmaticengineer.com', to: 'you@workbench.dev', when: h(5), body: 'This week in engineering: 14 links on platform reliability, hiring, and tooling…' },
    stages: [
      { filterId: 'fr_09', outcome: 'label', label: 'noise', confidence: 84, reason: 'Bulk sender with an unsubscribe header.', context: 'label: noise' },
      { filterId: 'fr_24', outcome: 'drop', confidence: 88, reason: 'Newsletter/digest; no active project named.' },
    ],
    verdict: { decision: 'dropped', confidence: 86, rationale: 'Labeled noise then matched the newsletter drop rule; both agree on direction.' },
  },
  {
    id: 'itm_8829', kind: 'meeting', source: 'calendar', summary: 'Standup (recurring)', created_at: h(2), state: 'dropped', priority: null, relevance: 6, tags: ['recurring'],
    llm_summary: 'A recurring standup you’ve already accepted with no agenda change — auto-dropped. Surfaces only in search.',
    context: { type: 'meeting', when: h(-1), duration: '15m', attendees: ['you', 'team'], agenda: 'Standup — same as every day', location: 'Zoom' },
    stages: [{ filterId: 'fr_19', outcome: 'drop', confidence: 90, reason: 'Recurring invite already accepted, no agenda change.' }],
    verdict: { decision: 'dropped', confidence: 90, rationale: 'Single decisive drop rule; nothing contested it.' },
  },
]

// ---- Feedback (useFeedback.ts) --------------------------------------------
const corrections = [
  { id: 'cor_01', item_id: 'itm_8841', rule_id: 'fr_31', original_action: 'drop', corrected_action: 'include', reason: 'This dependency bump patched a CVE I cared about', created_at: d(1) },
  { id: 'cor_02', item_id: 'itm_8834', rule_id: null, original_action: 'include', corrected_action: 'drop', reason: null, created_at: d(2) },
]
const tuningTasks = [
  { id: 'task_01', rule_id: 'fr_31', proposed_prompt: 'Drop dependency-bump PRs that carry no security advisory — but surface ones that reference a CVE (you corrected this).', correction_ids: ['cor_01'], status: 'open', created_at: d(1), resolved_at: null },
  { id: 'task_02', rule_id: 'fr_24', proposed_prompt: 'Drop newsletter/digest emails — refined to keep ones naming an active project.', correction_ids: ['cor_02'], status: 'applied', created_at: d(2), resolved_at: d(2) },
]

// ===========================================================================
// Routing
// ===========================================================================

function send(res, status, body) {
  const json = JSON.stringify(body)
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, PUT, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    'X-Request-ID': 'mock-' + Math.random().toString(36).slice(2, 10),
  })
  res.end(json)
}

function readBody(req) {
  return new Promise((resolve) => {
    let data = ''
    req.on('data', (c) => (data += c))
    req.on('end', () => {
      try {
        resolve(data ? JSON.parse(data) : {})
      } catch {
        resolve({})
      }
    })
  })
}

// Route table: [method, RegExp, handler(res, match, query, body)].
const routes = [
  // Auth
  ['GET', /^\/api\/auth\/token$/, (res) => send(res, 200, { token: 'dev-mock-token' })],

  // Stats
  ['GET', /^\/api\/stats\/overview$/, (res) => send(res, 200, overview)],
  ['GET', /^\/api\/stats\/queue$/, (res) => send(res, 200, queueStats)],
  ['GET', /^\/api\/stats\/sources$/, (res) => send(res, 200, sources)],
  ['GET', /^\/api\/stats\/ingestion-timeseries$/, (res) => send(res, 200, ingestionSeries)],
  ['GET', /^\/api\/stats\/timeseries$/, (res, _m, q) =>
    send(res, 200, q.get('metric') === 'throughput' ? throughputSeries : signalVelocity)],

  // Topology / jobs / activity / connections / health / debug
  ['GET', /^\/api\/topology$/, (res) => send(res, 200, topology)],
  ['GET', /^\/api\/jobs$/, (res, _m, q) => {
    const limit = Number(q.get('limit') ?? 10)
    const offset = Number(q.get('offset') ?? 0)
    const status = q.get('status')
    let list = status ? allJobs.filter((j) => j.status === status) : allJobs
    return send(res, 200, { jobs: list.slice(offset, offset + limit), total: list.length, limit, offset })
  }],
  ['GET', /^\/api\/activity$/, (res, _m, q) => {
    const limit = Number(q.get('limit') ?? 50)
    return send(res, 200, activity.slice(0, limit))
  }],
  ['GET', /^\/api\/connections$/, (res) => send(res, 200, connections)],
  ['GET', /^\/api\/health$/, (res) => send(res, 200, health)],
  ['GET', /^\/health$/, (res) => send(res, 200, health)],
  ['GET', /^\/api\/debug\/config$/, (res) => send(res, 200, debugConfig)],

  // Triage
  ['GET', /^\/api\/triage\/pending$/, (res) => send(res, 200, triageCards)],
  ['GET', /^\/api\/triage\/cards\/([^/]+)$/, (res, mm) => {
    const card = triageCards.find((c) => c.id === mm[1])
    // Return the rich detail for the flagship card; else a generic detail.
    if (mm[1] === triageDetail.id) return send(res, 200, triageDetail)
    return send(res, 200, card ?? triageDetail)
  }],
  ['POST', /^\/api\/triage\/respond$/, (res, _m, _q, body) =>
    send(res, 200, { status: 'recorded', card_id: body.card_id, action: body.choice != null ? 'numbered' : 'interpreted' })],
  ['POST', /^\/api\/triage\/confirm$/, (res, _m, _q, body) =>
    send(res, 200, { status: body.confirm ? 'completed' : 'cancelled', card_id: body.card_id })],

  // Actions
  ['GET', /^\/api\/actions$/, (res, _m, q) => send(res, 200, actionsResponse(q.get('category')))],
  ['POST', /^\/api\/actions$/, (res, _m, _q, body) =>
    send(res, 200, { id: 'act_' + Math.floor(Math.random() * 9000 + 1000), summary: body.summary ?? '', priority: body.priority ?? 'P2', action_category: body.action_category ?? null, action_source: 'manual', parent_item: null, created_at: new Date().toISOString() })],
  ['POST', /^\/api\/actions\/([^/]+)\/(done|priority|snooze)$/, (res) => send(res, 200, { ok: true })],

  // Items (Hot Feed: GET /api/items?status=pending_triage)
  ['GET', /^\/api\/items$/, (res, _m, q) => {
    const hot = [
      { id: 'D12871', source_type: 'github', source_id: 'src_github_main', summary: 'CI is red on D12871 and you are the blocking reviewer', category: 'action_item', origin: 'triaged', priority: 'P0', status: 'pending_triage', created_at: m(6), updated_at: m(6) },
      { id: 'eml_5521', source_type: 'email', source_id: 'src_email_work', summary: 'VP Eng flagged the Q3 reliability plan — needs sign-off today', category: 'action_item', origin: 'triaged', priority: 'P0', status: 'pending_triage', created_at: m(22), updated_at: m(22) },
      { id: 'D12863', source_type: 'github', source_id: 'src_github_main', summary: 'Reviewers blocked on D12863 — 3 approvals pending your rebase', category: 'action_item', origin: 'triaged', priority: 'P1', status: 'pending_triage', created_at: m(48), updated_at: m(48) },
      { id: 'cal_8841', source_type: 'calendar', source_id: 'src_calendar', summary: 'Architecture review moved to 14:00 — agenda not yet posted', category: 'meeting', origin: 'triaged', priority: 'P1', status: 'pending_triage', created_at: h(1), updated_at: h(1) },
      { id: 'chat_2207', source_type: 'chat', source_id: 'src_gchat', summary: 'On-call thread: queue depth alarm cleared, post-mortem requested', category: 'informational', origin: 'triaged', priority: 'P2', status: 'pending_triage', created_at: h(2), updated_at: h(2) },
    ]
    const status = q.get('status'); const priority = q.get('priority')
    let list = hot
    if (status) list = list.filter((it) => it.status === status)
    if (priority) list = list.filter((it) => it.priority === priority)
    return send(res, 200, list)
  }],

  // Items / search
  ['GET', /^\/api\/items\/search$/, (res, _m, q) => {
    const query = (q.get('q') || '').toLowerCase()
    const list = query ? searchItems.filter((it) => (it.summary + ' ' + (it.llm_summary || '')).toLowerCase().includes(query)) : searchItems
    return send(res, 200, list)
  }],
  ['POST', /^\/api\/items\/([^/]+)\/(snooze|archive|boost)$/, (res) => send(res, 200, { status: 'ok' })],

  // Funnel
  ['GET', /^\/api\/funnel\/filter-rules$/, (res) => send(res, 200, filterRules)],
  ['POST', /^\/api\/funnel\/filter-rules$/, (res, _m, _q, body) =>
    send(res, 200, { id: 'fr_' + Math.random().toString(36).slice(2, 6), prompt: body.prompt ?? '', action: body.action ?? 'drop', sources: body.sources ?? [], confidence: null, origin: 'explicit', matched: 0, enabled: true, order_index: filterRules.length })],
  ['DELETE', /^\/api\/funnel\/filter-rules\/([^/]+)$/, (res) => send(res, 200, { status: 'deleted' })],
  ['GET', /^\/api\/funnel\/enrichers$/, (res) => send(res, 200, enrichers)],
  ['GET', /^\/api\/funnel\/enrichment-samples$/, (res) => send(res, 200, enrichmentSamples)],
  ['GET', /^\/api\/funnel\/loopbacks$/, (res) => send(res, 200, loopbacks)],
  ['GET', /^\/api\/funnel\/order$/, (res) => send(res, 200, funnelOrder)],
  ['PATCH', /^\/api\/funnel\/order$/, (res) => send(res, 200, { status: 'ok' })],
  ['GET', /^\/api\/funnel\/items$/, (res, _m, q) => {
    const source = q.get('source')
    const verdict = q.get('verdict')
    // Always return the rich SearchItem shape — it is a superset of FunnelItem
    // (id/summary/stages/verdict) plus tags/context/llm_summary that the Search
    // page needs. Satisfies both the Search page and the Filters output table.
    let list = searchItems
    const query = (q.get('q') || '').toLowerCase()
    if (source) list = list.filter((it) => it.source === source)
    if (verdict) list = list.filter((it) => it.verdict && it.verdict.decision === verdict)
    if (query) list = list.filter((it) => (it.summary + ' ' + (it.llm_summary || '')).toLowerCase().includes(query))
    return send(res, 200, list)
  }],
  ['GET', /^\/api\/funnel\/items\/([^/]+)$/, (res, mm) => {
    const item = funnelItems.find((it) => it.id === mm[1]) || searchItems.find((it) => it.id === mm[1])
    return item ? send(res, 200, item) : send(res, 404, { detail: 'not found' })
  }],
  ['PATCH', /^\/api\/funnel\/stages\/([^/]+)$/, (res) => send(res, 200, { status: 'ok' })],
  ['POST', /^\/api\/funnel\/stages\/([^/]+)\/toggle$/, (res) => send(res, 200, { status: 'ok' })],

  // Feedback
  ['GET', /^\/api\/feedback\/corrections$/, (res, _m, q) => {
    const itemId = q.get('item_id')
    return send(res, 200, itemId ? corrections.filter((c) => c.item_id === itemId) : corrections)
  }],
  ['POST', /^\/api\/feedback\/corrections$/, (res, _m, _q, body) =>
    send(res, 200, { id: 'cor_' + Math.random().toString(36).slice(2, 6), item_id: body.item_id ?? 'itm_x', rule_id: body.rule_id ?? null, original_action: body.original_action ?? 'pass', corrected_action: body.corrected_action ?? 'include', reason: body.reason ?? null, created_at: new Date().toISOString() })],
  ['DELETE', /^\/api\/feedback\/corrections\/([^/]+)$/, (res) => send(res, 200, { status: 'deleted' })],
  ['GET', /^\/api\/feedback\/tasks$/, (res, _m, q) => {
    const status = q.get('status')
    return send(res, 200, status ? tuningTasks.filter((t) => t.status === status) : tuningTasks)
  }],
  ['POST', /^\/api\/feedback\/tasks$/, (res, _m, _q, body) =>
    send(res, 200, { id: 'task_' + Math.random().toString(36).slice(2, 6), rule_id: body.rule_id ?? 'fr_x', proposed_prompt: body.proposed_prompt ?? 'refined prompt', correction_ids: body.correction_ids ?? [], status: body.status ?? 'open', created_at: new Date().toISOString(), resolved_at: null })],
  ['PATCH', /^\/api\/feedback\/tasks\/([^/]+)$/, (res, mm, q) => {
    const t = tuningTasks.find((x) => x.id === mm[1])
    return send(res, 200, { ...(t ?? { id: mm[1], rule_id: 'fr_x', proposed_prompt: '', correction_ids: [] }), status: q.get('status') ?? 'applied', resolved_at: new Date().toISOString() })
  }],
  ['DELETE', /^\/api\/feedback\/tasks\/([^/]+)$/, (res) => send(res, 200, { status: 'deleted' })],

  // Sources
  ['GET', /^\/api\/sources\/adapter-types$/, (res) => send(res, 200, adapterTypes)],
  ['GET', /^\/api\/sources$/, (res) => send(res, 200, sources)],
  ['POST', /^\/api\/sources$/, (res) => send(res, 200, { id: 'src_' + Math.random().toString(36).slice(2, 6) })],
  ['PATCH', /^\/api\/sources\/([^/]+)$/, (res) => send(res, 200, { status: 'ok' })],
  ['DELETE', /^\/api\/sources\/([^/]+)$/, (res) => send(res, 200, { status: 'deleted' })],
  ['POST', /^\/api\/sources\/([^/]+)\/poll$/, (res) => send(res, 200, { status: 'ok' })],

  // Messenger
  ['GET', /^\/api\/messenger$/, (res) => send(res, 200, messenger)],
  ['PATCH', /^\/api\/messenger$/, (res) => send(res, 200, { status: 'ok' })],

  // Memory facts
  ['GET', /^\/api\/memory\/facts$/, (res) => send(res, 200, factsEnvelope)],
  ['POST', /^\/api\/memory\/facts$/, (res, _m, _q, body) =>
    send(res, 200, { id: 'f_' + Math.random().toString(36).slice(2, 6), content: body.content ?? '', source: 'manual', timestamp: new Date().toISOString() })],
  ['PATCH', /^\/api\/memory\/facts\/([^/]+)$/, (res) => send(res, 200, { status: 'ok' })],
  ['DELETE', /^\/api\/memory\/facts\/([^/]+)$/, (res) => send(res, 200, { status: 'deleted' })],

  // Queue dead-letter
  ['GET', /^\/api\/queue\/dead-letter$/, (res) => send(res, 200, deadLetters)],
  ['POST', /^\/api\/queue\/dead-letter\/([^/]+)\/retry$/, (res) => send(res, 200, { status: 'requeued' })],
  ['DELETE', /^\/api\/queue\/dead-letter\/([^/]+)$/, (res) => send(res, 200, { status: 'purged' })],
]

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`)
  const path = url.pathname
  const method = req.method
  console.log(`${method} ${req.url}`)

  // CORS preflight
  if (method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, PUT, OPTIONS',
      'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    })
    return res.end()
  }

  const body = method === 'GET' || method === 'HEAD' ? {} : await readBody(req)

  for (const [m2, re, handler] of routes) {
    if (m2 !== method) continue
    const match = re.exec(path)
    if (match) return handler(res, match, url.searchParams, body)
  }

  // Unknown endpoint: valid empty response. GET → []; mutations → {ok:true}.
  if (method === 'GET') return send(res, 200, [])
  return send(res, 200, { ok: true })
})

server.listen(PORT, HOST, () => {
  console.log(`WorkBench dev mock API listening on http://${HOST}:${PORT}`)
})
