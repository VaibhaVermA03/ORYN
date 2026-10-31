import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { App } from '@/App'
import { WORKSPACE, json, mockApi, renderApp, signedInRoutes } from './helpers'

const SECOND = { ...WORKSPACE, id: 'w2', name: 'A very long workspace name that cannot possibly fit inside the narrow header container' }
const routes = () =>
  signedInRoutes({
    'GET /workspaces': () => json([WORKSPACE, SECOND]),
    'GET /workspaces/w1/documents': () => json({ items: [], total: 0, page: 1, page_size: 25 }),
    'GET /workspaces/w2/documents': () => json({ items: [], total: 0, page: 1, page_size: 25 }),
    'GET /workspaces/w1/members': () => json([]),
    'GET /workspaces/w2/members': () => json([]),
  })

afterEach(() => document.documentElement.removeAttribute('data-theme'))

describe('workspace dropdown', () => {
  it('lists workspaces with full names, marks the current one, and switches on click', async () => {
    mockApi(routes())
    renderApp(<App />, '/app/knowledge')
    const trigger = await screen.findByRole('button', { name: /Workspace: Acme/ })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(trigger)
    const list = await screen.findByRole('listbox', { name: 'Workspaces' })
    const options = within(list).getAllByRole('option')
    expect(options).toHaveLength(2)
    expect(options[0]).toHaveAttribute('aria-selected', 'true')
    expect(within(list).getByText(SECOND.name)).toBeInTheDocument() // full name, not cut
    await userEvent.click(options[1]!)
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Workspace: A very long/ })).toBeInTheDocument()
    expect(localStorage.getItem('oryn-workspace')).toBe('w2')
  })

  it('supports the keyboard: arrows, Enter to select, Escape to close', async () => {
    mockApi(routes())
    renderApp(<App />, '/app/knowledge')
    const trigger = await screen.findByRole('button', { name: /Workspace: Acme/ })
    trigger.focus()
    await userEvent.keyboard('{ArrowDown}')
    const list = await screen.findByRole('listbox')
    await waitFor(() => expect(list).toHaveFocus())
    await userEvent.keyboard('{ArrowDown}{Enter}')
    expect(await screen.findByRole('button', { name: /Workspace: A very long/ })).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}')
    await screen.findByRole('listbox')
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Workspace: A very long/ })).toHaveFocus()
  })

  it('closes when clicking outside', async () => {
    mockApi(routes())
    renderApp(<App />, '/app/knowledge')
    await userEvent.click(await screen.findByRole('button', { name: /Workspace: Acme/ }))
    await screen.findByRole('listbox')
    await userEvent.click(document.body)
    await waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument())
  })

  it('"Create new workspace" opens Settings at the create section', async () => {
    mockApi(routes())
    renderApp(<App />, '/app/knowledge')
    await userEvent.click(await screen.findByRole('button', { name: /Workspace: Acme/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Create new workspace' }))
    expect(await screen.findByRole('heading', { name: 'Create a workspace' })).toBeInTheDocument()
    expect(document.getElementById('create-workspace')).toContainElement(screen.getByRole('heading', { name: 'Create a workspace' }))
    await waitFor(() => expect(document.getElementById('create-workspace')!.querySelector('input')).toHaveFocus())
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })
})

describe('sidebar', () => {
  it('collapses and expands on desktop and remembers the choice', async () => {
    mockApi(routes())
    renderApp(<App />, '/app/knowledge')
    const collapse = await screen.findByRole('button', { name: 'Collapse sidebar' })
    const sidebar = document.getElementById('app-sidebar')!
    expect(sidebar).not.toHaveAttribute('inert')
    expect(collapse).toHaveAttribute('aria-expanded', 'true')
    await userEvent.click(collapse)
    expect(sidebar).toHaveAttribute('inert')
    expect(sidebar.className).toContain('w-0')
    expect(localStorage.getItem('oryn-sidebar')).toBe('collapsed')
    await userEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }))
    expect(sidebar).not.toHaveAttribute('inert')
    expect(sidebar.className).toContain('w-60')
    expect(localStorage.getItem('oryn-sidebar')).toBe('open')
  })

  it('starts collapsed when that was the saved choice', async () => {
    localStorage.setItem('oryn-sidebar', 'collapsed')
    mockApi(routes())
    renderApp(<App />, '/app/knowledge')
    expect(await screen.findByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })

  it('phone drawer: opens, traps focus on its close button, closes with Escape and returns focus', async () => {
    mockApi(routes())
    renderApp(<App />, '/app/knowledge')
    const menu = await screen.findByRole('button', { name: 'Open navigation menu' })
    const drawer = document.getElementById('mobile-nav')!
    expect(drawer).toHaveAttribute('inert')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await userEvent.click(menu)
    const dialog = await screen.findByRole('dialog', { name: 'Navigation menu' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(drawer).not.toHaveAttribute('inert')
    expect(drawer.className).toContain('visible')
    await waitFor(() => expect(within(dialog).getAllByRole('button', { name: 'Close navigation menu' })[1]).toHaveFocus())
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(drawer).toHaveAttribute('inert'))
    expect(drawer.className).toContain('invisible')
    expect(menu).toHaveFocus()
  })

  it('phone drawer closes after choosing a page', async () => {
    mockApi(routes())
    renderApp(<App />, '/app/knowledge')
    await userEvent.click(await screen.findByRole('button', { name: 'Open navigation menu' }))
    const nav = await screen.findByRole('navigation', { name: 'Mobile navigation' })
    await userEvent.click(within(nav).getByRole('link', { name: 'Settings' }))
    await waitFor(() => expect(document.getElementById('mobile-nav')).toHaveAttribute('inert'))
    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument()
  })
})

describe('theme toggle', () => {
  it('switches theme, stores it, and the hover hint always names the action it will perform', async () => {
    mockApi(routes())
    renderApp(<App />, '/app/knowledge')
    const btn = await screen.findByRole('button', { name: 'Switch to dark mode' })
    expect(btn.parentElement).toHaveTextContent('Switch to dark mode')
    await userEvent.click(btn)
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    expect(localStorage.getItem('oryn-theme')).toBe('dark')
    const back = await screen.findByRole('button', { name: 'Switch to light mode' })
    expect(back.parentElement).toHaveTextContent('Switch to light mode')
    await userEvent.click(back)
    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
  })
})