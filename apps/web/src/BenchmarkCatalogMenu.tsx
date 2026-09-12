import { useEffect, useLayoutEffect, useId, useRef, useState } from 'react';
import { Check, ChevronDown, Layers3, Table2 } from 'lucide-react';

const options = [
  { id: 'models', title: 'Models', hint: 'Local models and API providers', icon: Layers3 },
  {
    id: 'legacy',
    title: 'CSV benchmarks',
    hint: 'Prediction benchmarks and leaderboards',
    icon: Table2,
  },
] as const;

export default function BenchmarkCatalogMenu({
  value,
  onSelect,
}: {
  value: string;
  onSelect: (id: string) => void;
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
    (
      menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]') ||
      menu.current?.querySelector<HTMLButtonElement>('button')
    )?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, [open]);
  return (
    <div
      className="benchmark-catalog-menu"
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
        if (event.key === 'Tab') setOpen(false);
        if (!open) return;
        const items = Array.from(
          root.current!.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]'),
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
        className="button secondary benchmark-catalog-trigger"
        aria-label="Also explore"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen(!open)}
        onKeyDown={(event) => {
          if (!open && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
            event.preventDefault();
            event.stopPropagation();
            setOpen(true);
          }
        }}
      >
        {options.find((option) => option.id === value)?.title || 'Models & CSV benchmarks'}
        <ChevronDown size={16} />
      </button>
      <div
        ref={menu}
        id={menuId}
        popover="auto"
        className="create-menu benchmark-catalog-options"
        role="menu"
        aria-label="Other benchmark catalogs"
        style={position}
        onToggle={(event) => setOpen((event.nativeEvent as ToggleEvent).newState === 'open')}
      >
        <div className="create-menu-label">ALSO EXPLORE</div>
        {options.map(({ id, title, hint, icon: Icon }) => (
          <button
            key={id}
            role="menuitemradio"
            aria-checked={id === value}
            tabIndex={-1}
            aria-label={title}
            onClick={() => {
              setOpen(false);
              onSelect(id);
              trigger.current?.focus();
            }}
          >
            <Icon size={21} />
            <span>
              <strong>{title}</strong>
              <small>{hint}</small>
            </span>
            {id === value && <Check size={17} className="benchmark-catalog-check" />}
          </button>
        ))}
      </div>
    </div>
  );
}
