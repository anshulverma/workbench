import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DataTable, type Column } from './DataTable'

type Row = { id: string; name: string }
const rows: Row[] = [{ id: 'WRK-1', name: 'alpha' }]

describe('DataTable mono columns', () => {
  it('adds font-mono tabular-nums to mono cells only', () => {
    const cols: Column<Row>[] = [
      { key: 'id', header: 'ID', render: (r) => r.id, mono: true },
      { key: 'name', header: 'Name', render: (r) => r.name },
    ]
    render(<DataTable columns={cols} rows={rows} rowKey={(r) => r.id} />)
    expect(screen.getByText('WRK-1').closest('td')!.className).toContain(
      'font-mono',
    )
    expect(screen.getByText('alpha').closest('td')!.className).not.toContain(
      'font-mono',
    )
  })
})
