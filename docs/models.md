# Models

A model has a Markdown model card and one or more **variations**. A variation is a framework plus a variation name, such as PyTorch `base` or GGUF `q4`, and has its own immutable, numbered versions. Versions, previews, chunked uploads and quotas work exactly as for [datasets](datasets.md).

## Model cards

New models start with a card template containing the sections Overview (prefilled with the description), Intended use, Training data, Evaluation, Limitations & bias, License and How to use. Owners and administrators edit the card on the model page; it is rendered with the sanitized Markdown component. Models created before cards existed show their description until someone edits the card.

## Variations

- Frameworks: PyTorch, TensorFlow / Keras, JAX, scikit-learn, ONNX, Transformers, GGUF and Other.
- Variation names use lowercase letters, numbers and hyphens (up to 40 characters) and are unique per model and framework. A model can have up to 100 variations.
- Creating a model adds a `default` variation for the framework chosen on the form. Owners and administrators add more variations and delete them; deleting a variation removes all its versions and frees their storage.

## Versions

Each variation has versions 1, 2, … with files, a version note, creator and time. Create a draft (optionally carrying over the latest version's files), upload files in resumable chunks, then publish with a note. Numbers are never reused. Visibility follows the model: models are listed publicly unless moderators hide them, in which case only the owner and administrators can see the model, its variations and its files.

The single-request `POST /api/assets/models/<id>` endpoint (one file up to 10 MB) still works and publishes the next version of the model's first variation.

### Upgrading existing data

Migration `0014_resource_versions_backfill` gives every existing model a `default` variation, with the framework mapped from its free-text framework (for example "Torch" becomes PyTorch and "Keras" becomes TensorFlow / Keras; unknown values become Other). Models with hosted files also get version 1 containing the newest file of each path. It runs once; re-runs change nothing. Reference-only model cards keep working and simply have no versions.

## Using a model in a notebook

- On the model page, each variation with a published version shows its notebook folder, a copyable Python snippet and **New notebook with this variation**. In the editor, **Add Input → Models** attaches the first variation that has files.
- The latest version is pinned when attached; choose **Always latest** or another version in the notebook's input panel. The reference stores `variation_id` and `version` (format 3).
- Files are copied read-only to `input/<model-slug>-<framework>-<variation>-model-<id>/<path>`, in interactive sessions (up to 200 MB or 1,000 files per source), Save & Run All, scheduled runs and competition commits. Background jobs stream up to `JOB_INPUT_MAX_BYTES` per source and check access again when they start.

A typical snippet for a PyTorch variation:

```python
from pathlib import Path

model_dir = Path("input/tiny-net-pytorch-base-model-7")
for path in sorted(model_dir.rglob('*')):
    if path.is_file():
        print(path, path.stat().st_size)

import torch
state = torch.load(model_dir / "weights.pt", map_location="cpu", weights_only=True)
```

The cluster is disconnected: loaders must read local files (for example `local_files_only=True` for Transformers).

## API

| Method and path | Purpose |
| --- | --- |
| `GET /api/models/<id>` | Model with `card`, `variations` and `input_available` |
| `PUT /api/models/<id>/card` | Replace the Markdown card (`{"card": "…"}`) |
| `GET /api/models/<id>/variations` | Variations with latest version, input folder and snippet |
| `POST /api/models/<id>/variations` | Create a variation (`{"framework": "pytorch", "slug": "base", "description": ""}`) |
| `DELETE /api/models/<id>/variations/<variation_id>` | Delete a variation with its versions |
| `GET /api/models/<id>/variations/<variation_id>/versions` | Published versions, plus the draft for managers |
| `GET /api/models/<id>/variations/<variation_id>/versions/<number\|latest\|draft>[/files]` | One version, or its paginated files |
| `POST /api/models/<id>/variations/<variation_id>/versions` | Create or return the draft (`{"carry_over": true}`) |
| `POST …/versions/draft/publish`, `DELETE …/versions/draft`, `DELETE …/versions/draft/files/<file_id>`, `DELETE …/versions/<number>` | Publish, discard, edit and delete, as for datasets |
| `GET /api/models/<id>/files/<file_id>/download`, `/preview`, `/raw` | Download, preview and inline images for any version file |

Uploads use `POST /api/uploads` with the variation's draft `version_id`; see [datasets](datasets.md#uploads).
