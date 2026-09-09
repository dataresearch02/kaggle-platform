import { useEffect, useRef, useState } from 'react';
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

export default function CreateDropdown({ onSelect }: { onSelect: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
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
        className="create-button"
        aria-label="Create"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="create-menu"
        onClick={() => setOpen(!open)}
      >
        <Plus size={20} /> Create <ChevronDown size={16} />
      </button>
      {open && (
        <div id="create-menu" className="create-menu" role="menu" aria-label="Create category">
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
      )}
    </div>
  );
}
