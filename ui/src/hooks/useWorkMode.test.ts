import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWorkMode, WORK_MODE_KEY } from './useWorkMode'

describe('useWorkMode', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => localStorage.clear())

  it('defaults off and toggles, persisting to localStorage', () => {
    const { result } = renderHook(() => useWorkMode())
    expect(result.current.workMode).toBe(false)
    act(() => result.current.setWorkMode(true))
    expect(result.current.workMode).toBe(true)
    expect(localStorage.getItem(WORK_MODE_KEY)).toBe('true')
  })

  it('initializes from a pre-existing localStorage value', () => {
    localStorage.setItem(WORK_MODE_KEY, 'true')
    const { result } = renderHook(() => useWorkMode())
    expect(result.current.workMode).toBe(true)
  })

  it('syncs across tabs via the storage event', () => {
    const { result } = renderHook(() => useWorkMode())
    expect(result.current.workMode).toBe(false)
    act(() => {
      localStorage.setItem(WORK_MODE_KEY, 'true')
      window.dispatchEvent(
        new StorageEvent('storage', {
          key: WORK_MODE_KEY,
          newValue: 'true',
        }),
      )
    })
    expect(result.current.workMode).toBe(true)
  })
})
