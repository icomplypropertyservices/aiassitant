import json
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from .. import models
from ..auth_utils import get_current_user

router = APIRouter(prefix="/templates", tags=["templates"])

@router.get("/")
def list_templates(db: Session = Depends(get_db), user=Depends(get_current_user)):
    out = []
    for t in db.query(models.AgentTemplate).all():
        out.append({"id": t.id, "name": t.name, "type": t.type, "description": t.description,
                    "unique_fields": json.loads(t.unique_fields), "est_cost": t.est_cost})
    return out
