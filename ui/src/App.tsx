import { Routes, Route } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Overview } from '@/pages/Overview'
import { Triage } from '@/pages/Triage'
import { TriageDetail } from '@/pages/TriageDetail'
import { ActionItems } from '@/pages/ActionItems'
import { Ingestion } from '@/pages/Ingestion'
import { Sources } from '@/pages/Sources'
import { Knowledge } from '@/pages/Knowledge'
import { Messenger } from '@/pages/Messenger'
import { Settings } from '@/pages/Settings'
import { Filters } from '@/pages/Filters'
import { Search } from '@/pages/Search'
import { SystemStatus } from '@/pages/SystemStatus'

export default function App() {
  return (
    <AppShell>
      <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/triage" element={<Triage />} />
          <Route path="/triage/:cardId" element={<TriageDetail />} />
          <Route path="/actions" element={<ActionItems />} />
          <Route path="/ingestion" element={<Ingestion />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/messenger" element={<Messenger />} />
          {/* Settings sub-tab routes (Slice 8) */}
          <Route path="/settings" element={<Settings />} />
          <Route path="/settings/sources" element={<Settings />} />
          <Route path="/settings/messenger" element={<Settings />} />
          <Route path="/system" element={<SystemStatus />} />
          {/* V3 route aliases */}
          <Route path="/search" element={<Search />} />
          <Route path="/filters" element={<Filters />} />
        </Routes>
      </ErrorBoundary>
    </AppShell>
  )
}
