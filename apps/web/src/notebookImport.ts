import type { Cell, Document } from './NotebookWorkspace';

const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown) =>
  typeof value === 'string' ||
  (Array.isArray(value) && value.every((line) => typeof line === 'string'));

/** Import document content only; foreign Arena attachments are not access grants. */
export function parseNotebook(source: string): Document {
  let value: unknown;
  try {
    value = JSON.parse(source);
  } catch {
    throw new Error('This file is not valid notebook JSON.');
  }
  if (!object(value) || value.nbformat !== 4 || !Array.isArray(value.cells))
    throw new Error('Choose a Jupyter notebook in nbformat 4 format.');
  if (value.cells.length > 500) throw new Error('Import supports up to 500 cells.');
  const metadata = object(value.metadata) ? value.metadata : {};
  const kernel = object(metadata.kernelspec) ? metadata.kernelspec : {};
  if (typeof kernel.language === 'string' && kernel.language.toLowerCase() !== 'python')
    throw new Error('This editor supports Python notebooks.');
  const cells = value.cells.map((cell, index) => {
    const invalid = () => new Error(`Cell ${index + 1} contains invalid notebook content.`);
    if (
      !object(cell) ||
      !['code', 'markdown', 'raw'].includes(String(cell.cell_type)) ||
      !text(cell.source)
    )
      throw invalid();
    if (cell.cell_type === 'code') {
      if (
        cell.outputs !== undefined &&
        (!Array.isArray(cell.outputs) ||
          cell.outputs.some((output: unknown) => {
            if (
              !object(output) ||
              !['stream', 'display_data', 'execute_result', 'error'].includes(
                String(output.output_type),
              )
            )
              return true;
            if (output.text !== undefined && !text(output.text)) return true;
            if (
              output.data !== undefined &&
              (!object(output.data) ||
                Object.entries(output.data).some(
                  ([mime, data]) => mime !== 'application/json' && !text(data),
                ))
            )
              return true;
            if (
              output.traceback !== undefined &&
              (!Array.isArray(output.traceback) ||
                !output.traceback.every((line: unknown) => typeof line === 'string'))
            )
              return true;
            return ['ename', 'evalue'].some(
              (key) => output[key] !== undefined && typeof output[key] !== 'string',
            );
          }))
      )
        throw invalid();
    }
    return {
      id: crypto.randomUUID(),
      cell_type: cell.cell_type,
      source: cell.source,
      metadata: object(cell.metadata) ? cell.metadata : {},
      ...(cell.cell_type === 'code'
        ? {
            outputs: cell.outputs ?? [],
            execution_count: Number.isInteger(cell.execution_count) ? cell.execution_count : null,
          }
        : {}),
    } as Cell;
  });
  return {
    nbformat: 4,
    nbformat_minor: 5,
    metadata: { kernelspec: { name: 'python3', display_name: 'Python 3', language: 'python' } },
    cells,
  };
}
