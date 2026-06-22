import { useSearchParams } from 'react-router-dom'

/** Reads/writes the `?item=<id>` search param that drives the item-detail dialog. */
export function useItemDialog() {
  const [params, setParams] = useSearchParams()
  const raw = params.get('item')
  const itemId = raw != null && /^\d+$/.test(raw) ? Number(raw) : null

  const openItem = (id: number) => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('item', String(id))
        return next
      },
      { replace: false },
    )
  }
  const closeItem = () => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete('item')
        return next
      },
      { replace: false },
    )
  }
  return { itemId, openItem, closeItem }
}
