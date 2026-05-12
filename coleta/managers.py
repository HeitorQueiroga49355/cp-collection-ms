from django.db import models


class ImovelManager(models.Manager):
    def upsert_from_evento(self, payload: dict):
        iptu = payload['iptu']
        defaults = {
            'id_externo': payload.get('id_externo', ''),
            'logradouro': payload.get('logradouro', ''),
            'numero': payload.get('numero', ''),
            'bairro': payload.get('bairro', ''),
            'morador': payload.get('morador', ''),
            'elegivel': payload.get('elegivel', True),
            'ativo': payload.get('ativo', True),
        }
        return self.update_or_create(iptu=iptu, defaults=defaults)


class ColetaManager(models.Manager):
    def criar_idempotente(self, coleta_id, **dados):
        return self.get_or_create(coleta_id=coleta_id, defaults=dados)
