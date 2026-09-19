import { ArrowLeft, KeyRound, Pencil, Plus, Trash2 } from 'lucide-react';
import { Fragment, useState } from 'react';
import { Link } from 'react-router-dom';

import type { ModelOut } from '@/api/types';
import { ErrorBoundary } from '@/components/error-boundary';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter } from '@/components/ui/dialog';
import { QueryError } from '@/components/ui/query-error';
import { Spinner } from '@/components/ui/spinner';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table';
import { toast } from '@/components/ui/toaster';

import { type TestResult, useTestModel } from './agent-api';
import { ChatGptPanel } from './chatgpt-panel';
import { ModelFormDialog } from './model-form-dialog';
import { useAdminModels, useDeleteModel, usePatchModel } from './queries';
import { RuntimeCatalogPanel } from './runtime-catalog-panel';
import { WebSearchPanel } from './web-search-panel';

function syncTone(status: ModelOut['sync_status']): StatusTone {
  return status === 'synced' ? 'success' : status === 'error' ? 'danger' : 'accent';
}

export function ModelsPage() {
  const models = useAdminModels();
  const patchModel = usePatchModel();
  const deleteModel = useDeleteModel();
  const testModel = useTestModel();
  const [formTarget, setFormTarget] = useState<'create' | ModelOut | null>(null);
  const [formKey, setFormKey] = useState(0);
  const [removing, setRemoving] = useState<ModelOut | null>(null);
  const [tab, setTab] = useState<'chat' | 'embedding'>('chat');
  const [results, setResults] = useState<Record<string, TestResult>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const openForm = (target: 'create' | ModelOut) => {
    setFormTarget(target);
    setFormKey((key) => key + 1);
  };
  const showError = (id: string, error: Error) =>
    setErrors((previous) => ({ ...previous, [id]: error.message }));
  const rows = models.data?.filter((model) => model.modality === tab) ?? [];

  return (
    <>
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-line bg-bg px-4 py-3 sm:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <Link
            to="/agent"
            className="inline-flex items-center gap-1 text-xs text-secondary hover:text-ink"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            Back to chat
          </Link>
          <div>
            <h1 className="text-base font-semibold text-ink">Agent configuration</h1>
            <p className="text-xs text-secondary">Models, keys and web search for this instance</p>
          </div>
        </div>
        <Button variant="primary" size="sm" onClick={() => openForm('create')}>
          <Plus className="h-3.5 w-3.5" aria-hidden />
          Add model
        </Button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6">
          <ErrorBoundary compact>
            <section aria-labelledby="registered-models-heading" className="space-y-4">
              <div>
                <h2 id="registered-models-heading" className="text-base font-semibold text-ink">
                  Models
                </h2>
                <p className="text-sm text-secondary">
                  Every model the agent may run. Enabled chat models appear in the chat picker;
                  workspace defaults stay in workspace settings.
                </p>
              </div>
              <div className="flex gap-1" role="group" aria-label="Registered model type">
                {(['chat', 'embedding'] as const).map((type) => (
                  <button
                    key={type}
                    type="button"
                    aria-pressed={tab === type}
                    onClick={() => setTab(type)}
                    className={`rounded-md px-3 py-1.5 text-xs capitalize ${tab === type ? 'bg-subtle text-ink' : 'text-secondary'}`}
                  >
                    {type} models
                  </button>
                ))}
              </div>
              {models.isPending ? <Spinner label="Loading models…" /> : null}
              {models.isError ? (
                <QueryError error={models.error} onRetry={() => models.refetch()} />
              ) : null}
              {models.data ? (
                rows.length ? (
                  <div className="overflow-x-auto rounded-lg border border-line">
                    <Table>
                      <THead>
                        <TR>
                          <TH>Model</TH>
                          <TH>Provider</TH>
                          <TH>Key / connection</TH>
                          <TH>Status</TH>
                          <TH>Enabled</TH>
                          {tab === 'chat' ? <TH>Utility</TH> : <TH>Dimension</TH>}
                          <TH>
                            <span className="sr-only">Actions</span>
                          </TH>
                        </TR>
                      </THead>
                      <TBody>
                        {rows.map((model) => {
                          const subscription = model.litellm_model_name.startsWith('chatgpt/');
                          const result = results[model.id];
                          const error = errors[model.id];
                          return (
                            <Fragment key={model.id}>
                              <TR>
                                <TD>
                                  <div className="flex flex-wrap items-center gap-2 font-medium">
                                    {model.display_name}
                                    {subscription ? (
                                      <StatusPill tone="accent">ChatGPT plan</StatusPill>
                                    ) : null}
                                  </div>
                                  <div className="mt-1 break-all font-mono text-xs text-muted">
                                    {model.litellm_model_name}
                                  </div>
                                  {model.supports_reasoning ? (
                                    <div className="mt-1 text-xs text-muted">
                                      Reasoning: {model.default_reasoning_effort}
                                    </div>
                                  ) : null}
                                </TD>
                                <TD className="text-secondary">
                                  {subscription ? 'ChatGPT' : model.provider_kind}
                                </TD>
                                <TD className="text-xs text-secondary">
                                  {subscription ? (
                                    'ChatGPT sign-in'
                                  ) : model.key_fingerprint ? (
                                    <span className="font-mono">{model.key_fingerprint}</span>
                                  ) : model.provider_kind === 'tei' ||
                                    model.provider_kind === 'ollama' ? (
                                    'No key needed'
                                  ) : (
                                    'No key stored'
                                  )}
                                </TD>
                                <TD>
                                  <StatusPill tone={syncTone(model.sync_status)}>
                                    {model.sync_status}
                                  </StatusPill>
                                </TD>
                                <TD>
                                  <input
                                    type="checkbox"
                                    aria-label={`Enable ${model.display_name}`}
                                    checked={model.enabled}
                                    disabled={patchModel.isPending}
                                    onChange={(e) =>
                                      patchModel.mutate(
                                        { modelId: model.id, body: { enabled: e.target.checked } },
                                        { onError: (err) => showError(model.id, err) },
                                      )
                                    }
                                    className="h-4 w-4 accent-[var(--accent)]"
                                  />
                                </TD>
                                <TD>
                                  {tab === 'chat' ? (
                                    <input
                                      type="radio"
                                      name="utility-model"
                                      aria-label={`Use ${model.display_name} as the utility model`}
                                      checked={model.is_utility}
                                      disabled={patchModel.isPending || !model.enabled}
                                      onChange={() =>
                                        patchModel.mutate(
                                          { modelId: model.id, body: { is_utility: true } },
                                          { onError: (err) => showError(model.id, err) },
                                        )
                                      }
                                      className="h-4 w-4 accent-[var(--accent)]"
                                    />
                                  ) : (
                                    (model.dimension ?? '—')
                                  )}
                                </TD>
                                <TD>
                                  <div className="flex items-center justify-end gap-1">
                                    {model.provider_kind === 'tei' ? (
                                      <span className="text-xs text-muted">Built-in</span>
                                    ) : (
                                      <>
                                        {model.modality === 'chat' ? (
                                          <Button
                                            size="sm"
                                            disabled={testModel.isPending || !model.enabled}
                                            aria-label={`Test ${model.display_name}`}
                                            onClick={() =>
                                              testModel.mutate(model.id, {
                                                onSuccess: (next) => {
                                                  setResults((previous) => ({
                                                    ...previous,
                                                    [model.id]: next,
                                                  }));
                                                  setErrors((previous) => ({
                                                    ...previous,
                                                    [model.id]: '',
                                                  }));
                                                },
                                                onError: (err) => showError(model.id, err),
                                              })
                                            }
                                          >
                                            {testModel.isPending && testModel.variables === model.id
                                              ? 'Testing…'
                                              : 'Test'}
                                          </Button>
                                        ) : null}
                                        <Button
                                          variant="ghost"
                                          size="icon"
                                          aria-label={`Edit ${model.display_name}`}
                                          onClick={() => openForm(model)}
                                        >
                                          <Pencil className="h-4 w-4" aria-hidden />
                                        </Button>
                                        {!subscription && model.provider_kind !== 'ollama' ? (
                                          <Button
                                            variant="ghost"
                                            size="icon"
                                            aria-label={`Update key for ${model.display_name}`}
                                            onClick={() => openForm(model)}
                                          >
                                            <KeyRound className="h-4 w-4" aria-hidden />
                                          </Button>
                                        ) : null}
                                        <Button
                                          variant="ghost"
                                          size="icon"
                                          aria-label={`Remove ${model.display_name}`}
                                          onClick={() => setRemoving(model)}
                                        >
                                          <Trash2 className="h-4 w-4" aria-hidden />
                                        </Button>
                                      </>
                                    )}
                                  </div>
                                </TD>
                              </TR>
                              {error || result ? (
                                <TR>
                                  <TD colSpan={7}>
                                    <p
                                      role={error || !result?.ok ? 'alert' : 'status'}
                                      className={`text-xs ${error || !result?.ok ? 'text-danger' : 'text-success'}`}
                                    >
                                      {error ||
                                        `${result?.detail} · ${Math.round(result?.latency_ms ?? 0)} ms`}
                                    </p>
                                  </TD>
                                </TR>
                              ) : null}
                            </Fragment>
                          );
                        })}
                      </TBody>
                    </Table>
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-line p-6 text-center">
                    <p className="text-sm text-secondary">No {tab} models registered yet.</p>
                    <Button size="sm" className="mt-3" onClick={() => openForm('create')}>
                      Add your first model
                    </Button>
                  </div>
                )
              ) : null}
              <p className="text-xs text-muted">
                {tab === 'chat'
                  ? 'The utility model powers answer-quality scoring, evals, and (later) enrichment and memory. Choosing a new one replaces the current designation immediately.'
                  : 'Select an embedding model in workspace settings. Existing document vectors keep their configured collection and dimension.'}
              </p>
            </section>
          </ErrorBoundary>
          <ErrorBoundary compact>
            <ChatGptPanel />
          </ErrorBoundary>
          <ErrorBoundary compact>
            <RuntimeCatalogPanel registered={models.data ?? []} />
          </ErrorBoundary>
          <ErrorBoundary compact>
            <WebSearchPanel />
          </ErrorBoundary>
        </div>
      </div>
      {formTarget !== null ? (
        <ModelFormDialog
          key={formKey}
          open
          onOpenChange={(open) => !open && setFormTarget(null)}
          model={formTarget === 'create' ? null : formTarget}
        />
      ) : null}
      <Dialog open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
        <DialogContent
          title="Remove model"
          description={`“${removing?.display_name ?? ''}” will be removed from the registry and every picker.`}
        >
          <DialogFooter>
            <Button onClick={() => setRemoving(null)}>Cancel</Button>
            <Button
              variant="danger"
              disabled={deleteModel.isPending}
              onClick={() => {
                if (removing)
                  deleteModel.mutate(removing.id, {
                    onSuccess: () => setRemoving(null),
                    onError: (error) => toast.error(error.message),
                  });
              }}
            >
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
