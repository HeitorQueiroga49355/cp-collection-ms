from django.db import models


class ImovelManager(models.Manager):
    def upsert_from_evento(self, payload: dict):
        inscricao = payload['inscricao_imobiliaria']
        defaults = {
            # O Core ainda não envia IPTU; usa a inscrição como placeholder
            # para satisfazer a unicidade do campo.
            'iptu': payload.get('iptu') or inscricao,
            'logradouro': payload.get('endereco', ''),
            'numero': payload.get('numero', ''),
            'complemento': payload.get('complemento', ''),
            'bairro': payload.get('bairro', ''),
            'morador': payload.get('nome', ''),
            'telefone': payload.get('telefone', ''),
            'elegivel': payload.get('elegivel', True),
            'motivo_inelegivel': payload.get('motivo_inelegivel', ''),
            'ativo': payload.get('ativo', True),
        }
        return self.update_or_create(id_externo=inscricao, defaults=defaults)


class ColetaManager(models.Manager):
    def criar_idempotente(self, coleta_id, **dados):
        return self.get_or_create(coleta_id=coleta_id, defaults=dados)
