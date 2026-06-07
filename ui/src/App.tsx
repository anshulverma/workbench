import { Routes, Route } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Overview } from '@/pages/Overview'
import { Triage } from '@/pages/Triage'
import { ActionItems } from '@/pages/ActionItems'
import { Ingestion } from '@/pages/Ingestion'
import { Sources } from '@/pages/Sources'
import { Knowledge } from '@/pages/Knowledge'
import { Messenger } from '@/pages/Messenger'
import { Settings } from '@/pages/Settings'

export default function App() {
  return (
    <AppShell>
      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/triage" element={<Triage />} />
          <Route path="/actions" element={<ActionItems />} />
          <Route path="/ingestion" element={<Ingestion />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/messenger" element={<Messenger />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </ErrorBoundary>
    </AppShell>
  )
}
