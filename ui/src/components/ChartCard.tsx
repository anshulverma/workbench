import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export function ChartCard({
  title,
  children,
  empty,
}: {
  title: string
  children: ReactNode
  empty?: boolean
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent className="h-64">
        {empty ? (
          <p className="text-muted-foreground text-sm">No data yet</p>
        ) : (
          children
        )}
      </CardContent>
    </Card>
  )
}
