from fastapi import HTTPException
from sqlalchemy import select, or_
from .models import Notebook, NotebookWorkingCopy, NotebookShare


def visible_notebooks(user):
    private = select(NotebookWorkingCopy.notebook_id).where(
        NotebookWorkingCopy.private == 1
    )
    return or_(
        Notebook.id.not_in(private),
        Notebook.owner_id == (user.id if user else -1),
        Notebook.id.in_(
            select(NotebookShare.notebook_id).where(
                NotebookShare.user_id == (user.id if user else -1)
            )
        ),
    )


def require_visible(db, id, user):
    row = db.scalar(select(Notebook).where(Notebook.id == id, visible_notebooks(user)))
    if not row:
        raise HTTPException(404, "Notebook not found")
    return row


def published_code(db, notebook):
    """Legacy public summaries must use the publication, never saved private edits."""
    import json
    from .models import NotebookPublication

    publication = db.get(NotebookPublication, notebook.id)
    if not publication:
        return notebook.code
    return "\n\n".join(
        "".join(cell.get("source", ""))
        for cell in json.loads(publication.document)["cells"]
        if cell["cell_type"] == "code"
    )
