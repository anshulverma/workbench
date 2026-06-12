// Settings page — tab container with System / Sources / Messenger sub-tabs.
//
// Tab state is driven by the React Router URL (HashRouter). The active tab is
// derived from the current pathname: /settings/sources -> "sources",
// /settings/messenger -> "messenger", anything else -> "system". Clicking a
// tab navigates to the corresponding route so the URL is always bookmarkable.
//
// Each sub-tab renders its own content component. Sources and Messenger are
// rendered with `embedded` prop so they hide their own h1 headings.

import { useLocation, useNavigate } from 'react-router-dom'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { SettingsSystem } from './SettingsSystem'
import { Sources } from './Sources'
import { Messenger } from './Messenger'

const TABS = [
  { id: 'system', label: 'System' },
  { id: 'sources', label: 'Sources' },
  { id: 'messenger', label: 'Messenger' },
] as const

type TabId = (typeof TABS)[number]['id']

function deriveTab(pathname: string): TabId {
  const seg = pathname.split('/')[2] // /settings/<tab>
  if (seg === 'sources' || seg === 'messenger') return seg
  return 'system'
}

function tabRoute(tab: TabId): string {
  if (tab === 'system') return '/settings'
  return `/settings/${tab}`
}

export function Settings() {
  const location = useLocation()
  const navigate = useNavigate()
  const active = deriveTab(location.pathname)

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Settings</h1>

      <Tabs
        value={active}
        onValueChange={(v) => navigate(tabRoute(v as TabId))}
      >
        <TabsList>
          {TABS.map((t) => (
            <TabsTrigger key={t.id} value={t.id}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="system">
          <SettingsSystem />
        </TabsContent>

        <TabsContent value="sources">
          <Sources embedded />
        </TabsContent>

        <TabsContent value="messenger">
          <Messenger embedded />
        </TabsContent>
      </Tabs>
    </div>
  )
}
