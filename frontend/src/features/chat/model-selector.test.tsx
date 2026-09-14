import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';

import type { ModelPublic } from '@/api/types';

import { ModelSelector } from './model-selector';
import type { ReasoningEffort } from './effort-selector';

const models: ModelPublic[] = [
  {
    id: 'plan',
    display_name: 'GPT Luna',
    model_name: 'chatgpt/gpt-5.6-luna',
    billing_mode: 'subscription',
    provider_kind: 'litellm',
    supports_vision: true,
    supports_reasoning: true,
    default_reasoning_effort: 'high',
    supported_reasoning_efforts: ['off', 'low', 'high', 'xhigh', 'max', 'ultra'],
  },
  {
    id: 'api',
    display_name: 'Future API',
    model_name: 'novel/bright-9',
    supports_reasoning: false,
    supports_vision: false,
    provider_kind: 'litellm',
    billing_mode: 'metered',
    default_reasoning_effort: 'off',
    supported_reasoning_efforts: [],
  },
];

function Picker({ disabled = false }: { disabled?: boolean }) {
  const [model, setModel] = useState<string | null>('plan');
  const [effort, setEffort] = useState<ReasoningEffort | null>('high');
  return (
    <>
      <ModelSelector
        models={models}
        value={model}
        onChange={setModel}
        effort={effort}
        onEffortChange={setEffort}
        disabled={disabled}
      />
      <output aria-label="Selected effort">{effort ?? 'no override'}</output>
    </>
  );
}

test('Default clears the override, extended supported efforts stay available, and model search chooses the next model', async () => {
  const user = userEvent.setup();
  render(<Picker />);
  await user.click(screen.getByRole('button', { name: /Model and reasoning/ }));
  expect(screen.getByRole('menuitemradio', { name: /Ultra/ })).toBeInTheDocument();
  expect(screen.queryByRole('menuitemradio', { name: /^Medium/ })).not.toBeInTheDocument();
  await user.click(screen.getByRole('menuitemradio', { name: /^Default/ }));
  expect(screen.getByLabelText('Selected effort')).toHaveTextContent('no override');
  await user.click(screen.getByRole('button', { name: /Model and reasoning/ }));
  await user.click(screen.getByRole('menuitem', { name: /Model/ }));
  const search = await screen.findByRole('searchbox', { name: 'Search models' });
  await user.click(search);
  expect(search).toHaveFocus();
  await user.keyboard('novel/bright');
  expect(search).toHaveValue('novel/bright');
  await user.click(screen.getByRole('menuitemradio', { name: /Future API/ }));
  expect(screen.getByRole('button', { name: /Model and reasoning/ })).toHaveTextContent(
    'Future API',
  );
});

test('the single picker cannot change a running turn', () => {
  render(<Picker disabled />);
  expect(screen.getByRole('button', { name: /Model and reasoning/ })).toBeDisabled();
});
