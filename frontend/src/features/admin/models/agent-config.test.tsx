import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';

import { ModelsPage } from './models-page';
import type { ChatGptLogin, WebConfig } from './agent-api';

const provider = {
  id: 'future_provider',
  name: 'Future Provider',
  icon: 'future_provider',
  model_count: 1,
  needs_key: true,
  needs_base_url: false,
  provider_kind: 'litellm',
  default_base_url: null,
  auth_mode: 'api_key',
  supported: true,
};
const catalogModel = {
  id: 'future_provider/bright-9',
  name: 'future_provider/bright-9',
  provider: 'future_provider',
  mode: 'chat',
  display_name: 'Bright 9',
  max_input_tokens: 200000,
  max_output_tokens: 32000,
  input_cost_per_1m: 1,
  output_cost_per_1m: 2,
  supports_reasoning: true,
  supports_vision: true,
  supports_function_calling: true,
  supported_reasoning_efforts: ['low', 'high', 'ultra'],
  registered: false,
  billing_mode: 'metered',
};
const idle: ChatGptLogin = {
  login_id: null,
  state: 'idle',
  verification_url: null,
  user_code: null,
  expires_at: null,
  interval: 5,
  error: null,
};
const pending: ChatGptLogin = {
  ...idle,
  login_id: 'flow-1',
  state: 'pending',
  verification_url: 'https://auth.openai.com/codex/device',
  user_code: 'ABCD-EFGH',
  expires_at: 9999999999,
};
const web: WebConfig = {
  provider: 'duckduckgo',
  perplexity_model: 'openai/gpt-5.6-luna',
  max_calls_per_turn: 3,
  daily_cap: 100,
  full_content: true,
  providers: [
    {
      id: 'duckduckgo',
      name: 'DuckDuckGo',
      result_kind: 'links',
      needs_key: false,
      key_set: false,
      key_fingerprint: null,
      ready: true,
    },
    {
      id: 'tavily',
      name: 'Tavily',
      result_kind: 'links',
      needs_key: true,
      key_set: false,
      key_fingerprint: null,
      ready: false,
    },
    {
      id: 'perplexity',
      name: 'Perplexity',
      result_kind: 'answer',
      needs_key: true,
      key_set: false,
      key_fingerprint: null,
      ready: false,
    },
  ],
};

