from pydantic import BaseModel,Field
class RelationInput(BaseModel):
    left_source_id:int
    right_source_id:int
    reason:str=Field(default='',max_length=2000)
class RelationRevoke(BaseModel):
    reason:str=Field(default='',max_length=2000)
