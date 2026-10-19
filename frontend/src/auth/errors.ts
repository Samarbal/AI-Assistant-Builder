export function authError(error: unknown): string {
  const e = error as { code?: string; status?: number; name?: string } | null
  if (e?.code === 'invalid_credentials') return 'Email or password is incorrect.'
  if (e?.code === 'email_not_confirmed') return 'Confirm your email before signing in.'
  if (e?.code === 'weak_password') return 'Choose a stronger password that meets the account security policy.'
  if (e?.code === 'signup_disabled') return 'Registration is currently unavailable.'
  if (e?.code === 'user_already_exists' || e?.code === 'email_exists') return 'Unable to create this account. Try signing in instead.'
  if (e?.status === 429 || e?.code?.startsWith('over_')) return 'Too many attempts. Please wait before trying again.'
  if (e?.name === 'AuthRetryableFetchError' || e?.name === 'TypeError') return 'Unable to reach authentication. Check your connection and try again.'
  return 'Authentication could not be completed. Please try again.'
}
