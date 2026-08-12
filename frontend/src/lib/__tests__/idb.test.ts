import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { getDraft, setDraft, deleteDraft } from '../idb'
import { installFakeIndexedDB } from '../../test/fakeIndexedDB'

describe('idb draft helpers', () => {
  beforeEach(() => {
    installFakeIndexedDB()
  })

  afterEach(() => {
    // @ts-expect-error remove fake
    delete window.indexedDB
  })

  it('returns null for a missing draft', async () => {
    const value = await getDraft('missing-key')
    expect(value).toBeNull()
  })

  it('sets and gets a draft', async () => {
    await setDraft('recipe:1', { system_name: 'Alpha' })
    const value = await getDraft('recipe:1')
    expect(value).toEqual({ system_name: 'Alpha' })
  })

  it('deletes a draft', async () => {
    await setDraft('recipe:2', { system_name: 'Beta' })
    await deleteDraft('recipe:2')
    const value = await getDraft('recipe:2')
    expect(value).toBeNull()
  })

  it('overwrites an existing draft', async () => {
    await setDraft('recipe:3', { system_name: 'Old' })
    await setDraft('recipe:3', { system_name: 'New' })
    const value = await getDraft('recipe:3')
    expect(value).toEqual({ system_name: 'New' })
  })

  it('rejects when IndexedDB is unavailable', async () => {
    // @ts-expect-error simulate private mode
    window.indexedDB = undefined
    await expect(getDraft('recipe:x')).rejects.toThrow('IndexedDB not available')
    await expect(setDraft('recipe:x', {})).rejects.toThrow('IndexedDB not available')
    await expect(deleteDraft('recipe:x')).rejects.toThrow('IndexedDB not available')
  })
})
