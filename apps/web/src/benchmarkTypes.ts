export type Asset = {
  id: number;
  kind: 'task' | 'model';
  owner_id: number;
  owner?: string;
  title: string;
  description: string;
  visibility: 'public' | 'private';
  version_id: number;
  digest: string;
  provider_id?: string | null;
  source?: string;
  cases?: Record<string, unknown>[];
  versions?: { id: number; source: string; cases: Record<string, unknown>[]; digest: string }[];
};
export type Collection = {
  id: number;
  owner_id: number;
  owner?: string;
  title: string;
  description: string;
  visibility: 'public' | 'private';
  tasks: number[];
  models: number[];
  fingerprint: string;
  top_models?: { model: string; score: number }[];
  task_details: Asset[];
  model_details: Asset[];
};
export type Result = {
  model_version_id: number;
  task_version_id: number;
  model: string;
  task: string;
  status: string;
  score: number | null;
  duration_ms: number;
  error: string;
  cases: {
    index: number;
    input: unknown;
    outputs: { input: string; output: unknown }[];
    score: number | null;
    error: string;
    duration_ms: number;
  }[];
};
export type Run = {
  id: number;
  collection_id: number;
  status: string;
  fingerprint: string;
  error: string;
  created_at: string;
  finished_at: string | null;
  results?: Result[];
  logs?: string;
};
export type Board = {
  items: {
    rank: number | null;
    model: string;
    model_version_id: number;
    score: number | null;
    completed_tasks: number;
    total_tasks: number;
    tasks: Result[];
    run_id: number;
  }[];
  aggregation: string;
};
export const taskExample = `def evaluate(model, case) -> bool:
    """Compare the model's response with the expected answer."""
    response = model.prompt(case["prompt"])
    return str(response).strip().lower() == str(case["expected"]).strip().lower()
`;
export const modelExample = `def predict(prompt):
    """Local echo baseline for testing the evaluation workflow, not an AI model."""
    return prompt
`;
