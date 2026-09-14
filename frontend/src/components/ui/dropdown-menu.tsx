import * as Menu from '@radix-ui/react-dropdown-menu';
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from 'react';

import { cn } from '@/lib/cn';

export const DropdownMenu = Menu.Root;
export const DropdownMenuTrigger = Menu.Trigger;
export const DropdownMenuSub = Menu.Sub;
export const DropdownMenuRadioGroup = Menu.RadioGroup;

export const DropdownMenuRadioItem = forwardRef<
  ElementRef<typeof Menu.RadioItem>,
  ComponentPropsWithoutRef<typeof Menu.RadioItem>
>(({ className, ...props }, ref) => (
  <Menu.RadioItem
    ref={ref}
    className={cn(
      'flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-[13px] text-ink outline-none data-[highlighted]:bg-subtle data-[state=checked]:bg-subtle data-[disabled]:opacity-50',
      className,
    )}
    {...props}
  />
));
DropdownMenuRadioItem.displayName = 'DropdownMenuRadioItem';
export const DropdownMenuSubTrigger = forwardRef<
  ElementRef<typeof Menu.SubTrigger>,
  ComponentPropsWithoutRef<typeof Menu.SubTrigger>
>(({ className, ...props }, ref) => (
  <Menu.SubTrigger
    ref={ref}
    className={cn(
      'flex cursor-default select-none items-center justify-between gap-2 rounded-sm px-2 py-1.5 text-[13px] text-ink outline-none data-[highlighted]:bg-subtle data-[state=open]:bg-subtle',
      className,
    )}
    {...props}
  />
));
DropdownMenuSubTrigger.displayName = 'DropdownMenuSubTrigger';
export const DropdownMenuSubContent = forwardRef<
  ElementRef<typeof Menu.SubContent>,
  ComponentPropsWithoutRef<typeof Menu.SubContent>
>(({ className, ...props }, ref) => (
  <Menu.Portal>
    <Menu.SubContent
      ref={ref}
      className={cn(
        'z-50 min-w-[220px] rounded-md border border-line bg-bg p-1 shadow-md',
        className,
      )}
      {...props}
    />
  </Menu.Portal>
));
DropdownMenuSubContent.displayName = 'DropdownMenuSubContent';

export const DropdownMenuContent = forwardRef<
  ElementRef<typeof Menu.Content>,
  ComponentPropsWithoutRef<typeof Menu.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <Menu.Portal>
    <Menu.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        'z-50 min-w-[180px] rounded-md border border-line bg-bg p-1 shadow-md',
        'data-[state=open]:animate-menu-in',
        className,
      )}
      {...props}
    />
  </Menu.Portal>
));
DropdownMenuContent.displayName = 'DropdownMenuContent';

export const DropdownMenuItem = forwardRef<
  ElementRef<typeof Menu.Item>,
  ComponentPropsWithoutRef<typeof Menu.Item>
>(({ className, ...props }, ref) => (
  <Menu.Item
    ref={ref}
    className={cn(
      'cursor-default select-none rounded-sm px-2 py-1.5 text-[13px] text-ink outline-none',
      'transition-colors duration-150 ease-out data-[highlighted]:bg-subtle data-[disabled]:opacity-50',
      className,
    )}
    {...props}
  />
));
DropdownMenuItem.displayName = 'DropdownMenuItem';

export const DropdownMenuSeparator = ({ className }: { className?: string }) => (
  <Menu.Separator className={cn('my-1 h-px bg-line-faint', className)} />
);
