import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { ChatGptLogin, ChatGptStatus } from '@/api/types';

import { ChatGptPanel } from './chatgpt-panel';

const idle: ChatGptLogin = {
  state: 'idle',
  interval: 5,
  login_id: null,
  user_code: null,
  verification_url: null,
  expires_at: null,
  error: null,
};
const pending: ChatGptLogin = {
  ...idle,
  state: 'pending',
  login_id: 'flow',
  user_code: 'CODE-TEST',
  verification_url: 'https://auth.openai.com/codex/device',
  expires_at: 9999999999,
};
const disconnected: ChatGptStatus = {
  available: true,
  connected: false,
  email: null,
  account_id: null,
  plan_type: null,
  expires_at: null,
  login: idle,
};
const json = (value: unknown) =>
  new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } });

function setup(status: ChatGptStatus, pollResult?: Promise<Response>) {
  const calls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname;
      calls.push(`${request.method} ${path}`);
      if (path.endsWith('/poll')) return pollResult ?? json(pending);
      if (path.endsWith('/login'))
        return json(request.method === 'DELETE' ? { ...idle, state: 'cancelled' } : pending);
      return json(request.method === 'DELETE' ? disconnected : status);
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ChatGptPanel />
    </QueryClientProvider>,
  );
  return { user: userEvent.setup(), calls };
}

afterEach(() => vi.unstubAllGlobals());

test('connected status shows the account and disconnect requires its explicit action', async () => {
  const { user, calls } = setup({
    ...disconnected,
    connected: true,
    email: 'operator@example.test',
    plan_type: 'pro',
  });
  expect(await screen.findByText('operator@example.test')).toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: 'Disconnect' }));
  expect(calls.filter((call) => call.startsWith('DELETE'))).toHaveLength(0);
  await user.click(
    within(screen.getByRole('dialog')).getByRole('button', { name: 'Disconnect ChatGPT' }),
  );
  expect(await screen.findByRole('button', { name: 'Connect ChatGPT' })).toBeEnabled();
  expect(calls).toContain('DELETE /api/v1/admin/models/chatgpt');
});

test.each(['failed', 'expired'] as const)(
  'a %s login offers a new sign-in without showing a stale code',
  async (state) => {
    setup({
      ...disconnected,
      login: { ...pending, state, error: state === 'failed' ? 'Sign-in was declined.' : null },
    });
    expect(await screen.findByRole('alert')).toHaveTextContent(
      state === 'failed' ? 'Sign-in was declined.' : 'expired',
    );
    expect(screen.queryByText('CODE-TEST')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect ChatGPT' })).toBeEnabled();
  },
);

test('a cancelled poll finishing late cannot restore the device code', async () => {
  let finish: ((response: Response) => void) | undefined;
  const slowPoll = new Promise<Response>((resolve) => {
    finish = resolve;
  });
  const { user, calls } = setup(disconnected, slowPoll);
  await user.click(await screen.findByRole('button', { name: 'Connect ChatGPT' }));
  await screen.findByText('CODE-TEST');
  await waitFor(() => expect(calls).toContain('POST /api/v1/admin/models/chatgpt/poll'));
  await user.click(screen.getByRole('button', { name: 'Cancel sign-in' }));
  await waitFor(() => expect(screen.queryByText('CODE-TEST')).not.toBeInTheDocument());
  await act(async () => {
    finish?.(json(pending));
  });
  expect(screen.queryByText('CODE-TEST')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Connect ChatGPT' })).toBeEnabled();
});
