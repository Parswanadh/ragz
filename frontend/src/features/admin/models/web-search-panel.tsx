import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { QueryError } from '@/components/ui/query-error';
import { NativeSelect } from '@/components/ui/select';
import { Spinner } from '@/components/ui/spinner';
import { StatusPill } from '@/components/ui/status-pill';

import {
  agentRequest,
  type TestResult,
  type WebConfig,
  type WebProvider,
  useSaveWebConfig,
  useWebConfig,
} from './agent-api';

export function WebSearchPanel() {
  const config = useWebConfig();
  const save = useSaveWebConfig();
  const [draft, setDraft] = useState<Partial<Omit<WebConfig, 'providers'>>>({});
  const form = config.data ? { ...config.data, ...draft } : null;
  const change = (patch: Partial<Omit<WebConfig, 'providers'>>) =>
    setDraft((prev) => ({ ...prev, ...patch }));
  const selected = form?.providers.find((p) => p.id === form.provider);
  return (
    <section id="web-search" aria-labelledby="web-search-heading" className="scroll-mt-4 space-y-4">
      <div>
        <h2 id="web-search-heading" className="text-base font-semibold text-ink">
          Web search
        </h2>
        <p className="text-sm text-secondary">
          DuckDuckGo and Tavily return links. Perplexity adds cited research while link searches
          remain available.
        </p>
      </div>
      {config.isPending ? <Spinner label="Loading web search…" /> : null}
      {config.isError ? <QueryError error={config.error} onRetry={() => config.refetch()} /> : null}
      {form ? (
        <>
          <form
            className="space-y-4 rounded-lg border border-line bg-bg p-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(
                {
                  provider: form.provider,
                  perplexity_model: form.perplexity_model,
                  max_calls_per_turn: form.max_calls_per_turn,
                  daily_cap: form.daily_cap,
                  full_content: form.full_content,
                },
                { onSuccess: () => setDraft({}) },
              );
            }}
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label htmlFor="web-provider">Web search provider</Label>
                <NativeSelect
                  id="web-provider"
                  value={form.provider}
                  onChange={(e) => change({ provider: e.target.value as WebConfig['provider'] })}
                >
                  {form.providers.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </NativeSelect>
              </div>
              {form.provider === 'perplexity' ? (
                <div>
                  <Label htmlFor="perplexity-model">Perplexity model</Label>
                  <Input
                    id="perplexity-model"
                    required
                    maxLength={120}
                    value={form.perplexity_model}
                    onChange={(e) => change({ perplexity_model: e.target.value })}
                  />
                </div>
              ) : null}
            </div>
            <p className="text-sm text-secondary">
              {form.provider === 'perplexity'
                ? selected?.ready
                  ? 'Perplexity provides research with citations. Link searches run on DuckDuckGo.'
                  : 'Save a Perplexity key below to enable research. Link searches continue on DuckDuckGo.'
                : form.provider === 'tavily' && !selected?.ready
                  ? 'Save a Tavily key below. Link searches fall back to DuckDuckGo until it is ready.'
                  : `Link searches run on ${selected?.name ?? form.provider}.`}
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label htmlFor="web-max-calls">Maximum calls per turn</Label>
                <Input
                  id="web-max-calls"
                  type="number"
                  min={1}
                  max={50}
                  required
                  value={form.max_calls_per_turn}
                  onChange={(e) => change({ max_calls_per_turn: Number(e.target.value) })}
                />
              </div>
              <div>
                <Label htmlFor="web-daily-cap">Daily search cap</Label>
                <Input
                  id="web-daily-cap"
                  type="number"
                  min={1}
                  max={10000}
                  required
                  value={form.daily_cap}
                  onChange={(e) => change({ daily_cap: Number(e.target.value) })}
                />
              </div>
            </div>
            <label className="flex items-center gap-2 text-sm text-secondary">
              <input
                type="checkbox"
                checked={form.full_content}
                onChange={(e) => change({ full_content: e.target.checked })}
              />
              Fetch full page content
            </label>
            {save.isError ? (
              <p role="alert" className="text-sm text-danger">
                {save.error.message}
              </p>
            ) : null}
            {save.isSuccess && !Object.keys(draft).length ? (
              <p role="status" className="text-sm text-success">
                Web search settings saved.
              </p>
            ) : null}
            <Button type="submit" variant="primary" size="sm" disabled={save.isPending}>
              {save.isPending ? 'Saving…' : 'Save web search'}
            </Button>
          </form>
          <div className="grid gap-3 lg:grid-cols-3">
            {form.providers.map((p) => (
              <WebProviderCard key={p.id} provider={p} />
            ))}
          </div>
          <p className="text-xs text-muted">
            Web search also requires workspace permission and consent in chat. Your existing query
            redaction and quotas apply.
          </p>
        </>
      ) : null}
    </section>
  );
}

