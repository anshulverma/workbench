import { Component, type ErrorInfo, type ReactNode } from 'react'
import { reportClientError } from '@/lib/error-reporter'

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    reportClientError({
      level: 'error',
      kind: 'react',
      message: error.message,
      stack: error.stack,
      component_stack: info.componentStack ?? undefined,
    })
  }

  render() {
    if (this.state.error) {
      const requestId = (this.state.error as { requestId?: string }).requestId
      return (
        <div role="alert" className="p-6 text-destructive">
          <p>Something went wrong: {this.state.error.message}</p>
          {requestId && <p className="text-xs">Request ID: {requestId}</p>}
        </div>
      )
    }
    return this.props.children
  }
}
