import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export function StatCard({
  label,
  value,
  danger,
}: {
  label: string
  value: ReactNode
  danger?: boolean
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {label}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${danger ? 'text-destructive' : ''}`}>
          {value}
        </div>
      </CardContent>
    </Card>
  )
}
