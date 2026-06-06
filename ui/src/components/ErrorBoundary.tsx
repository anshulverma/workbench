import { Component, type ReactNode } from 'react'

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error) {
    return { error }
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
