/**
 * Tiny promise-based IndexedDB helper for recipe input drafts.
 *
 * Keeps auto-saved workspace inputs out of ``localStorage`` so they survive
 * larger payloads and are not wiped by synchronous storage exceptions. When
 * IndexedDB is unavailable (e.g. private mode), helpers reject so callers can
 * fall back to memory-only state.
 */

const DB_NAME = 'crp-comply-drafts'
const DB_VERSION = 1
const STORE_NAME = 'drafts'

/**
 * Open the drafts database and ensure the object store exists.
 * Rejects when IndexedDB is unavailable.
 */
export function openDraftDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof window === 'undefined' || !window.indexedDB) {
      reject(new Error('IndexedDB not available'))
      return
    }

    const request = window.indexedDB.open(DB_NAME, DB_VERSION)

    request.onerror = () => reject(request.error ?? new Error('Failed to open IndexedDB'))
    request.onsuccess = () => resolve(request.result)

    request.onupgradeneeded = (event) => {
      const db = (event.target as IDBOpenDBRequest).result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'key' })
      }
    }
  })
}

function withStore(mode: IDBTransactionMode): Promise<IDBObjectStore> {
  return openDraftDB().then((db) => {
    const tx = db.transaction(STORE_NAME, mode)
    return tx.objectStore(STORE_NAME)
  })
}

function promisifyRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'))
    request.onsuccess = () => resolve(request.result)
  })
}

/**
 * Load a draft by key. Returns ``null`` when no draft exists.
 * Rejects when IndexedDB is unavailable.
 */
export async function getDraft(key: string): Promise<Record<string, string> | null> {
  const store = await withStore('readonly')
  const request = store.get(key)
  const row = await promisifyRequest<{ key: string; value: Record<string, string> } | undefined>(
    request as IDBRequest<{ key: string; value: Record<string, string> } | undefined>,
  )
  return row?.value ?? null
}

/**
 * Persist a draft under the given key.
 * Rejects when IndexedDB is unavailable.
 */
export async function setDraft(key: string, value: Record<string, string>): Promise<void> {
  const store = await withStore('readwrite')
  await promisifyRequest(store.put({ key, value }) as unknown as IDBRequest<void>)
}

/**
 * Remove a draft by key.
 * Rejects when IndexedDB is unavailable.
 */
export async function deleteDraft(key: string): Promise<void> {
  const store = await withStore('readwrite')
  await promisifyRequest(store.delete(key) as unknown as IDBRequest<void>)
}
