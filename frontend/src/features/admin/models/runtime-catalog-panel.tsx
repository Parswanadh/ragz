import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Plus, RefreshCw } from 'lucide-react';
import { useState } from 'react';

import type { ModelOut } from '@/api/types';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { QueryError } from '@/components/ui/query-error';
import { NativeSelect } from '@/components/ui/select';
import { Spinner } from '@/components/ui/spinner';
import { StatusPill } from '@/components/ui/status-pill';

import {
  agentRequest,
  type RuntimeModel,
  type RuntimeProvider,
  useRuntimeModels,
  useRuntimeProviders,
} from './agent-api';
import { ModelFormDialog } from './model-form-dialog';
import { ProviderIcon } from './provider-icon';

const PINNED = [
  'openai',
  'chatgpt',
  'anthropic',
  'gemini',
  'xai',
  'groq',
  'deepseek',
  'mistral',
  'openrouter',
  'ollama',
];
const rank = (id: string) => {
  const i = PINNED.indexOf(id);
  return i < 0 ? PINNED.length : i;
};

export function RuntimeCatalogPanel({ registered }: { registered: ModelOut[] }) {
  const providers = useRuntimeProviders();
  const client = useQueryClient();
  const refresh = useMutation({
    mutationFn: () => agentRequest('/admin/models/catalog/refresh', 'POST'),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['agent-catalog'] }),
        client.invalidateQueries({ queryKey: ['admin-models-catalog'] }),
      ]);
    },
  });
  const [search, setSearch] = useState('');
  const [visible, setVisible] = useState(24);
  const [selected, setSelected] = useState<RuntimeProvider | null>(null);
  const [target, setTarget] = useState<{
    provider: RuntimeProvider;
    model?: RuntimeModel;
    modality: 'chat' | 'embedding';
  } | null>(null);
  const filtered = (providers.data?.providers ?? [])
    .filter((p) => `${p.name} ${p.id}`.toLowerCase().includes(search.trim().toLowerCase()))
    .sort((a, b) => rank(a.id) - rank(b.id));
  return (
    <section aria-labelledby="provider-catalog-heading" className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-2xl">
          <h2 id="provider-catalog-heading" className="text-base font-semibold text-ink">
            Providers
          </h2>
          <p className="text-sm text-secondary">
            Read from LiteLLM itself. Pick a provider to see its models, context windows, prices and
            tool support.
          </p>
        </div>
        <Button
          size="sm"
          disabled={providers.isFetching || refresh.isPending}
          onClick={() => refresh.mutate()}
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />{' '}
          {refresh.isPending ? 'Reloading…' : 'Reload catalog'}
        </Button>
      </div>
      {providers.data ? (
        <p className="text-xs text-muted">LiteLLM {providers.data.litellm_version}</p>
      ) : null}
      {providers.isPending ? <Spinner label="Loading providers…" /> : null}
      {refresh.isError ? (
        <p role="alert" className="text-sm text-danger">
          {refresh.error.message}
        </p>
      ) : null}
      {providers.isError ? (
        <QueryError error={providers.error} onRetry={() => providers.refetch()} />
      ) : null}
      {providers.data?.available === false ? (
        <p role="status" className="rounded-lg border border-line p-4 text-sm text-secondary">
          The runtime catalog is unavailable. Use Add model to register a model by name.
        </p>
      ) : null}
      {selected ? (
        <ProviderDetail
          key={selected.id}
          provider={selected}
          registered={registered}
          onBack={() => setSelected(null)}
          onAdd={(model, modality) => setTarget({ provider: selected, model, modality })}
        />
      ) : providers.data?.available ? (
        <>
          <Input
            type="search"
            aria-label="Search providers"
            placeholder="Search providers"
            autoComplete="off"
            className="max-w-sm"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setVisible(24);
            }}
          />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filtered.slice(0, visible).map((provider) => {
              const owned = registered.filter(
                (m) =>
                  m.provider_kind === provider.provider_kind &&
                  (provider.provider_kind !== 'litellm' ||
                    m.litellm_model_name.startsWith(`${provider.id}/`)),
              );
              return (
                <button
                  key={provider.id}
                  type="button"
                  onClick={() => setSelected(provider)}
                  className="flex w-full flex-col items-start gap-2 rounded-lg border border-line bg-bg p-3 text-left transition-colors hover:bg-subtle focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                >
                  <div className="flex w-full items-start justify-between gap-2">
                    <ProviderIcon provider={provider} />
                    {owned.length ? (
                      <StatusPill tone="muted">{owned.length} added</StatusPill>
                    ) : null}
                  </div>
                  <span className="text-sm font-medium text-ink">{provider.name}</span>
                  <div className="flex flex-wrap gap-1">
                    <StatusPill tone="muted">{provider.model_count} models</StatusPill>
                    {provider.supported === false ? (
                      <StatusPill tone="muted">Not supported</StatusPill>
                    ) : provider.auth_mode === 'subscription' ? (
                      <StatusPill tone="accent">ChatGPT plan</StatusPill>
                    ) : !provider.needs_key ? (
                      <StatusPill tone="muted">no key needed</StatusPill>
                    ) : owned.some((m) => m.key_fingerprint) ? (
                      <StatusPill tone="muted">key stored</StatusPill>
                    ) : null}
                    {provider.needs_base_url ? (
                      <StatusPill tone="muted">needs a URL</StatusPill>
                    ) : null}
                  </div>
                </button>
              );
            })}
          </div>
          {!filtered.length ? (
            <p className="py-4 text-sm text-secondary">No provider matches that search.</p>
          ) : null}
          <div className="flex items-center gap-3">
            <p className="text-xs text-muted">
              Showing {Math.min(visible, filtered.length)} of {filtered.length} providers.
            </p>
            {visible < filtered.length ? (
              <Button size="sm" onClick={() => setVisible((n) => n + 24)}>
                Show more providers
              </Button>
            ) : null}
          </div>
        </>
      ) : null}
      {target ? (
        <ModelFormDialog open onOpenChange={(open) => !open && setTarget(null)} preset={target} />
      ) : null}
    </section>
  );
}

