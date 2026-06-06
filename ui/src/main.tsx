import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { HashRouter } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { queryClient } from '@/lib/query-client'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <HashRouter>
        <App />
        <Toaster />
      </HashRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
