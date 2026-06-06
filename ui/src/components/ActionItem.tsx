// ui/src/components/ActionItem.tsx
import { markDone, changePriority, snooze, type Action } from '@/lib/api'

interface Props {
  item: Action
  onUpdate: () => void
}

const priorityClasses: Record<string, string> = {
  P0: 'text-red-600 font-bold',
  P1: 'text-orange-600 font-bold',
  P2: 'text-blue-600 font-bold',
  P3: 'text-gray-500 font-bold',
}

export function ActionItem({ item, onUpdate }: Props) {
  const hours = Math.floor(
    (Date.now() - new Date(item.created_at).getTime()) / (1000 * 60 * 60),
  )
  const ageLabel = hours < 24 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`

  return (
    <li className="mb-3 list-none">
      <div className="flex items-baseline gap-2">
        <span className={`text-sm ${priorityClasses[item.priority] || 'text-gray-800 font-bold'}`}>
          [{item.priority}]
        </span>
        <span>{item.summary}</span>
        {item.parent_item && (
          <span className="text-gray-500 text-sm">
            from {item.parent_item.summary}
          </span>
        )}
        <span className="text-gray-400 text-xs">{ageLabel}</span>
      </div>
      <div className="mt-1 flex gap-1">
        <button className="px-2 py-0.5 text-sm border rounded hover:bg-gray-100" onClick={() => markDone(item.id).then(onUpdate)}>Done</button>
        <button className="px-2 py-0.5 text-sm border rounded hover:bg-gray-100" onClick={() => changePriority(item.id, 'P0').then(onUpdate)}>P0</button>
        <button className="px-2 py-0.5 text-sm border rounded hover:bg-gray-100" onClick={() => changePriority(item.id, 'P1').then(onUpdate)}>P1</button>
        <button className="px-2 py-0.5 text-sm border rounded hover:bg-gray-100" onClick={() => changePriority(item.id, 'P2').then(onUpdate)}>P2</button>
        <button className="px-2 py-0.5 text-sm border rounded hover:bg-gray-100" onClick={() => changePriority(item.id, 'P3').then(onUpdate)}>P3</button>
        <button className="px-2 py-0.5 text-sm border rounded hover:bg-gray-100" onClick={() => snooze(item.id, 4).then(onUpdate)}>Snooze 4h</button>
      </div>
    </li>
  )
}
