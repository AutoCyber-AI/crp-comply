import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  TableSkeleton,
  CardSkeleton,
  ChartSkeleton,
  ContentSkeleton,
  FormSkeleton,
} from '../index'

describe('Skeleton taxonomy', () => {
  it('TableSkeleton announces loading table data', () => {
    render(<TableSkeleton rows={3} columns={2} />)
    expect(screen.getByRole('status', { name: /Loading table/i })).toBeInTheDocument()
  })

  it('CardSkeleton announces loading cards', () => {
    render(<CardSkeleton count={2} />)
    expect(screen.getByRole('status', { name: /Loading cards/i })).toBeInTheDocument()
  })

  it('ChartSkeleton announces loading chart', () => {
    render(<ChartSkeleton />)
    expect(screen.getByRole('status', { name: /Loading chart/i })).toBeInTheDocument()
  })

  it('ContentSkeleton announces loading content', () => {
    render(<ContentSkeleton lines={4} />)
    expect(screen.getByRole('status', { name: /Loading content/i })).toBeInTheDocument()
  })

  it('FormSkeleton announces loading form', () => {
    render(<FormSkeleton fields={3} />)
    expect(screen.getByRole('status', { name: /Loading form/i })).toBeInTheDocument()
  })
})
