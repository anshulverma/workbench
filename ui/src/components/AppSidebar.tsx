import { NavLink } from 'react-router-dom'

const NAV = [
  { to: '/', label: 'Overview' },
  { to: '/triage', label: 'Triage' },
  { to: '/actions', label: 'Action Items' },
  { to: '/ingestion', label: 'Ingestion' },
  { to: '/sources', label: 'Sources' },
  { to: '/knowledge', label: 'Knowledge' },
  { to: '/messenger', label: 'Messenger' },
  { to: '/settings', label: 'Settings' },
]

export function AppSidebar() {
  return (
    <nav
      aria-label="Primary"
      className="w-52 shrink-0 border-r border-border p-3"
    >
      <h1 className="mb-4 px-2 text-lg font-bold">Workbench</h1>
      <ul className="space-y-1">
        {NAV.map((n) => (
          <li key={n.to}>
            <NavLink
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                `block rounded px-2 py-1.5 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring ${
                  isActive
                    ? 'bg-muted font-medium'
                    : 'text-muted-foreground hover:bg-muted'
                }`
              }
            >
              {n.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
