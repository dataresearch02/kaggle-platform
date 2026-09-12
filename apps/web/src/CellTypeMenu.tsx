import { useEffect, useId, useRef, useState } from 'react';
import { Check, ChevronDown, Code2, FileText, Type } from 'lucide-react';

type CellType = 'code' | 'markdown' | 'raw';
const choices = [
  { value: 'code', label: 'Code', description: 'Run Python code', icon: Code2 },
  { value: 'markdown', label: 'Markdown', description: 'Headings, notes, and tables', icon: Type },
  { value: 'raw', label: 'Raw', description: 'Unformatted text', icon: FileText },
] as const;

export default function CellTypeMenu({
  value,
  disabled,
  onChange,
}: {
  value: CellType;
  disabled: boolean;
  onChange: (value: CellType) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const id = useId();
  const selected = choices.find((choice) => choice.value === value)!;
  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
    const dismiss = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener('pointerdown', dismiss);
    return () => window.removeEventListener('pointerdown', dismiss);
  }, [open]);
  return (
    <div
      className="cell-type-control"
      ref={root}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <button
        ref={trigger}
        className="cell-type-trigger"
        aria-label={`Cell type: ${selected.label}`}
        aria-haspopup="menu"
        aria-expanded={open && !disabled}
        aria-controls={open ? id : undefined}
        disabled={disabled}
        onClick={() => setOpen(!open)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        {selected.label}
        <ChevronDown size={15} />
      </button>
      {open && !disabled && (
        <div
          ref={menu}
          id={id}
          className="cell-type-menu"
          role="menu"
          aria-label="Cell type"
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              event.stopPropagation();
              setOpen(false);
              trigger.current?.focus();
              return;
            }
            const items = Array.from(
              event.currentTarget.querySelectorAll<HTMLButtonElement>('button'),
            );
            const index = items.indexOf(document.activeElement as HTMLButtonElement);
            if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
              event.preventDefault();
              const next =
                event.key === 'Home'
                  ? 0
                  : event.key === 'End'
                    ? items.length - 1
                    : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
              items[next].focus();
            }
            if (event.key === 'Tab') setOpen(false);
          }}
        >
          {choices.map((choice) => (
            <button
              key={choice.value}
              role="menuitemradio"
              aria-checked={choice.value === value}
              tabIndex={-1}
              onClick={() => {
                onChange(choice.value);
                setOpen(false);
                trigger.current?.focus();
              }}
            >
              <choice.icon size={19} />
              <span>
                <strong>{choice.label}</strong>
                <small>{choice.description}</small>
              </span>
              {choice.value === value && <Check size={16} className="cell-type-check" />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