function WebProviderCard({ provider }: { provider: WebProvider }) {
  const client = useQueryClient();
  const [key, setKey] = useState('');
  const [confirmRemove, setConfirmRemove] = useState(false);
  const keyMutation = useMutation({
    mutationFn: (remove: boolean) =>
      agentRequest<WebConfig>(
        `/admin/web-search/keys/${provider.id}`,
        remove ? 'DELETE' : 'PUT',
        remove ? undefined : { api_key: key },
      ),
    onSuccess: (next) => {
      client.setQueryData(['agent-web-search'], next);
      setKey('');
      setConfirmRemove(false);
    },
  });
  const test = useMutation({
    mutationFn: () => agentRequest<TestResult>(`/admin/web-search/test/${provider.id}`, 'POST'),
  });
  return (
    <div className="space-y-3 rounded-lg border border-line bg-bg p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">{provider.name}</h3>
        <StatusPill tone={provider.ready ? 'success' : 'muted'}>
          {provider.ready ? 'Ready' : 'Needs key'}
        </StatusPill>
      </div>
      <p className="text-xs text-muted">
        {provider.result_kind === 'answer' ? 'Research with citations' : 'Search result links'}
        {provider.key_fingerprint ? ` · ${provider.key_fingerprint}` : ''}
      </p>
      {provider.needs_key ? (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            keyMutation.mutate(false);
          }}
        >
          <Label htmlFor={`web-key-${provider.id}`}>{provider.name} API key</Label>
          <Input
            id={`web-key-${provider.id}`}
            type="password"
            autoComplete="off"
            value={key}
            placeholder={
              provider.key_set ? 'Leave blank to keep the stored key' : 'Paste an API key'
            }
            onChange={(e) => setKey(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              type="submit"
              size="sm"
              disabled={!key.trim() || keyMutation.isPending}
              aria-label={`Save ${provider.name} key`}
            >
              Save key
            </Button>
            {provider.key_set ? (
              <Button
                size="sm"
                disabled={keyMutation.isPending}
                onClick={() => setConfirmRemove(true)}
                aria-label={`Remove ${provider.name} key`}
              >
                Remove key
              </Button>
            ) : null}
          </div>
        </form>
      ) : (
        <p className="text-sm text-secondary">Works without an API key.</p>
      )}
      <Button
        size="sm"
        disabled={test.isPending || !provider.ready}
        onClick={() => test.mutate()}
        aria-label={`Test ${provider.name}`}
      >
        {test.isPending ? 'Testing…' : 'Test provider'}
      </Button>
      {test.data ? (
        <p role="status" className={`text-xs ${test.data.ok ? 'text-success' : 'text-danger'}`}>
          {test.data.detail} · {Math.round(test.data.latency_ms)} ms
          {test.data.result_count !== undefined ? ` · ${test.data.result_count} results` : ''}
        </p>
      ) : null}
      {keyMutation.isError || test.isError ? (
        <p role="alert" className="text-xs text-danger">
          {keyMutation.error?.message ?? test.error?.message}
        </p>
      ) : null}
      <Dialog open={confirmRemove} onOpenChange={setConfirmRemove}>
        <DialogContent
          title={`Remove ${provider.name} key`}
          description="This provider will need a new key before it can run again."
        >
          <DialogFooter>
            <Button onClick={() => setConfirmRemove(false)}>Cancel</Button>
            <Button
              variant="danger"
              disabled={keyMutation.isPending}
              onClick={() => keyMutation.mutate(true)}
            >
              Remove key
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