function ProviderDetail({
  provider,
  registered,
  onBack,
  onAdd,
}: {
  provider: RuntimeProvider;
  registered: ModelOut[];
  onBack: () => void;
  onAdd: (model: RuntimeModel | undefined, mode: 'chat' | 'embedding') => void;
}) {
  const [search, setSearch] = useState('');
  const [mode, setMode] = useState<'chat' | 'embedding'>('chat');
  const [toolsOnly, setToolsOnly] = useState(false);
  const [visible, setVisible] = useState(40);
  const models = useRuntimeModels(provider.id, mode);
  const filtered = (models.data?.models ?? []).filter(
    (m) =>
      `${m.name} ${m.display_name}`.toLowerCase().includes(search.trim().toLowerCase()) &&
      (!toolsOnly || m.supports_function_calling === true),
  );
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" aria-hidden />
          All providers
        </Button>
        <ProviderIcon provider={provider} />
        <div>
          <h3 className="text-sm font-semibold text-ink">{provider.name}</h3>
          <p className="text-xs text-muted">
            {provider.supported === false
              ? 'Registration unavailable on this instance'
              : provider.auth_mode === 'subscription'
                ? 'Signed in with your ChatGPT plan'
                : provider.needs_key
                  ? 'Add a model to enter its API key'
                  : 'No API key needed'}
          </p>
        </div>
        <Button
          size="sm"
          className="ml-auto"
          disabled={provider.supported === false}
          onClick={() => onAdd(undefined, mode)}
        >
          <Plus className="h-3.5 w-3.5" aria-hidden />
          Model not listed
        </Button>
      </div>
      {provider.configuration_note ? (
        <p
          role="status"
          className="rounded-lg border border-line bg-subtle p-3 text-sm text-secondary"
        >
          {provider.configuration_note}
        </p>
      ) : null}
      {provider.auth_mode === 'subscription' ? (
        <p className="rounded-lg border border-line bg-subtle p-3 text-sm text-secondary">
          Models added here use your ChatGPT plan and keep the{' '}
          <span className="font-mono">chatgpt/</span> prefix. Connect above, then test a model to
          check availability on your account.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <Input
          type="search"
          aria-label="Search models from this provider"
          placeholder="Search models"
          className="min-w-48 flex-1"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setVisible(40);
          }}
        />
        <NativeSelect
          aria-label="Catalog model type"
          className="h-8 w-auto"
          value={mode}
          onChange={(e) => {
            setMode(e.target.value as 'chat' | 'embedding');
            setVisible(40);
            setToolsOnly(false);
          }}
        >
          <option value="chat">Chat models</option>
          <option value="embedding">Embedding models</option>
        </NativeSelect>
        {mode === 'chat' ? (
          <label className="flex items-center gap-2 text-sm text-secondary">
            <input
              type="checkbox"
              checked={toolsOnly}
              onChange={(e) => setToolsOnly(e.target.checked)}
            />
            Only models that can call tools
          </label>
        ) : null}
      </div>
      {models.isPending ? <Spinner label="Loading catalog models…" /> : null}
      {models.isError ? <QueryError error={models.error} onRetry={() => models.refetch()} /> : null}
      <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
        {filtered.slice(0, visible).map((model) => {
          const added =
            model.registered || registered.some((m) => m.litellm_model_name === model.name);
          return (
            <li
              key={model.id}
              className="flex flex-wrap items-center justify-between gap-3 px-3 py-3"
            >
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-ink">{model.display_name}</span>
                  {model.billing_mode === 'subscription' ? (
                    <StatusPill tone="accent">ChatGPT plan</StatusPill>
                  ) : null}
                  {model.supports_function_calling === true ? (
                    <StatusPill tone="muted">tools</StatusPill>
                  ) : model.supports_function_calling === false && mode === 'chat' ? (
                    <StatusPill tone="muted">no native tools</StatusPill>
                  ) : null}
                  {model.supports_reasoning ? (
                    <StatusPill tone="muted">reasoning</StatusPill>
                  ) : null}
                  {model.supports_vision ? <StatusPill tone="muted">vision</StatusPill> : null}
                </div>
                <p className="break-all font-mono text-xs text-muted">{model.name}</p>
                <p className="text-xs text-muted">
                  {model.max_input_tokens
                    ? `${Math.round(model.max_input_tokens / 1000)}k context · `
                    : ''}
                  {model.billing_mode === 'subscription'
                    ? 'Covered by your ChatGPT plan'
                    : `${model.input_cost_per_1m == null ? 'unknown' : `$${model.input_cost_per_1m.toFixed(2)}`} in / ${model.output_cost_per_1m == null ? 'unknown' : `$${model.output_cost_per_1m.toFixed(2)}`} out per 1M`}
                </p>
              </div>
              <Button
                size="sm"
                disabled={added || provider.supported === false}
                aria-label={added ? `${model.display_name} added` : `Add ${model.display_name}`}
                onClick={() => onAdd(model, mode)}
              >
                {added ? (
                  'Added'
                ) : (
                  <>
                    <Plus className="h-3.5 w-3.5" aria-hidden />
                    Add
                  </>
                )}
              </Button>
            </li>
          );
        })}
      </ul>
      {!models.isPending && !models.isError && !filtered.length ? (
        <p className="text-sm text-secondary">
          No models match. Use Model not listed to register one by name.
        </p>
      ) : null}
      <div className="flex items-center gap-3">
        <p className="text-xs text-muted">
          Showing {Math.min(visible, filtered.length)} of {filtered.length} models.
        </p>
        {visible < filtered.length ? (
          <Button size="sm" onClick={() => setVisible((n) => n + 40)}>
            Show more models
          </Button>
        ) : null}
      </div>
    </div>
  );
}
