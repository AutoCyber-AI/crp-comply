import type { HumanInputItem } from '../../lib/api'

export interface InputRowProps {
  item: HumanInputItem
  value: string
  onChange: (value: string) => void
}

export function InputRow({ item, value, onChange }: InputRowProps) {
  const required = item.priority === 'high'
  return (
    <div className="px-4 py-3">
      <label className="block text-xs font-medium text-ink-2 mb-1" title={item.key}>
        {item.prompt}
        {required && (
          <span
            className="ml-1 text-danger font-bold"
            aria-label="required"
            title="Required - the recipe cannot run without this value"
          >
            *
          </span>
        )}
      </label>
      {item.rationale && (
        <p className="text-xs text-ink-3 mb-1.5 italic">{item.rationale}</p>
      )}
      {item.options && item.options.length > 0 ? (
        <select
          className="select text-sm"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-required={required}
        >
          <option value="">- choose -</option>
          {item.options.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      ) : (
        <input
          className="input text-sm"
          placeholder={item.examples?.[0] || ''}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-required={required}
        />
      )}
      {item.examples && item.examples.length > 0 && (
        <div className="text-xs text-ink-3 mt-1">e.g. {item.examples.slice(0, 2).join(', ')}</div>
      )}
    </div>
  )
}
