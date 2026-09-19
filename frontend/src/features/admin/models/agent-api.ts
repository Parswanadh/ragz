import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { authFetch } from '@/api/client';

import type {
  ChatGptStatus,
  ModelTestResult,
  RuntimeModelsOut,
  RuntimeProvidersOut,
  WebConfig,
  WebConfigPatch,
  WebProviderTest,
} from '@/api/types';
export type {
  RuntimeProvider,
  RuntimeModel,
  ChatGptLogin,
  ChatGptStatus,
  WebProvider,
  WebConfig,
  WebConfigPatch,
} from '@/api/types';
export type TestResult = ModelTestResult & Partial<Pick<WebProviderTest, 'result_count'>>;

export async function agentRequest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await authFetch(
    new Request(`${window.location.origin}/api/v1${path}`, {
      method,
      credentials: 'include',
      headers: { 'content-type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    }),
  );
  // Server errors are sanitized RFC 9457 problems. Never reflect raw response bodies.
  if (!response.ok) throw new Error(`Request failed (${response.status}). Please try again.`);
  return response.json() as Promise<T>;
}

export function useRuntimeProviders() {
  return useQuery({
    queryKey: ['agent-catalog', 'providers'],
    staleTime: 10 * 60_000,
    queryFn: () => agentRequest<RuntimeProvidersOut>('/admin/models/catalog/providers'),
  });
}
export function useRuntimeModels(provider: string, mode: 'chat' | 'embedding') {
  return useQuery({
    queryKey: ['agent-catalog', 'models', provider, mode],
    staleTime: 10 * 60_000,
    queryFn: () =>
      agentRequest<RuntimeModelsOut>(
        `/admin/models/catalog/models?provider=${encodeURIComponent(provider)}&mode=${mode}`,
      ),
  });
}
export function useChatGptStatus() {
  return useQuery({
    queryKey: ['agent-chatgpt'],
    staleTime: 15_000,
    queryFn: () => agentRequest<ChatGptStatus>('/admin/models/chatgpt'),
  });
}
export function useTestModel() {
  return useMutation({
    mutationFn: (id: string) =>
      agentRequest<TestResult>(`/admin/models/${encodeURIComponent(id)}/test`, 'POST'),
  });
}
export function useWebConfig() {
  return useQuery({
    queryKey: ['agent-web-search'],
    queryFn: () => agentRequest<WebConfig>('/admin/web-search'),
  });
}
export function useSaveWebConfig() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: WebConfigPatch) =>
      agentRequest<WebConfig>('/admin/web-search', 'PATCH', body),
    onSuccess: (config) => {
      client.setQueryData(['agent-web-search'], config);
      void client.invalidateQueries({ queryKey: ['provider-settings'] });
    },
  });
}
