import { useEffect, useLayoutEffect, useId, useRef, useState } from 'react';
import { ChevronDown, Code2, Database, FlaskConical, Plus, Trophy } from 'lucide-react';

const options = [
  { id: 'notebooks', title: 'Notebook', hint: 'Write code and explore ideas', icon: Code2 },
  { id: 'datasets', title: 'Dataset', hint: 'Upload and share your data', icon: Database },
  {
    id: 'competitions',
    title: 'Competition',
    hint: 'Bring a challenge to the community',
    icon: Trophy,
  },
  {
    id: 'benchmarks',
    title: 'Benchmark',
    hint: 'Compare prediction performance',
    icon: FlaskConical,
  },
];

export default function CreateDropdown({
  onSelect,
  disabled = false,
}: {
  onSelect: (id: string) => void;
  disabled?: boolean;
}) {
  const menuId = useId();
  const menu = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    if (!open) {
      menu.current?.hidePopover();
      return;
    }
    const place = () => {
      const rect = trigger.current!.getBoundingClientRect();
      const height = menu.current!.offsetHeight;
      const width = menu.current!.offsetWidth;
      setPosition({
        left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
        top:
          rect.bottom + 6 + height <= window.innerHeight - 8
            ? rect.bottom + 6
            : Math.max(8, rect.top - height - 6),
      });
    };
    menu.current?.showPopover();
    place();
    const scroll = (event: Event) => {
      if (!menu.current?.contains(event.target as Node)) place();
    };
    window.addEventListener('resize', place);
    window.addEventListener('scroll', scroll, true);
    return () => {
      window.removeEventListener('resize', place);
      window.removeEventListener('scroll', scroll, true);
    };
  }, [open]);
  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, [open]);
  return (
    <div
      className="create-dropdown"
      ref={root}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
          trigger.current?.focus();
        }
        if (!open) return;
        const items = Array.from(
          root.current!.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'),
        );
        const index = items.indexOf(document.activeElement as HTMLButtonElement);
        let next: number | undefined;
        if (event.key === 'ArrowDown') next = (index + 1) % items.length;
        if (event.key === 'ArrowUp') next = (index + items.length - 1) % items.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = items.length - 1;
        if (next !== undefined) {
          event.preventDefault();
          items[next].focus();
        }
      }}
    >
      <button
        ref={trigger}
        disabled={disabled}
        className="create-button"
        aria-label="Create"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen(!open)}
      >
        <Plus size={20} /> Create <ChevronDown size={16} />
      </button>
      <div
        ref={menu}
        id={menuId}
        popover="auto"
        className="create-menu"
        role="menu"
        aria-label="Create category"
        style={position}
        onToggle={(event) => setOpen((event.nativeEvent as ToggleEvent).newState === 'open')}
      >
        <div className="create-menu-label">CREATE SOMETHING NEW</div>
        {options.map(({ id, title, hint, icon: Icon }) => (
          <button
            key={id}
            role="menuitem"
            aria-label={title}
            onClick={() => {
              setOpen(false);
              onSelect(id);
            }}
          >
            <Icon size={21} />
            <span>
              <strong>{title}</strong>
              <small>{hint}</small>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
