from fastapi import APIRouter,Depends
from ..config.database import db_session
from ..schemas.relation import RelationInput,RelationRevoke
from ..services.auth import current_user,writer
from ..controllers.relations import RelationsController as C
router=APIRouter()
@router.get('/relations')
def relations(db=Depends(db_session),u=Depends(current_user)):return C.list(db)
@router.post('/relations')
def add(data:RelationInput,db=Depends(db_session),u=Depends(writer)):return C.add(db,u,data)
@router.post('/relations/{id}/revoke')
def revoke(id:int,data:RelationRevoke,db=Depends(db_session),u=Depends(writer)):return C.revoke(db,u,id,data.reason)
