import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { StrictMode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import type { ModelPublic } from '@/api/types';

import { ChatPage } from './chat-page';

// Root-cause reproduction (bug 2026-08-15): on an existing chat, switching the
// model and sending the FIRST message reportedly shows nothing (request not
// posted, blank response); the second send works. This drives the REAL flow --
// real useChatStream / useSendMessage / chat-page effects, StrictMode -- and
// spies on streamChatSse to check the first post-switch send actually fires
// with the NEW model and its stream isn't aborted.

const streamCalls: { url: string; body: unknown; signal: AbortSignal }[] = [];

vi.mock('./stream', () => ({
  streamChatSse: vi.fn(async (url: string, body: unknown, _o: unknown, signal: AbortSignal) => {
    streamCalls.push({ url, body, signal });
    await new Promise(() => {});
  }),
}));

vi.mock('./queries', () => ({
  useChat: () => ({ data: { messages: [], has_summary: false }, isPending: false }),
  useCreateChat: () => ({ mutateAsync: vi.fn(), isPending: false }),
  useSetMessageFeedback: () => ({ mutate: vi.fn() }),
  useClearMessageFeedback: () => ({ mutate: vi.fn() }),
}));

vi.mock('@/features/documents/queries', () => ({ useDocuments: () => ({ data: [] }) }));
vi.mock('@/features/models/queries', () => ({
  useModels: () => ({
    data: [
      {
        id: 'model-1',
        display_name: 'GPT5.6 Luna',
        model_name: 'chatgpt/gpt-5.6-luna',
        provider_kind: 'litellm',
        billing_mode: 'subscription',
        supports_vision: true,
        supports_reasoning: true,
        default_reasoning_effort: 'high',
        supported_reasoning_efforts: ['off', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'],
      },
      {
        id: 'model-2',
        display_name: 'DeepSeek V4 Flash',
        model_name: 'deepseek/deepseek-v4-flash',
        provider_kind: 'litellm',
        billing_mode: 'metered',
        supports_vision: false,
        supports_reasoning: true,
        default_reasoning_effort: 'off',
        supported_reasoning_efforts: ['off', 'low', 'high'],
      },
    ] satisfies ModelPublic[],
  }),
}));
vi.mock('@/features/workspaces/queries', () => ({
  useWorkspaces: () => ({ data: [{ id: 'ws-1', name: 'Acme', web_search_enabled: false }] }),
}));
vi.mock('@/features/workspaces/workspace-context', () => ({
  useWorkspace: () => ({ workspaceId: 'ws-1', setWorkspaceId: vi.fn() }),
}));
vi.mock('./use-pending-attachments', () => ({
  usePendingAttachments: () => ({
    files: [],
    addFiles: vi.fn(),
    remove: vi.fn(),
    clear: vi.fn(),
    error: null,
  }),
}));

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/chat/chat-1']}>
          <Routes>
            <Route path="/chat/:chatId" element={<ChatPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}

afterEach(() => {
  streamCalls.length = 0;
});

test('model and reasoning are selected inside the message composer, not the header', async () => {
  const user = userEvent.setup();
  renderApp();

  const composer = within(screen.getByRole('group', { name: 'Message composer' }));
  const picker = composer.getByRole('button', { name: 'Model and reasoning' });
  expect(composer.getByRole('textbox', { name: 'Message' })).toBeInTheDocument();
  expect(composer.getByRole('button', { name: 'Add attachments and options' })).toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: 'Model and reasoning' })).toHaveLength(1);
  expect(
    within(screen.getByRole('banner')).queryByRole('button', {
      name: 'Model and reasoning',
    }),
  ).not.toBeInTheDocument();

  await user.click(picker);
  await user.click(screen.getByRole('menuitemradio', { name: /^Ultra/ }));
  expect(picker).toHaveTextContent('Ultra');
  await user.type(composer.getByRole('textbox', { name: 'Message' }), 'Compare these documents');
  await user.click(composer.getByRole('button', { name: 'Send' }));

  await waitFor(() => expect(streamCalls).toHaveLength(1));
  expect(streamCalls[0]?.body).toMatchObject({ model_id: 'model-1', reasoning_effort: 'ultra' });
  expect(picker).toBeDisabled();
});

test('first message after switching the model is sent (with the new model) and not aborted', async () => {
  const user = userEvent.setup();
  renderApp();

  await user.click(screen.getByRole('button', { name: 'Model and reasoning' }));
  await user.click(screen.getByRole('menuitemradio', { name: /^Ultra/ }));
  await user.click(screen.getByRole('button', { name: 'Model and reasoning' }));
  await user.click(screen.getByRole('menuitem', { name: /Model/ }));
  await user.click(await screen.findByRole('menuitemradio', { name: /DeepSeek V4 Flash/ }));
  expect(screen.getByRole('button', { name: 'Model and reasoning' })).toHaveTextContent('Default');
  await user.click(screen.getByRole('button', { name: 'Model and reasoning' }));
  expect(screen.queryByRole('menuitemradio', { name: /^Ultra/ })).not.toBeInTheDocument();
  await user.keyboard('{Escape}');

  const box = screen.getByPlaceholderText(/ask about your documents/i);
  await user.type(box, 'What is the websocket pattern for fyers?');
  await user.keyboard('{Enter}');

  await waitFor(() => expect(streamCalls.length).toBeGreaterThan(0));
  const last = streamCalls[streamCalls.length - 1];
  if (!last) throw new Error('expected a stream send');
  expect(last.url).toContain('/chats/chat-1/messages');
  expect((last.body as { model_id?: string }).model_id).toBe('model-2');
  expect(last.body).not.toHaveProperty('reasoning_effort');
  await new Promise((r) => setTimeout(r, 0));
  expect(last.signal.aborted).toBe(false);
});
