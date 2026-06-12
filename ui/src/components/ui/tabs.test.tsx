import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Tabs, TabsList, TabsTrigger, TabsContent } from './tabs'

describe('Tabs', () => {
  it('renders the default tab content', () => {
    render(
      <Tabs defaultValue="a">
        <TabsList>
          <TabsTrigger value="a">Tab A</TabsTrigger>
          <TabsTrigger value="b">Tab B</TabsTrigger>
        </TabsList>
        <TabsContent value="a">Content A</TabsContent>
        <TabsContent value="b">Content B</TabsContent>
      </Tabs>,
    )
    expect(screen.getByText('Content A')).toBeInTheDocument()
    expect(screen.queryByText('Content B')).not.toBeInTheDocument()
  })

  it('switches tab on click', async () => {
    const user = userEvent.setup()
    render(
      <Tabs defaultValue="a">
        <TabsList>
          <TabsTrigger value="a">Tab A</TabsTrigger>
          <TabsTrigger value="b">Tab B</TabsTrigger>
        </TabsList>
        <TabsContent value="a">Content A</TabsContent>
        <TabsContent value="b">Content B</TabsContent>
      </Tabs>,
    )
    await user.click(screen.getByRole('tab', { name: 'Tab B' }))
    expect(screen.queryByText('Content A')).not.toBeInTheDocument()
    expect(screen.getByText('Content B')).toBeInTheDocument()
  })

  it('sets aria-selected on active trigger', () => {
    render(
      <Tabs defaultValue="x">
        <TabsList>
          <TabsTrigger value="x">X</TabsTrigger>
          <TabsTrigger value="y">Y</TabsTrigger>
        </TabsList>
        <TabsContent value="x">cx</TabsContent>
        <TabsContent value="y">cy</TabsContent>
      </Tabs>,
    )
    expect(screen.getByRole('tab', { name: 'X' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tab', { name: 'Y' })).toHaveAttribute(
      'aria-selected',
      'false',
    )
  })

  it('renders tabpanel role on visible content', () => {
    render(
      <Tabs defaultValue="one">
        <TabsList>
          <TabsTrigger value="one">One</TabsTrigger>
        </TabsList>
        <TabsContent value="one">Panel</TabsContent>
      </Tabs>,
    )
    expect(screen.getByRole('tabpanel')).toBeInTheDocument()
  })

  it('supports controlled value', async () => {
    let current = 'a'
    const onChange = (v: string) => {
      current = v
    }
    const { rerender } = render(
      <Tabs value={current} onValueChange={onChange}>
        <TabsList>
          <TabsTrigger value="a">A</TabsTrigger>
          <TabsTrigger value="b">B</TabsTrigger>
        </TabsList>
        <TabsContent value="a">CA</TabsContent>
        <TabsContent value="b">CB</TabsContent>
      </Tabs>,
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole('tab', { name: 'B' }))
    expect(current).toBe('b')
    rerender(
      <Tabs value={current} onValueChange={onChange}>
        <TabsList>
          <TabsTrigger value="a">A</TabsTrigger>
          <TabsTrigger value="b">B</TabsTrigger>
        </TabsList>
        <TabsContent value="a">CA</TabsContent>
        <TabsContent value="b">CB</TabsContent>
      </Tabs>,
    )
    expect(screen.getByText('CB')).toBeInTheDocument()
  })
})
