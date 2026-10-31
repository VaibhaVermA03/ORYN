import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '@/auth/AuthContext'
import { ConfirmDialog } from '@/components/ui/Dialog'

/** "Do you want to sign out?" alert dialog shared by the header and the Settings page.
 *  The session is only ended after the user confirms; Cancel / Escape / clicking outside keeps them signed in. */
export function SignOutConfirm({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)

  const confirm = async () => {
    setBusy(true)
    try {
      await logout() // clears the local session even if the server call fails
    } finally {
      setBusy(false)
      onOpenChange(false)
    }
    navigate('/login', { replace: true })
  }

  return (
    <ConfirmDialog
      open={open}
      onOpenChange={(o) => {
        if (!busy) onOpenChange(o)
      }}
      title="Sign out of ORYN?"
      description="Do you want to sign out? You will need to sign in again to get back to your workspaces."
      confirmLabel="Sign out"
      destructive={false}
      loading={busy}
      onConfirm={confirm}
    />
  )
}