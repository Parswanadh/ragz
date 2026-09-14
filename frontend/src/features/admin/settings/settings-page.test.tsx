import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { ProviderSettings } from './queries';

const useProviderSettings = vi.fn();
const useUpdateProviderSettings = vi.fn();
vi.mock('./queries', () => ({
  useProviderSettings: () => useProviderSettings(),
  useUpdateProviderSettings: () => useUpdateProviderSettings(),
}));

import { SettingsPage } from './settings-page';

const settings: ProviderSettings = {
  document_parser: 'docling',
  rerank_provider: 'local',
  cohere_rerank_model: 'rerank-v4.0-fast',
  web_search_provider: 'duckduckgo',
  web_search_full_content: true,
  default_chunk_method: 'heading',
  generative_ui_images: 'off',
  generative_ui_enabled: true,
  llamaparse_key_set: false,
  cohere_key_set: false,
  tavily_key_set: false,
};

const putSpy = vi.fn();

beforeEach(() => {
  useProviderSettings.mockReturnValue({
    data: settings,
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  });
  useUpdateProviderSettings.mockReturnValue({
    mutate: putSpy,
    isPending: false,
    isError: false,
    error: null,
    isSuccess: false,
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

test('renders current settings and masks keys', async () => {
  render(<SettingsPage />);

  expect(await screen.findByLabelText(/document parser/i)).toHaveValue('docling');
  expect(screen.getByLabelText(/reranker/i)).toHaveValue('local');
  expect(screen.getByLabelText(/llamaparse api key/i)).toHaveAttribute('type', 'password');
  expect(screen.getByLabelText(/cohere api key/i)).toHaveAttribute('type', 'password');
});

test('picking Cohere reveals the rerank model select', async () => {
  render(<SettingsPage />);

  expect(screen.queryByLabelText(/cohere model/i)).not.toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText(/reranker/i), 'cohere');
  expect(screen.getByLabelText(/cohere model/i)).toBeInTheDocument();
});

test('submitting sends a PUT with the new reranker and key', async () => {
  render(<SettingsPage />);

  await userEvent.selectOptions(screen.getByLabelText(/reranker/i), 'cohere');
  await userEvent.type(screen.getByLabelText(/cohere api key/i), 'ck-live');
  await userEvent.click(screen.getByRole('button', { name: /save/i }));

  expect(putSpy).toHaveBeenCalledWith(
    expect.objectContaining({ rerank_provider: 'cohere', cohere_api_key: 'ck-live' }),
  );
});

test('saving with the default Local reranker omits cohere_rerank_model from the PUT body', async () => {
  render(<SettingsPage />);

  await userEvent.click(screen.getByRole('button', { name: /save/i }));

  expect(putSpy).toHaveBeenCalledTimes(1);
  const body = putSpy.mock.calls[0]?.[0] as Record<string, unknown>;
  expect(body.rerank_provider).toBe('local');
  expect(body.cohere_rerank_model).toBeUndefined();
});

test('leaving a key field blank on save omits it from the PUT body', async () => {
  render(<SettingsPage />);

  await userEvent.selectOptions(screen.getByLabelText(/reranker/i), 'cohere');
  // Cohere is selected but no key is typed — the field stays blank.
  await userEvent.click(screen.getByRole('button', { name: /save/i }));

  expect(putSpy).toHaveBeenCalledTimes(1);
  const body = putSpy.mock.calls[0]?.[0] as Record<string, unknown>;
  expect(body.cohere_api_key).toBeUndefined();
  expect(body.llamaparse_api_key).toBeUndefined();
});

test('web search links to its canonical panel and unrelated saves do not overwrite its settings', async () => {
  render(<SettingsPage />);
  expect(screen.getByRole('link', { name: 'Agent configuration' })).toHaveAttribute(
    'href',
    '/agent/config#web-search',
  );
  await userEvent.click(screen.getByRole('button', { name: /save/i }));
  const body = putSpy.mock.calls[0]?.[0] as Record<string, unknown>;
  expect(body).not.toHaveProperty('web_search_provider');
  expect(body).not.toHaveProperty('web_search_full_content');
  expect(body).not.toHaveProperty('tavily_api_key');
});

test('sends the default chunking strategy on save', async () => {
  render(<SettingsPage />);

  await userEvent.selectOptions(screen.getByLabelText(/default chunking strategy/i), 'page');
  await userEvent.click(screen.getByRole('button', { name: /save/i }));

  expect(putSpy).toHaveBeenCalledWith(expect.objectContaining({ default_chunk_method: 'page' }));
});

test('offers anydoc as a parser option and selects it when reported by the backend', async () => {
  useProviderSettings.mockReturnValue({
    data: { ...settings, document_parser: 'anydoc' },
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  });

  render(<SettingsPage />);

  expect(await screen.findByRole('option', { name: /anydoc/i })).toBeInTheDocument();
  expect(screen.getByLabelText(/document parser/i)).toHaveValue('anydoc');
});

test('offers liteparse (the recommended default) as a parser option', async () => {
  useProviderSettings.mockReturnValue({
    data: { ...settings, document_parser: 'liteparse' },
    isPending: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  });

  render(<SettingsPage />);

  expect(await screen.findByRole('option', { name: /liteparse/i })).toBeInTheDocument();
  expect(screen.getByLabelText(/document parser/i)).toHaveValue('liteparse');
});

test('renders the generative UI images select defaulting to Off', async () => {
  render(<SettingsPage />);

  expect(await screen.findByLabelText(/generative ui images/i)).toHaveValue('off');
});

test('changing generative UI images to web results and saving sends it in the PUT body', async () => {
  render(<SettingsPage />);

  await userEvent.selectOptions(screen.getByLabelText(/generative ui images/i), 'web_results');
  await userEvent.click(screen.getByRole('button', { name: /save/i }));

  expect(putSpy).toHaveBeenCalledWith(
    expect.objectContaining({ generative_ui_images: 'web_results' }),
  );
});

test('renders the rich generative UI checkbox from the mocked value (on)', async () => {
  render(<SettingsPage />);

  expect(await screen.findByLabelText(/rich generative ui/i)).toBeChecked();
});

test('unchecking rich generative UI and saving sends generative_ui_enabled false', async () => {
  render(<SettingsPage />);

  await userEvent.click(await screen.findByLabelText(/rich generative ui/i));
  await userEvent.click(screen.getByRole('button', { name: /save/i }));

  expect(putSpy).toHaveBeenCalledWith(expect.objectContaining({ generative_ui_enabled: false }));
});

test('saving unchanged includes generative_ui_enabled true in the PUT body', async () => {
  render(<SettingsPage />);

  await userEvent.click(await screen.findByRole('button', { name: /save/i }));

  expect(putSpy).toHaveBeenCalledWith(expect.objectContaining({ generative_ui_enabled: true }));
});

test('shows an error message and retry button when the settings query fails', async () => {
  const refetch = vi.fn();
  useProviderSettings.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: true,
    error: new Error('failed to load settings'),
    refetch,
  });

  render(<SettingsPage />);

  expect(await screen.findByRole('alert')).toHaveTextContent(/failed to load/i);
  await userEvent.click(screen.getByRole('button', { name: /retry/i }));
  expect(refetch).toHaveBeenCalledTimes(1);
});
