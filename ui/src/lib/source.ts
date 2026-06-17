// Source-type display helpers shared by the Triage feed and detail pages.
//
// Cards carry a raw `source_type` (the adapter_type string, e.g. "meta_tasks",
// "diff", "github"). SOURCE_LABEL maps the common ones to friendlier labels for
// the source-type badge; unmapped values fall through unchanged.

export const SOURCE_LABEL: Record<string, string> = {
  meta_tasks: 'task',
  diff: 'diff',
  github: 'github',
  email: 'email',
  calendar: 'calendar',
  chat: 'chat',
  meta_docs: 'doc',
  google_docs: 'doc',
  workplace: 'workplace',
}

export function sourceLabel(sourceType: string | undefined): string {
  if (!sourceType) return 'unknown'
  return SOURCE_LABEL[sourceType] ?? sourceType
}
