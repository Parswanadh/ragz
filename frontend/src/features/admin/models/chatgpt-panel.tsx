import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ExternalLink } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogFooter } from '@/components/ui/dialog';
import { QueryError } from '@/components/ui/query-error';
import { Spinner } from '@/components/ui/spinner';
import { StatusPill } from '@/components/ui/status-pill';

import { agentRequest, type ChatGptLogin, type ChatGptStatus, useChatGptStatus } from './agent-api';

export function ChatGptPanel() {
  const status = useChatGptStatus();
  const client = useQueryClient();
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const applyLogin = (login: ChatGptLogin) => {
    client.setQueryData<ChatGptStatus>(['agent-chatgpt'], (previous) =>
      previous ? { ...previous, login } : previous,
    );
    if (login.state === 'authorised')
      void client.invalidateQueries({ queryKey: ['agent-chatgpt'] });
  };
  const action = useMutation({
    mutationFn: async (kind: 'connect' | 'cancel' | 'disconnect') => {
      // Finish any pending local poll before changing the server login state.
      await client.cancelQueries({ queryKey: ['agent-chatgpt-poll'] });
      if (kind === 'disconnect')
        return agentRequest<ChatGptStatus>('/admin/models/chatgpt', 'DELETE');
      return agentRequest<ChatGptLogin>(
        '/admin/models/chatgpt/login',
        kind === 'connect' ? 'POST' : 'DELETE',
      );
    },
    onSuccess: (next) => {
      if ('connected' in next) client.setQueryData(['agent-chatgpt'], next);
      else applyLogin(next);
      setConfirmDisconnect(false);
    },
  });
  const login = status.data?.login;
  const poll = useQuery({
    queryKey: ['agent-chatgpt-poll', login?.login_id],
    enabled: login?.state === 'pending' && !!login.login_id && !action.isPending,
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: login?.state === 'pending' ? Math.max(login.interval, 1) * 1000 : false,
    queryFn: async ({ signal }) => {
      const result = await agentRequest<ChatGptLogin>('/admin/models/chatgpt/poll', 'POST', {
        login_id: login?.login_id,
      });
      // A cancelled query may still complete at the transport boundary. It must
      // not restore a code after cancellation or disconnect.
      if (!signal.aborted) applyLogin(result);
      return result;
    },
  });
  const connecting = login?.state === 'pending';
  const connected = status.data?.connected;
  const failed = login?.state === 'failed' || login?.state === 'expired';
  let verificationUrl: string | null = null;
  try {
    const url = new URL(login?.verification_url ?? '');
    if (url.protocol === 'https:') verificationUrl = url.href;
  } catch {
    /* No pending URL. */
  }
  return (
    <section
      aria-labelledby="chatgpt-heading"
      className="space-y-4 rounded-lg border border-line bg-bg p-4 sm:p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 id="chatgpt-heading" className="text-base font-semibold text-ink">
            ChatGPT subscription
          </h2>
          <p className="max-w-2xl text-sm text-secondary">
            Connect your ChatGPT plan to run subscription models on this instance. Sign in with a
            device code; no API key is needed.
          </p>
        </div>
        <StatusPill tone={connected ? 'success' : 'muted'}>
          {connecting ? 'Connecting' : connected ? 'Connected' : 'Not connected'}
        </StatusPill>
      </div>
      {status.isPending ? <Spinner label="Loading ChatGPT connection…" /> : null}
      {status.isError ? <QueryError error={status.error} onRetry={() => status.refetch()} /> : null}
      {status.data?.available === false ? (
        <p role="status" className="text-sm text-secondary">
          ChatGPT sign-in is unavailable on this server.
        </p>
      ) : null}
      {connecting ? (
        <div className="space-y-3">
          <p className="text-sm text-secondary">Enter this code on the sign-in page:</p>
          <div className="flex flex-wrap items-center gap-3">
            <code className="rounded-md border border-line bg-subtle px-4 py-2 text-lg tracking-widest text-ink">
              {login.user_code}
            </code>
            <Button
              size="sm"
              onClick={() => {
                if (login.user_code) void navigator.clipboard.writeText(login.user_code);
              }}
            >
              Copy code
            </Button>
            {verificationUrl ? (
              <a
                href={verificationUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-sm text-accent underline"
              >
                Open sign-in page
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              </a>
            ) : null}
          </div>
          {login.expires_at ? (
            <p className="text-xs text-muted">
              Expires {new Date(login.expires_at * 1000).toLocaleTimeString()} · Waiting for
              approval
            </p>
          ) : null}
          <Button size="sm" disabled={action.isPending} onClick={() => action.mutate('cancel')}>
            Cancel sign-in
          </Button>
        </div>
      ) : connected ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-sm text-secondary">
            {status.data?.email ?? status.data?.account_id ?? 'ChatGPT account'}
            {status.data?.plan_type ? (
              <span className="ml-2 capitalize">{status.data.plan_type}</span>
            ) : null}
            <p className="mt-1 text-xs text-muted">
              Subscription models are available in the provider catalog below.
            </p>
          </div>
          <Button size="sm" disabled={action.isPending} onClick={() => setConfirmDisconnect(true)}>
            Disconnect
          </Button>
        </div>
      ) : status.data?.available ? (
        <div className="space-y-3">
          {failed ? (
            <p role="alert" className="text-sm text-danger">
              {login?.state === 'expired'
                ? 'The sign-in code expired. Start again to get a new code.'
                : (login?.error ?? 'Sign-in failed. Please try again.')}
            </p>
          ) : null}
          <Button
            variant="primary"
            size="sm"
            disabled={action.isPending}
            onClick={() => action.mutate('connect')}
          >
            {action.isPending ? 'Connecting…' : 'Connect ChatGPT'}
          </Button>
          <p className="text-xs text-muted">
            Model access depends on your account. Use Test beside a registered model to check it.
          </p>
        </div>
      ) : null}
      {action.isError ? (
        <p role="alert" className="text-sm text-danger">
          {action.error.message}
        </p>
      ) : null}
      {poll.isError && connecting ? (
        <p role="alert" className="text-sm text-danger">
          Could not check sign-in. Retrying while the code remains active.
        </p>
      ) : null}
      <Dialog open={confirmDisconnect} onOpenChange={setConfirmDisconnect}>
        <DialogContent
          title="Disconnect ChatGPT"
          description="The saved connection will be removed. Registered models stay available to reconnect later."
        >
          <DialogFooter>
            <Button onClick={() => setConfirmDisconnect(false)}>Cancel</Button>
            <Button
              variant="danger"
              disabled={action.isPending}
              onClick={() => action.mutate('disconnect')}
            >
              Disconnect ChatGPT
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
