import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import type { ModelOut } from '@/api/types';

import { ModelsPage } from './models-page';

const modelA: ModelOut = {
  id: 'm1',
  litellm_model_name: 'gpt-test',
  display_name: 'API model',
  provider_kind: 'openai',
  base_url: null,
  enabled: true,
  key_fingerprint: '12…89',
  sync_status: 'synced',
  mock_response: null,
  tools_unreliable: false,
  is_utility: true,
  supports_reasoning: false,
  default_reasoning_effort: 'off',
  supports_vision: false,
  modality: 'chat',
  dimension: null,
  collection_name: null,
  billing_mode: 'metered',
};
const modelB: ModelOut = {
  ...modelA,
  id: 'm2',
  display_name: 'Plan model',
  litellm_model_name: 'chatgpt/gpt-5.6-luna',
  provider_kind: 'litellm',
  is_utility: false,
  key_fingerprint: null,
  billing_mode: 'subscription',
};
const modelC: ModelOut = {
  ...modelA,
  id: 'm3',
  display_name: 'TEI embeddings',
  provider_kind: 'tei',
  modality: 'embedding',
  dimension: 1024,
  collection_name: 'ws_default_bge_m3',
  is_utility: false,
};

function setup({ fail = false } = {}) {
  let rows = [modelA, modelB, modelC];
  const requests: { path: string; method: string; body: Record<string, unknown> }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname;
      const body =
        request.method === 'GET'
          ? {}
          : ((await request
              .clone()
              .json()
              .catch(() => ({}))) as Record<string, unknown>);
      requests.push({ path, method: request.method, body });
      if (fail && path.endsWith('/models')) return new Response('{}', { status: 503 });
      let data: unknown = {};
      if (path.endsWith('/catalog/providers'))
        data = { available: true, litellm_version: '1.100.0', providers: [] };
      else if (path.endsWith('/chatgpt'))
        data = { available: true, connected: false, login: { state: 'idle', interval: 5 } };
      else if (path.endsWith('/web-search'))
        data = {
          provider: 'duckduckgo',
          perplexity_model: 'openai/gpt-5.6-luna',
          max_calls_per_turn: 3,
          daily_cap: 100,
          full_content: true,
          providers: [],
        };
      else if (path.endsWith('/test'))
        data = { ok: true, detail: 'Model responded successfully', latency_ms: 42 };
      else if (request.method === 'PATCH') {
        rows = rows.map((row) =>
          row.id === path.split('/').pop()
            ? { ...row, ...body }
            : body.is_utility
              ? { ...row, is_utility: false }
              : row,
        );
        data = rows.find((row) => row.id === path.split('/').pop());
      } else if (path.endsWith('/models')) data = rows;
      return new Response(JSON.stringify(data), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ModelsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { user: userEvent.setup(), requests };
}

afterEach(() => vi.unstubAllGlobals());

test('utility designation moves to the chosen model and sends only its patch', async () => {
  const { user, requests } = setup();
  expect(await screen.findByLabelText('Use API model as the utility model')).toBeChecked();
  await user.click(screen.getByLabelText('Use Plan model as the utility model'));
  await waitFor(() =>
    expect(screen.getByLabelText('Use Plan model as the utility model')).toBeChecked(),
  );
  expect(screen.getByLabelText('Use API model as the utility model')).not.toBeChecked();
  expect(requests.filter((r) => r.method === 'PATCH')).toEqual([
    { path: '/api/v1/admin/models/m2', method: 'PATCH', body: { is_utility: true } },
  ]);
});

test('embedding tab preserves built-in model dimension and does not offer deletion or utility designation', async () => {
  const { user } = setup();
  await screen.findByText('API model');
  expect(screen.queryByText('TEI embeddings')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'embedding models' }));
  expect(screen.getByText('TEI embeddings')).toBeInTheDocument();
  expect(screen.getByText('1024')).toBeInTheDocument();
  expect(screen.queryByLabelText('Remove TEI embeddings')).not.toBeInTheDocument();
  expect(screen.queryByRole('radio')).not.toBeInTheDocument();
});

test('model tests are explicit and show their outcome beside the model', async () => {
  const { user, requests } = setup();
  await screen.findByText('Plan model');
  expect(requests.some((r) => r.path.endsWith('/test'))).toBe(false);
  await user.click(screen.getByRole('button', { name: 'Test Plan model' }));
  expect(await screen.findByRole('status')).toHaveTextContent(
    'Model responded successfully · 42 ms',
  );
  const row = screen.getByText('Plan model').closest('tr');
  expect(row).not.toHaveTextContent('$');
  expect(within(row!).getByText('ChatGPT plan')).toBeInTheDocument();
});

test('blank API-key edits preserve the key and subscription model edits do not offer an API key', async () => {
  const { user, requests } = setup();
  await user.click(await screen.findByRole('button', { name: 'Edit API model' }));
  expect(screen.getByLabelText('API key')).toHaveValue('');
  await user.clear(screen.getByLabelText('Display name'));
  await user.type(screen.getByLabelText('Display name'), 'Renamed API');
  await user.click(screen.getByRole('button', { name: 'Save changes' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  expect(requests.find((r) => r.method === 'PATCH')?.body).toEqual({ display_name: 'Renamed API' });
  await user.click(screen.getByRole('button', { name: 'Edit Plan model' }));
  expect(screen.queryByLabelText('API key')).not.toBeInTheDocument();
});

test('a failed registry query leaves the independent configuration panels usable', async () => {
  setup({ fail: true });
  expect(await screen.findByRole('alert')).toHaveTextContent(/failed to load models/i);
  expect(screen.getByRole('button', { name: 'Connect ChatGPT' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Save web search' })).toBeEnabled();
});
