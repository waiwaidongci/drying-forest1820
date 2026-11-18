from ..services import relations
class RelationsController:
    list=staticmethod(relations.list_relations)
    add=staticmethod(relations.add_relation)
    revoke=staticmethod(relations.revoke_relation)
