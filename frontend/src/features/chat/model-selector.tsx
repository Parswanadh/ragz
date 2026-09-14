import { Check, ChevronDown, ChevronRight } from 'lucide-react';
import { useState } from 'react';

import type { ModelPublic } from '@/api/types';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';

import type { ReasoningEffort } from './effort-selector';

const EFFORTS: { value: ReasoningEffort; label: string; hint: string }[] = [
  { value: 'off', label: 'Off', hint: 'no override' },
  { value: 'low', label: 'Low', hint: 'fastest' },
  { value: 'medium', label: 'Medium', hint: 'balanced' },
  { value: 'high', label: 'High', hint: 'deeper' },
  { value: 'xhigh', label: 'Extra high', hint: 'more thorough' },
  { value: 'max', label: 'Max', hint: 'maximum effort' },
  { value: 'ultra', label: 'Ultra', hint: 'most thorough' },
];

export function ModelSelector({
  models,
  value,
  onChange,
  effort = null,
  onEffortChange,
  disabled = false,
}: {
  // GET /api/v1/models already returns only enabled models (ModelPublic —
  // no `enabled` field to re-filter on; see api/types.ts).
  models: ModelPublic[];
  value: string | null;
  onChange: (id: string) => void;
  effort?: ReasoningEffort | null;
  onEffortChange?: (effort: ReasoningEffort | null) => void;
  disabled?: boolean;
}) {
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState(false);
  const [subOpen, setSubOpen] = useState(false);
  const selected = models.find((model) => model.id === value) ?? models[0];
  const supported = selected?.supported_reasoning_efforts ?? ['off', 'low', 'medium', 'high'];
  const choices = selected?.supports_reasoning
    ? EFFORTS.filter((option) => supported.includes(option.value))
    : [];
  const filtered = models.filter((model) =>
    `${model.display_name} ${model.model_name ?? ''}`.toLowerCase().includes(search.toLowerCase()),
  );
  const effortLabel =
    effort === null
      ? 'Default'
      : (EFFORTS.find((option) => option.value === effort)?.label ?? effort);
  const subscription = (model: ModelPublic | undefined) =>
    model?.billing_mode === 'subscription' || model?.model_name?.startsWith('chatgpt/');
  return (
    <DropdownMenu
      open={open && !disabled}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setSearch('');
          setSubOpen(false);
        }
      }}
    >
      <DropdownMenuTrigger asChild>
        <Button
          variant="secondary"
          size="sm"
          disabled={disabled || !models.length}
          aria-label="Model and reasoning"
          className="h-8 min-w-0 max-w-full gap-1.5 px-2.5 font-normal sm:max-w-[360px]"
        >
          <span className="min-w-0 max-w-48 truncate">{selected?.display_name ?? 'No models'}</span>
          {subscription(selected) ? (
            <StatusPill tone="accent" className="hidden shrink-0 sm:inline-flex">
              ChatGPT plan
            </StatusPill>
          ) : null}
          {selected?.supports_reasoning ? (
            <span className="shrink-0 text-xs text-muted">{effortLabel}</span>
          ) : null}
          <ChevronDown className="h-3.5 w-3.5 shrink-0" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" side="top" className="w-64">
        <p className="px-2 py-1 text-xs font-medium text-muted">Reasoning effort</p>
        <DropdownMenuRadioGroup
          value={effort ?? 'default'}
          onValueChange={(next) => {
            if (!disabled) onEffortChange?.(next === 'default' ? null : (next as ReasoningEffort));
          }}
        >
          <DropdownMenuRadioItem value="default">
            <span className="flex-1">Default</span>
            <span className="text-xs text-muted">the model’s own</span>
          </DropdownMenuRadioItem>
          {choices.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              <span className="flex-1">{option.label}</span>
              <span className="text-xs text-muted">{option.hint}</span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {!selected?.supports_reasoning ? (
          <p className="px-2 py-1 text-xs text-muted">This model has no reasoning override.</p>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuSub
          open={subOpen}
          onOpenChange={(next) => {
            setSubOpen(next);
            if (!next) setSearch('');
          }}
        >
          {/* Preserve focus when the pointer enters the submenu search field. */}
          <DropdownMenuSubTrigger onPointerLeave={(event) => event.preventDefault()}>
            <span>Model</span>
            <span className="ml-auto max-w-36 truncate text-xs text-muted">
              {selected?.display_name}
            </span>
            <ChevronRight className="h-3.5 w-3.5" aria-hidden />
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="w-80 max-w-[90vw]">
            <div className="p-1">
              <Input
                type="search"
                aria-label="Search models"
                placeholder="Search models"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key !== 'Escape' && event.key !== 'Tab' && event.key !== 'ArrowDown')
                    event.stopPropagation();
                }}
              />
            </div>
            <DropdownMenuRadioGroup
              value={selected?.id}
              onValueChange={(id) => {
                if (!disabled) onChange(id);
              }}
              className="max-h-80 overflow-y-auto"
            >
              {filtered.map((model) => (
                <DropdownMenuRadioItem key={model.id} value={model.id}>
                  <span className="w-3.5 shrink-0">
                    {selected?.id === model.id ? (
                      <Check className="h-3.5 w-3.5" aria-hidden />
                    ) : null}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{model.display_name}</span>
                  {subscription(model) ? <StatusPill tone="accent">ChatGPT plan</StatusPill> : null}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
            {!filtered.length ? (
              <p className="p-3 text-xs text-secondary">No models match.</p>
            ) : null}
          </DropdownMenuSubContent>
        </DropdownMenuSub>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
