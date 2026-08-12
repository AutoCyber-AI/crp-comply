import { startAuthentication, startRegistration } from '@simplewebauthn/browser'

function isAbortError(err: any): boolean {
  return (
    err?.name === 'AbortError' ||
    /abort|cancelling/i.test(err?.message || '')
  )
}

function isAlreadyRegisteredError(err: any): boolean {
  return (
    err?.name === 'InvalidStateError' ||
    /already registered|previously registered|already in use/i.test(err?.message || '')
  )
}

async function fetchWithAuth(
  path: string,
  getToken: () => Promise<string | null>,
  options: RequestInit = {},
) {
  const token = await getToken()
  if (!token) throw new Error('Not authenticated')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }
  headers.Authorization = `Bearer ${token}`
  // The passkey MFA token is managed by the backend as an HttpOnly cookie;
  // do not read it from browser storage or send it as a header here.
  const res = await fetch(`/api/v1${path}`, { ...options, headers })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

export async function checkPasskeyStatus(getToken: () => Promise<string | null>) {
  return fetchWithAuth('/passkeys/status', getToken)
}

export async function registerPasskey(
  getToken: () => Promise<string | null>,
  deviceName = 'Primary device',
  displayName?: string,
): Promise<{ registered: boolean; alreadyRegistered?: boolean }> {
  const options = await fetchWithAuth('/passkeys/register-options', getToken, {
    method: 'POST',
    body: JSON.stringify({ device_name: deviceName, display_name: displayName }),
  })
  let credential
  try {
    credential = await startRegistration({ optionsJSON: options as any })
  } catch (err: any) {
    if (isAlreadyRegisteredError(err)) {
      return { registered: false, alreadyRegistered: true }
    }
    if (isAbortError(err)) {
      throw new Error('Passkey registration was cancelled.')
    }
    throw err
  }
  await fetchWithAuth('/passkeys/register', getToken, {
    method: 'POST',
    body: JSON.stringify({ credential, device_name: deviceName }),
  })
  return { registered: true }
}

export async function verifyPasskey(getToken: () => Promise<string | null>) {
  const options = await fetchWithAuth('/passkeys/auth-options', getToken, {
    method: 'POST',
  })
  let credential
  try {
    credential = await startAuthentication({ optionsJSON: options as any })
  } catch (err: any) {
    if (isAbortError(err)) {
      throw new Error('Passkey verification was cancelled.')
    }
    throw err
  }
  const result = (await fetchWithAuth('/passkeys/verify', getToken, {
    method: 'POST',
    body: JSON.stringify({ credential }),
  })) as {
    mfa_token: string
    expires_in: number
    risk_score: number
    risk_factors: string[]
  }
  // The backend sets the MFA token as an HttpOnly cookie; no browser
  // storage is needed.
  return result
}

export async function stepUpPasskey(getToken: () => Promise<string | null>) {
  const options = await fetchWithAuth('/passkeys/auth-options', getToken, {
    method: 'POST',
  })
  let credential
  try {
    credential = await startAuthentication({ optionsJSON: options as any })
  } catch (err: any) {
    if (isAbortError(err)) {
      throw new Error('Passkey verification was cancelled.')
    }
    throw err
  }
  return fetchWithAuth('/auth/step-up', getToken, {
    method: 'POST',
    body: JSON.stringify({ credential }),
  }) as Promise<{ status: string; elevated_until: number; risk_score: number; risk_factors: string[] }>
}

export async function listPasskeys(getToken: () => Promise<string | null>) {
  return fetchWithAuth('/passkeys', getToken)
}

export async function deletePasskey(
  getToken: () => Promise<string | null>,
  credentialId: string,
) {
  return fetchWithAuth(`/passkeys/${credentialId}`, getToken, {
    method: 'DELETE',
  })
}
