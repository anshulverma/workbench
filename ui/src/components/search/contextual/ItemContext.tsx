import type { ItemContext as ItemContextType } from '@/lib/types/search'
import { DiffContext } from './DiffContext'
import { EmailContext } from './EmailContext'
import { MeetingContext } from './MeetingContext'
import { ChatContext } from './ChatContext'

/**
 * ItemContext — dispatcher that renders the correct contextual payload
 * component based on the context's `type` field.
 */
export function ItemContext({ ctx }: { ctx: ItemContextType | null }) {
  if (!ctx) return null
  switch (ctx.type) {
    case 'diff':
      return <DiffContext ctx={ctx} />
    case 'email':
      return <EmailContext ctx={ctx} />
    case 'meeting':
      return <MeetingContext ctx={ctx} />
    case 'chat':
      return <ChatContext ctx={ctx} />
    default:
      return null
  }
}
