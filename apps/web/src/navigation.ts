import {
  FolderOpen,
  Home,
  Trophy,
  FlaskConical,
  Database,
  Layers3,
  Code2,
  GraduationCap,
  MessageSquare,
} from 'lucide-react';

export type Page =
  | 'work'
  | 'home'
  | 'competitions'
  | 'benchmarks'
  | 'datasets'
  | 'notebooks'
  | 'models'
  | 'courses'
  | 'discussions';
export const nav = [
  { id: 'home', label: 'Overview', icon: Home },
  { id: 'competitions', label: 'Competitions', icon: Trophy },
  { id: 'benchmarks', label: 'Benchmarks', icon: FlaskConical },
  { id: 'datasets', label: 'Datasets', icon: Database },
  { id: 'models', label: 'Models', icon: Layers3 },
  { id: 'notebooks', label: 'Codes', icon: Code2 },
  { id: 'courses', label: 'Learn', icon: GraduationCap },
  { id: 'discussions', label: 'Discussions', icon: MessageSquare },
  { id: 'work', label: 'Your work', icon: FolderOpen },
] as const;
export const dataHubPages: readonly Page[] = ['datasets', 'models', 'notebooks'];

export const morePages: readonly Page[] = ['courses', 'discussions'];
