import { useState } from 'react'
import { Code, Copy, Check } from 'lucide-react'

export function IntegrationsPanel() {
  const [copied, setCopied] = useState<string | null>(null)
  const apiKey = 'crp_YOUR_API_KEY'

  const handleCopy = (id: string, text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(id)
    setTimeout(() => setCopied(null), 2000)
  }

  const snippets = [
    {
      id: 'openai',
      title: 'OpenAI SDK (Drop-in Replacement)',
      language: 'python',
      code: `from openai import OpenAI

client = OpenAI(
    base_url="https://comply.crprotocol.io/v1",
    api_key="${apiKey}",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello, world!"}],
)
print(response.choices[0].message.content)

# Compliance headers are in response headers:
# X-CRP-Comply: active
# X-CRP-Comply-Record-ID: <audit-record-id>
# X-CRP-Comply-Risk: MINIMAL | HIGH
# X-CRP-Comply-Hallucination-Risk: LOW | MEDIUM | HIGH | CRITICAL`,
    },
    {
      id: 'langchain',
      title: 'LangChain Integration',
      language: 'python',
      code: `from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="gpt-4o",
    base_url="https://comply.crprotocol.io/v1",
    api_key="${apiKey}",
)

response = llm.invoke("Explain GDPR Article 35")
print(response.content)`,
    },
    {
      id: 'curl',
      title: 'cURL',
      language: 'bash',
      code: `curl -X POST https://comply.crprotocol.io/v1/chat/completions \\
  -H "Authorization: Bearer ${apiKey}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
    },
    {
      id: 'byok',
      title: 'BYOK Mode (Bring Your Own Key)',
      language: 'bash',
      code: `curl -X POST https://comply.crprotocol.io/v1/chat/completions \\
  -H "X-Api-Key: ${apiKey}" \\
  -H "Authorization: Bearer sk-YOUR_OPENAI_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}]
  }'`,
    },
  ]

  return (
    <div className="card">
      <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <Code className="h-5 w-5" /> Integration Snippets
      </h2>
      <p className="text-sm text-gray-600 mb-4">
        CRP Comply works as a drop-in proxy - point any OpenAI-compatible SDK at your Comply endpoint.
      </p>
      <div className="space-y-4">
        {snippets.map((s) => (
          <div key={s.id} className="border rounded-lg overflow-hidden">
            <div className="flex items-center justify-between bg-gray-50 px-4 py-2">
              <span className="text-sm font-medium text-gray-700">{s.title}</span>
              <button
                type="button"
                onClick={() => handleCopy(s.id, s.code)}
                className="flex items-center gap-1 text-xs text-gray-600 hover:text-gray-800 transition-colors"
              >
                {copied === s.id ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Copy className="h-3.5 w-3.5" />}
                {copied === s.id ? 'Copied' : 'Copy'}
              </button>
            </div>
            <pre className="p-4 bg-gray-900 text-gray-100 text-xs overflow-x-auto">
              <code>{s.code}</code>
            </pre>
          </div>
        ))}
      </div>
    </div>
  )
}
