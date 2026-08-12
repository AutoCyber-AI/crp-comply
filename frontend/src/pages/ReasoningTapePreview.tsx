// Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
// Licensed under Elastic License 2.0 - see LICENSE.md for details.
//
// Visual preview / Storybook substitute for the ReasoningTape.
// Mounted at ``/app/dev/reasoning-tape``. Renders the canonical
// fixture set so designers can inspect every event renderer
// without spinning up the language-agent loop.

import { useState } from 'react'
import ReasoningTape from '@/components/ReasoningTape'
import {
  LOOP_EVENT_FIXTURES,
} from '@/components/reasoningTapeFixtures'
import type { LoopEvent } from '@/lib/loopEvents'

export default function ReasoningTapePreview() {
  const [events, setEvents] = useState<LoopEvent[]>(LOOP_EVENT_FIXTURES)

  return (
    <div className="mx-auto flex h-full max-w-5xl flex-col gap-4 p-4">
      <header>
        <h1 className="text-2xl font-semibold text-slate-900">
          Reasoning tape - fixture preview
        </h1>
        <p className="text-sm text-slate-600">
          Fixture-driven render of every typed loop event. Use ↑/↓ to
          move focus, Enter to expand, Esc to collapse. The tape itself
          never collapses.
        </p>
      </header>
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => setEvents([])}
          className="rounded border border-slate-300 bg-white px-3 py-1 text-sm hover:bg-slate-50"
        >
          Clear
        </button>
        <button
          type="button"
          onClick={() => setEvents(LOOP_EVENT_FIXTURES)}
          className="rounded border border-slate-300 bg-white px-3 py-1 text-sm hover:bg-slate-50"
        >
          Reset to fixtures
        </button>
        <button
          type="button"
          onClick={() =>
            setEvents((es) => [
              ...es,
              {
                event: 'loop.heartbeat',
                ts: Date.now() / 1000,
                run_id: 'fixture-run',
                state: 'streaming',
              },
            ])
          }
          className="rounded border border-slate-300 bg-white px-3 py-1 text-sm hover:bg-slate-50"
        >
          Append heartbeat
        </button>
      </div>
      <div className="min-h-[32rem] flex-1">
        <ReasoningTape events={events} />
      </div>
    </div>
  )
}
