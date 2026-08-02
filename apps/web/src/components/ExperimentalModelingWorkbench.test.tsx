import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../i18n'
import type { ExperimentalModelingCapabilities } from '../types'
import { ExperimentalModelingWorkbench } from './ExperimentalModelingWorkbench'

const mocks = vi.hoisted(() => ({
  saveCredential: vi.fn(),
}))

const capabilities: ExperimentalModelingCapabilities = {
  schema_version: 'catex.experimental-modeling-capabilities.v2',
  enabled: true,
  max_evidence_upload_bytes: 20 * 1024 * 1024,
  rule_planner: { available: true, external_api: false },
  providers: {
    project: { available: true, requires_key: false },
    optimade: { available: true, requires_key: false },
    materials_project: {
      available: false,
      client_installed: true,
      key_configured: false,
      credential_source: null,
      saved_to_system: false,
      requires_key: true,
      api_key_environment_variable: 'MP_API_KEY',
    },
  },
  gpt_planner: {
    available: false,
    key_configured: false,
    credential_source: null,
    saved_to_system: false,
    api_key_environment_variable: 'OPENAI_API_KEY',
    model: 'test-model',
    responses_api: true,
    stores_responses: false,
  },
  credential_store: {
    available: true,
    persistent: true,
    backend: 'keyring.backends.Windows.WinVaultKeyring',
    reason: null,
  },
  credentials_persisted: true,
}

vi.mock('../api', () => ({
  api: {
    experimentalModelingCapabilities: vi.fn(async () => capabilities),
    experimentalEvidence: vi.fn(async () => []),
    experimentalSpec: vi.fn(async () => null),
    experimentalCatalogs: vi.fn(async () => []),
    experimentalRuns: vi.fn(async () => []),
    saveExperimentalCredential: mocks.saveCredential,
  },
}))

describe('experimental credential editor', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.localStorage.setItem('catex.language.v1', 'en')
    mocks.saveCredential.mockReset()
    mocks.saveCredential.mockResolvedValue({
      schema_version: 'catex.credential-save.v1',
      provider: 'materials_project',
      saved_to_system: true,
      verified: true,
      verification: { database_version: '2026.07.31' },
      capabilities: {
        ...capabilities,
        providers: {
          ...capabilities.providers,
          materials_project: {
            ...capabilities.providers.materials_project,
            available: true,
            key_configured: true,
            credential_source: 'system_keyring',
            saved_to_system: true,
          },
        },
      },
    })
  })

  it('uses a password field, clears it on submit, and never writes browser storage', async () => {
    render(
      <I18nProvider>
        <ExperimentalModelingWorkbench
          artifacts={[]}
          onArtifactsChanged={vi.fn()}
          onMessage={vi.fn()}
          onOpenStructures={vi.fn()}
          projectId="project-1"
        />
      </I18nProvider>,
    )

    const input = await screen.findByLabelText('Materials Project API key')
    expect(input).toHaveAttribute('type', 'password')
    expect(input).toHaveAttribute('autocomplete', 'new-password')

    fireEvent.change(input, { target: { value: 'browser-memory-test-key' } })
    fireEvent.click(
      screen.getAllByRole('button', { name: 'Verify and save securely' })[0],
    )

    await waitFor(() =>
      expect(mocks.saveCredential).toHaveBeenCalledWith(
        'materials_project',
        'browser-memory-test-key',
      ),
    )
    expect(input).toHaveValue('')
    expect(JSON.stringify(window.localStorage)).not.toContain('browser-memory-test-key')
  })
})
