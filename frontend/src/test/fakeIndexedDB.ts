/**
 * Minimal in-memory fake of the IndexedDB API for tests.
 *
 * Supports the open → transaction → object-store flow used by
 * ``src/lib/idb.ts`` without external dependencies.
 */

interface ListenerEntry {
  type: string
  listener: EventListener
}

class FakeEventTarget {
  private listeners: ListenerEntry[] = []
  onsuccess: ((this: IDBRequest, ev: Event) => unknown) | null = null
  onerror: ((this: IDBRequest, ev: Event) => unknown) | null = null
  onupgradeneeded: ((this: IDBOpenDBRequest, ev: IDBVersionChangeEvent) => unknown) | null = null

  addEventListener(type: string, listener: EventListener) {
    this.listeners.push({ type, listener })
  }

  removeEventListener(type: string, listener: EventListener) {
    this.listeners = this.listeners.filter(
      (entry) => entry.type !== type || entry.listener !== listener,
    )
  }

  dispatchEvent(event: Event): boolean {
    if (event.type === 'success' && this.onsuccess) {
      this.onsuccess.call(this as unknown as IDBRequest, event)
    } else if (event.type === 'error' && this.onerror) {
      this.onerror.call(this as unknown as IDBRequest, event)
    } else if (event.type === 'upgradeneeded' && this.onupgradeneeded) {
      this.onupgradeneeded.call(this as unknown as IDBOpenDBRequest, event as IDBVersionChangeEvent)
    }
    this.listeners
      .filter((entry) => entry.type === event.type)
      .forEach((entry) => {
        if (typeof entry.listener === 'function') {
          entry.listener(event)
        } else {
          ;(entry.listener as EventListenerObject).handleEvent(event)
        }
      })
    return true
  }
}

class FakeIDBRequest<T> extends FakeEventTarget {
  error: DOMException | null = null
  result: T
  source: IDBObjectStore | null = null
  readyState: IDBRequestReadyState = 'pending'
  transaction: IDBTransaction | null = null

  constructor(result: T) {
    super()
    this.result = result
  }

  dispatchSuccess() {
    this.readyState = 'done'
    this.dispatchEvent(new Event('success'))
  }

  dispatchError(message: string) {
    this.readyState = 'done'
    this.error = new DOMException(message)
    this.dispatchEvent(new Event('error'))
  }
}

class FakeIDBObjectStore {
  private db: FakeIDBDatabase
  readonly name = 'drafts'

  constructor(db: FakeIDBDatabase) {
    this.db = db
  }

  get(key: string): IDBRequest {
    const row = this.db.data.get(key)
    const req = new FakeIDBRequest(row ? { key, value: row } : undefined)
    queueMicrotask(() => req.dispatchSuccess())
    return req as unknown as IDBRequest
  }

  put(value: { key: string; value: Record<string, string> }): IDBRequest {
    const req = new FakeIDBRequest(undefined)
    queueMicrotask(() => {
      this.db.data.set(value.key, value.value)
      req.dispatchSuccess()
    })
    return req as unknown as IDBRequest
  }

  delete(key: string): IDBRequest {
    const req = new FakeIDBRequest(undefined)
    queueMicrotask(() => {
      this.db.data.delete(key)
      req.dispatchSuccess()
    })
    return req as unknown as IDBRequest
  }
}

class FakeIDBTransaction extends FakeEventTarget {
  readonly db: IDBDatabase
  private store: FakeIDBObjectStore

  constructor(db: IDBDatabase, store: FakeIDBObjectStore) {
    super()
    this.db = db
    this.store = store
  }

  objectStore(_name: string): IDBObjectStore {
    return this.store as unknown as IDBObjectStore
  }
}

class FakeIDBDatabase extends FakeEventTarget {
  private store: FakeIDBObjectStore
  private tx: FakeIDBTransaction
  data = new Map<string, Record<string, string>>()
  readonly name = 'crp-comply-drafts'
  readonly version = 1

  constructor() {
    super()
    this.store = new FakeIDBObjectStore(this)
    this.tx = new FakeIDBTransaction(this as unknown as IDBDatabase, this.store)
  }

  get objectStoreNames(): DOMStringList {
    const list = { length: 1, 0: 'drafts', contains: (n: string) => n === 'drafts' }
    return list as unknown as DOMStringList
  }

  transaction(_storeNames: string | string[], _mode?: IDBTransactionMode): IDBTransaction {
    return this.tx as unknown as IDBTransaction
  }

  createObjectStore(_name: string, _options?: IDBObjectStoreParameters): IDBObjectStore {
    return this.store as unknown as IDBObjectStore
  }
}

class FakeIDBOpenDBRequest extends FakeIDBRequest<IDBDatabase> {
  dispatchUpgradeNeeded(oldVersion: number, newVersion: number) {
    const event = new Event('upgradeneeded') as unknown as IDBVersionChangeEvent
    Object.defineProperty(event, 'oldVersion', { value: oldVersion })
    Object.defineProperty(event, 'newVersion', { value: newVersion })
    Object.defineProperty(event, 'target', { value: this })
    this.dispatchEvent(event)
  }
}

export type { FakeIDBDatabase }

export function installFakeIndexedDB(): FakeIDBDatabase {
  const fakeDB = new FakeIDBDatabase()
  const open = (_name: string, _version?: number): IDBOpenDBRequest => {
    const req = new FakeIDBOpenDBRequest(fakeDB as unknown as IDBDatabase)
    queueMicrotask(() => {
      req.dispatchUpgradeNeeded(0, 1)
      req.dispatchSuccess()
    })
    return req as unknown as IDBOpenDBRequest
  }
  Object.defineProperty(window, 'indexedDB', {
    value: { open },
    configurable: true,
    writable: true,
  })
  return fakeDB
}
