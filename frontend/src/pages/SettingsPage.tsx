import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { useLocation } from 'react-router-dom'
import { z } from 'zod'
import { useAuth } from '@/auth/AuthContext'
import { SignOutConfirm } from '@/components/layout/SignOutConfirm'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Field'
import { Alert, Badge, Card, ErrorState, PageHeader, Skeleton } from '@/components/ui/feedback'
import { useToast } from '@/components/ui/Toast'
import { API_PREFIX, api, errorMessage } from '@/lib/api'
import { keys, useMembersQuery } from '@/lib/queries'
import type { Member, User, Workspace } from '@/lib/types'
import { formatDateTime } from '@/lib/utils'
import { useWorkspace } from '@/workspace/WorkspaceContext'

const nameSchema = z.object({ name: z.string().trim().min(1, 'Enter a name').max(120, 'At most 120 characters') })
const wsSchema = z.object({ name: z.string().trim().min(1, 'Enter a name').max(120), description: z.string().max(500, 'At most 500 characters').optional() })
const memberSchema = z.object({ email: z.string().trim().min(1, 'Enter an email').pipe(z.email('Enter a valid email address')), role: z.enum(['member', 'admin']) })

function ProfileCard() {
  const { user, setUser } = useAuth()
  const toast = useToast()
  const { register, handleSubmit, formState: { errors } } = useForm<z.infer<typeof nameSchema>>({
    resolver: zodResolver(nameSchema),
    defaultValues: { name: user?.display_name ?? '' },
  })
  const save = useMutation({
    mutationFn: (name: string) => api.patch<User>('/users/me', { display_name: name }),
    onSuccess: (u) => {
      setUser(u)
      toast.success('Profile updated.')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const [linkError, setLinkError] = useState<string | null>(null)
  const link = async () => {
    setLinkError(null)
    try {
      const { link_token } = await api.post<{ link_token: string }>('/auth/google/link-intent')
      window.location.href = `${API_PREFIX}/auth/google/login?link_token=${encodeURIComponent(link_token)}`
    } catch (e) {
      setLinkError(errorMessage(e, 'Google sign-in is not available.'))
    }
  }
  return (
    <Card className="space-y-4 p-5">
      <h2 className="text-sm font-semibold">Profile</h2>
      <form onSubmit={handleSubmit((v) => save.mutate(v.name))} noValidate className="max-w-sm space-y-3">
        <Input label="Display name" error={errors.name?.message} {...register('name')} />
        <p className="text-xs text-muted">Email: {user?.email}{user?.email_verified ? ' (verified)' : ''}</p>
        <Button type="submit" variant="primary" loading={save.isPending}>Save</Button>
      </form>
      <div className="border-t border-line pt-4">
        <p className="text-sm font-medium">Google sign-in</p>
        {user?.google_linked ? (
          <p className="mt-1 text-sm text-muted">A Google account is linked to this profile.</p>
        ) : (
          <div className="mt-1 space-y-2">
            <p className="text-sm text-muted">Link a Google account to sign in without a password.</p>
            {linkError && <Alert tone="danger">{linkError}</Alert>}
            <Button onClick={() => void link()}>Link Google account</Button>
          </div>
        )}
      </div>
    </Card>
  )
}

function WorkspaceCard({ workspace, canManage }: { workspace: Workspace; canManage: boolean }) {
  const qc = useQueryClient()
  const toast = useToast()
  const { register, handleSubmit, formState: { errors, isDirty } } = useForm<z.infer<typeof wsSchema>>({
    resolver: zodResolver(wsSchema),
    defaultValues: { name: workspace.name, description: workspace.description ?? '' },
  })
  const save = useMutation({
    mutationFn: (v: z.infer<typeof wsSchema>) => api.patch(`/workspaces/${workspace.id}`, { name: v.name, description: v.description || null }),
    onSuccess: () => {
      toast.success('Workspace updated.')
      void qc.invalidateQueries({ queryKey: keys.workspaces })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Card className="p-5">
      <h2 className="mb-3 text-sm font-semibold">Workspace</h2>
      <form onSubmit={handleSubmit((v) => save.mutate(v))} noValidate className="max-w-sm space-y-3">
        <Input label="Name" disabled={!canManage} error={errors.name?.message} {...register('name')} />
        <Input label="Description" disabled={!canManage} error={errors.description?.message} {...register('description')} />
        <p className="text-xs text-muted">Your role: {workspace.role}. Created {formatDateTime(workspace.created_at)}.</p>
        {canManage && <Button type="submit" variant="primary" loading={save.isPending} disabled={!isDirty}>Save</Button>}
      </form>
    </Card>
  )
}

function Members({ workspace, canManage }: { workspace: Workspace; canManage: boolean }) {
  const { user } = useAuth()
  const members = useMembersQuery(workspace.id)
  const qc = useQueryClient()
  const toast = useToast()
  const [removing, setRemoving] = useState<Member | null>(null)
  const refresh = () => void qc.invalidateQueries({ queryKey: keys.members(workspace.id) })
  const { register, handleSubmit, reset, formState: { errors } } = useForm<z.infer<typeof memberSchema>>({
    resolver: zodResolver(memberSchema),
    defaultValues: { email: '', role: 'member' },
  })
  const add = useMutation({
    mutationFn: (v: z.infer<typeof memberSchema>) => api.post(`/workspaces/${workspace.id}/members`, v),
    onSuccess: () => {
      toast.success('Member added.')
      reset()
      refresh()
    },
    onError: (e) => toast.error(errorMessage(e, 'Could not add that member. They must already have an ORYN account.')),
  })
  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: 'admin' | 'member' }) => api.patch(`/workspaces/${workspace.id}/members/${id}`, { role }),
    onSuccess: refresh,
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/workspaces/${workspace.id}/members/${id}`),
    onSuccess: () => {
      setRemoving(null)
      refresh()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Card className="p-5">
      <h2 className="mb-3 text-sm font-semibold">Members</h2>
      {members.isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : members.error ? (
        <ErrorState message={errorMessage(members.error)} onRetry={() => void members.refetch()} />
      ) : (
        <ul className="divide-y divide-line">
          {members.data?.map((m) => (
            <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
              <span className="min-w-0">
                <span className="block truncate font-medium">{m.display_name}{m.user_id === user?.id ? ' (you)' : ''}</span>
                <span className="block truncate text-xs text-muted">{m.email}</span>
              </span>
              <span className="flex items-center gap-2">
                {canManage && m.role !== 'owner' ? (
                  <>
                    <select
                      aria-label={`Role for ${m.display_name}`}
                      value={m.role}
                      onChange={(e) => setRole.mutate({ id: m.user_id, role: e.target.value as 'admin' | 'member' })}
                      className="h-8 rounded-lg border border-line bg-surface px-2 text-[13px]"
                    >
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </select>
                    <Button size="sm" onClick={() => setRemoving(m)} aria-label={`Remove ${m.display_name}`}>Remove</Button>
                  </>
                ) : (
                  <Badge tone={m.role === 'owner' ? 'accent' : 'neutral'}>{m.role}</Badge>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {canManage && (
        <form onSubmit={handleSubmit((v) => add.mutate(v))} noValidate className="mt-4 flex flex-wrap items-start gap-2 border-t border-line pt-4">
          <div className="min-w-56 flex-1">
            <Input label="Add member by email" type="email" error={errors.email?.message} {...register('email')} />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="new-role" className="block text-[13px] font-medium">Role</label>
            <select id="new-role" className="h-10 rounded-lg border border-line bg-surface px-3 text-sm" {...register('role')}>
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <Button type="submit" variant="primary" loading={add.isPending} className="mt-6">Add</Button>
        </form>
      )}
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(o) => !o && setRemoving(null)}
        title="Remove this member?"
        description={`${removing?.display_name ?? 'They'} will lose access to this workspace. Their conversations stay private to them.`}
        confirmLabel="Remove"
        loading={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing.user_id)
        }}
      />
    </Card>
  )
}

function CreateWorkspace() {
  const qc = useQueryClient()
  const toast = useToast()
  const { select } = useWorkspace()
  const { register, handleSubmit, reset, formState: { errors } } = useForm<z.infer<typeof wsSchema>>({ resolver: zodResolver(wsSchema) })
  const create = useMutation({
    mutationFn: (v: z.infer<typeof wsSchema>) => api.post<Workspace>('/workspaces', { name: v.name, description: v.description || null }),
    onSuccess: async (w) => {
      await qc.invalidateQueries({ queryKey: keys.workspaces })
      select(w.id)
      reset()
      toast.success('Workspace created.')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Card className="p-5">
      <h2 className="mb-3 text-sm font-semibold">Create a workspace</h2>
      <form onSubmit={handleSubmit((v) => create.mutate(v))} noValidate className="max-w-sm space-y-3">
        <Input label="Name" error={errors.name?.message} {...register('name')} />
        <Input label="Description (optional)" error={errors.description?.message} {...register('description')} />
        <Button type="submit" variant="primary" loading={create.isPending}>Create workspace</Button>
      </form>
    </Card>
  )
}

function DangerZone({ workspace }: { workspace: Workspace }) {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const toast = useToast()
  const del = useMutation({
    mutationFn: () => api.del(`/workspaces/${workspace.id}`),
    onSuccess: async () => {
      setOpen(false)
      await qc.invalidateQueries({ queryKey: keys.workspaces })
      toast.success('Workspace deleted.')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Card className="border-danger/30 p-5">
      <h2 className="text-sm font-semibold text-danger">Delete workspace</h2>
      <p className="mt-1 text-sm text-muted">Permanently removes this workspace, its documents, indexed content and conversations.</p>
      <Button variant="danger" className="mt-3" onClick={() => setOpen(true)}>Delete workspace</Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Delete "${workspace.name}"?`}
        description="This cannot be undone."
        confirmLabel="Delete workspace"
        loading={del.isPending}
        onConfirm={() => del.mutate()}
      />
    </Card>
  )
}

export function SettingsPage() {
  const { workspace, canManage } = useWorkspace()
  const [signOutOpen, setSignOutOpen] = useState(false)
  const location = useLocation()
  // Same query as the Members card (shared cache, no extra request). We wait for it to settle before
  // scrolling, because the member list changes the height of everything above "Create a workspace".
  const members = useMembersQuery(workspace?.id)
  const membersSettling = members.isLoading

  // "Create new workspace" in the header links to /app/settings#create-workspace: scroll there and focus the name field.
  useEffect(() => {
    if (location.hash !== '#create-workspace' || membersSettling) return
    const el = document.getElementById('create-workspace')
    if (!el) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
    el.querySelector<HTMLInputElement>('input')?.focus({ preventScroll: true })
  }, [location.key, location.hash, membersSettling])

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-4 sm:p-6">
      <PageHeader title="Settings" description="Your profile and workspaces." />
      <ProfileCard />
      {workspace && <WorkspaceCard key={workspace.id} workspace={workspace} canManage={canManage} />}
      {workspace && <Members key={`m-${workspace.id}`} workspace={workspace} canManage={canManage} />}
      <div id="create-workspace" className="scroll-mt-4">
        <CreateWorkspace />
      </div>
      {workspace?.role === 'owner' && <DangerZone workspace={workspace} />}
      <Button onClick={() => setSignOutOpen(true)}>Sign out</Button>
      <SignOutConfirm open={signOutOpen} onOpenChange={setSignOutOpen} />
    </div>
  )
}