function setup(providerOverrides: { supported?: boolean; configuration_note?: string } = {}) {
  const requests: { path: string; method: string; body: Record<string, unknown> }[] = [];
  let login = idle;
  let config = web;
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
      let data: unknown = {};
      if (path.endsWith('/catalog/providers'))
        data = {
          available: true,
          litellm_version: '1.100.0',
          providers: [{ ...provider, ...providerOverrides }],
        };
      else if (path.endsWith('/catalog/models'))
        data = { available: true, litellm_version: '1.100.0', models: [catalogModel] };
      else if (path.endsWith('/catalog')) data = { entries: [], new_available: 0 };
      else if (path.endsWith('/chatgpt/login')) {
        login = request.method === 'DELETE' ? { ...idle, state: 'cancelled' } : pending;
        data = login;
      } else if (path.endsWith('/chatgpt/poll')) data = login;
      else if (path.endsWith('/chatgpt'))
        data = {
          available: true,
          connected: false,
          account_id: null,
          email: null,
          plan_type: null,
          expires_at: null,
          login,
        };
      else if (path.endsWith('/web-search/keys/perplexity')) {
        config = {
          ...config,
          providers: config.providers.map((p) =>
            p.id === 'perplexity'
              ? { ...p, key_set: true, key_fingerprint: '12…89', ready: true }
              : p,
          ),
        };
        data = config;
      } else if (path.endsWith('/web-search')) {
        if (request.method === 'PATCH') config = { ...config, ...body };
        data = config;
      } else if (path.endsWith('/models'))
        data = request.method === 'POST' ? { id: 'created-1', ...body } : [];
      return new Response(JSON.stringify(data), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ModelsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { requests, user: userEvent.setup() };
}

afterEach(() => vi.unstubAllGlobals());

test('an unsupported provider stays discoverable and explains why model registration is unavailable', async () => {
  const { user } = setup({
    supported: false,
    configuration_note: 'This provider needs an unsupported file-based sign-in.',
  });
  await user.click(await screen.findByRole('button', { name: /Future Provider/ }));
  expect(
    screen.getByText('This provider needs an unsupported file-based sign-in.'),
  ).toBeInTheDocument();
  expect(await screen.findByRole('button', { name: 'Add Bright 9' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Model not listed' })).toBeDisabled();
});

test('reloading the catalog requests a server refresh before reloading providers', async () => {
  const { requests, user } = setup();
  await screen.findByRole('searchbox', { name: 'Search providers' });
  await user.click(screen.getByRole('button', { name: 'Reload catalog' }));
  await waitFor(() =>
    expect(requests.some((r) => r.method === 'POST' && r.path.endsWith('/catalog/refresh'))).toBe(
      true,
    ),
  );
  const refresh = requests.findIndex((r) => r.path.endsWith('/catalog/refresh'));
  await waitFor(() =>
    expect(requests.slice(refresh + 1).some((r) => r.path.endsWith('/catalog/providers'))).toBe(
      true,
    ),
  );
});

test('a provider supplied by the runtime catalog is searchable and registers its canonical model with a write-only key', async () => {
  const { requests, user } = setup();
  await user.type(await screen.findByRole('searchbox', { name: 'Search providers' }), 'future');
  await user.click(await screen.findByRole('button', { name: /Future Provider/ }));
  await user.type(
    await screen.findByRole('searchbox', { name: 'Search models from this provider' }),
    'bright',
  );
  await user.click(await screen.findByRole('button', { name: 'Add Bright 9' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByLabelText('API key')).toHaveValue('');
  await user.type(within(dialog).getByLabelText('API key'), 'synthetic-test-key');
  await user.click(within(dialog).getByRole('button', { name: 'Add model' }));
  await waitFor(() =>
    expect(
      requests.find((r) => r.method === 'POST' && r.path.endsWith('/models'))?.body,
    ).toMatchObject({
      litellm_model_name: 'future_provider/bright-9',
      provider_kind: 'litellm',
      api_key: 'synthetic-test-key',
      supports_reasoning: true,
    }),
  );
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

test('ChatGPT connect displays a device code and cancellation removes it', async () => {
  const { requests, user } = setup();
  await user.click(await screen.findByRole('button', { name: 'Connect ChatGPT' }));
  expect(await screen.findByText('ABCD-EFGH')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /Open sign-in page/ })).toHaveAttribute(
    'href',
    'https://auth.openai.com/codex/device',
  );
  await user.click(screen.getByRole('button', { name: 'Cancel sign-in' }));
  await waitFor(() => expect(screen.queryByText('ABCD-EFGH')).not.toBeInTheDocument());
  expect(requests.some((r) => r.method === 'DELETE' && r.path.endsWith('/chatgpt/login'))).toBe(
    true,
  );
});

test('Perplexity saves its own key, clears the field and persists the chosen research model and caps', async () => {
  const { requests, user } = setup();
  await user.type(await screen.findByLabelText('Perplexity API key'), 'synthetic-perplexity-key');
  await user.click(screen.getByRole('button', { name: 'Save Perplexity key' }));
  await waitFor(() => expect(screen.getByLabelText('Perplexity API key')).toHaveValue(''));
  expect(requests.find((r) => r.path.endsWith('/keys/perplexity'))?.body).toEqual({
    api_key: 'synthetic-perplexity-key',
  });
  await user.selectOptions(screen.getByLabelText('Web search provider'), 'perplexity');
  await user.clear(screen.getByLabelText('Perplexity model'));
  await user.type(screen.getByLabelText('Perplexity model'), 'openai/custom-research');
  await user.click(screen.getByRole('button', { name: 'Save web search' }));
  await waitFor(() =>
    expect(
      requests.find((r) => r.method === 'PATCH' && r.path.endsWith('/web-search'))?.body,
    ).toMatchObject({
      provider: 'perplexity',
      perplexity_model: 'openai/custom-research',
      max_calls_per_turn: 3,
      daily_cap: 100,
    }),
  );
});
