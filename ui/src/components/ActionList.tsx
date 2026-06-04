// ui/src/components/ActionList.tsx
import { useState, useEffect, useCallback } from 'react'
import { fetchActions, type Action } from '../api'
import { ActionItem } from './ActionItem'

interface ActionsData {
  categories: Record<string, Action[]>
  total: number
}

export function ActionList() {
  const [data, setData] = useState<ActionsData | null>(null)
  const [filter, setFilter] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    const params: Record<string, string> = {}
    if (filter) params.category = filter
    fetchActions(params)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [filter])

  useEffect(() => {
    load()
  }, [load])

  if (loading && !data) return <div className="text-gray-500">Loading...</div>
  if (error) return <div className="text-red-600">Error: {error}</div>
  if (!data) return null

  const categories = Object.entries(data.categories)

  return (
    <div>
      <div className="flex items-center gap-4 mb-4">
        <h1 className="m-0 text-2xl font-bold">Action Items ({data.total})</h1>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="px-2 py-1 border rounded"
        >
          <option value="">All categories</option>
          <option value="delegation">Delegation</option>
          <option value="communication">Communication</option>
          <option value="scheduling">Scheduling</option>
          <option value="review">Review</option>
          <option value="creation">Creation</option>
          <option value="update">Update</option>
          <option value="decision">Decision</option>
          <option value="investigation">Investigation</option>
        </select>
        <button className="px-3 py-1 border rounded hover:bg-gray-100 disabled:opacity-50" onClick={load} disabled={loading}>
          Refresh
        </button>
      </div>
      {categories.map(([category, items]) => (
        <details key={category} open>
          <summary className="cursor-pointer font-bold mb-2">
            {category.charAt(0).toUpperCase() + category.slice(1)} ({items.length})
          </summary>
          <ul className="p-0">
            {items.map((item) => (
              <ActionItem key={item.id} item={item} onUpdate={load} />
            ))}
          </ul>
        </details>
      ))}
      {categories.length === 0 && (
        <p className="text-gray-500">No pending actions. You are all caught up.</p>
      )}
    </div>
  )
}
