# Roteiro de Apresentação: Fluxo End-to-End (Core ↔ Microsserviço)

Este documento detalha o passo a passo para reproduzir o fluxo completo de comunicação assíncrona entre o **Sistema Core** (Postgres) e o **Microsserviço de Coletas** (MongoDB) através do RabbitMQ.

## 🛠 Pré-requisitos
1. Ambos os projetos devem estar em execução via Docker Compose (`docker-compose up -d`).
2. Os serviços que precisam estar acessíveis:
   - **Core HTTP:** `http://localhost:8001`
   - **Microsserviço HTTP:** `http://localhost:8002`
   - **RabbitMQ:** (Filas `imoveis` e `coletas` criadas).
3. Tenha um utilitário como **Insomnia** ou **Postman** (você pode importar o arquivo `insomnia_collection.json` na raiz do projeto).

---

## 🟢 Passo 1: Autenticação nas duas pontas

Para realizar as requisições, precisamos estar autenticados de acordo com os papéis de cada sistema.

### 1.1. Login no Core (Gestor / Supervisor / Morador)
Farei um POST para obter o Token JWT para criar imóveis.
- **Endpoint:** `POST http://localhost:8001/api/accounts/token/`
- **Payload:**
```json
{
  "email": "seu_usuario_admin@test.com",
  "password": "sua_senha"
}
```
> **Nota:** Extraia o `access` token devolvido. Ele será usado em `Authorization: Bearer <CORE_TOKEN>`.

### 1.2. Login no Microsserviço (Coletor)
Farei um POST para logar com o coletor que registrará o lixo reciclável no app.
- **Endpoint:** `POST http://localhost:8002/api/auth/login`
- **Payload:**
```json
{
  "username": "matricula_coletor",
  "password": "sua_senha"
}
```
> **Nota:** Extraia o `access` token devolvido. Ele será usado em `Authorization: Bearer <MS_TOKEN>`.

---

## ➡️ Passo 2: Core ➝ Microsserviço (Sincronização de Imóveis)

Vamos cadastrar um imóvel no Core. Este evento deve ser publicado na fila `imoveis` e consumido pelo MS.

### 2.1. Criar imóvel no Core
- **Endpoint:** `POST http://localhost:8001/api/program/properties`
- **Headers:** `Authorization: Bearer <CORE_TOKEN>`
- **Payload:**
```json
{
  "iptu": "999888777",
  "logradouro": "Rua da Apresentação",
  "numero": "123",
  "bairro": "Centro",
  "elegivel": true
}
```
*Observe a resposta: O Core salvará no Postgres e emitirá o ID gerado (Ex: id=15). O RabbitMQ publicará esse evento.*

### 2.2. Verificar a Propagação no Microsserviço
Neste momento, o consumer do Microsserviço (rodando em background) interceptará a mensagem da fila `imoveis` e salvará no MongoDB. Vamos pesquisar esse imóvel no MS:
- **Endpoint:** `GET http://localhost:8002/api/imoveis/buscar?tipo=qrcode&valor=ID_EXTERNO_GERADO_NO_CORE`
- **Headers:** `Authorization: Bearer <MS_TOKEN>`
*O MS deve retornar o arquivo JSON do imóvel já persistido no MongoDB, contendo a chave `id` (Ex: `6a0bd8...`). Este é o `Imovel_ID` que usaremos a seguir.*

---

## ⬅️ Passo 3: Microsserviço ➝ Core (Registro de Coletas)

Agora simulação inversa: o Coletor foi até o imóvel e coletou materiais. Ele usa o App (Microsserviço) para salvar e propagar isso para o backend governamental (Core).

### 3.1. Cadastrar uma Coleta no Microsserviço
- **Endpoint:** `POST http://localhost:8002/api/coletas`
- **Headers:** `Authorization: Bearer <MS_TOKEN>`
- **Payload:**
```json
{
  "imovel_id": "ID_MONGODB_DO_IMOVEL_OBTIDO_NO_PASSO_2_2",
  "data_hora": "2026-05-19T10:00:00Z",
  "materiais": [
    {
      "tipo": "plastico",
      "peso_kg": "1.5"
    },
    {
      "tipo": "papel",
      "peso_kg": "1.0"
    }
  ],
  "gps": {
    "latitude": -6.1086,
    "longitude": -38.2089
  }
}
```
*Observe a resposta: `sincronizado: true`! O Microsserviço persistiu a coleta no MongoDB (gerando um ObjectId para a coleta) e disparou a mensagem para a fila `coletas`.*

### 3.2. Verificar Consumer no Core
No seu terminal onde o consumidor do Core está rodando (via `python manage.py consume_queue`), você verá um log de Sucesso demonstrando os pontos sendo calculados e computados no Postgres. Algo como:
> `Registrado: inscricao=... (id=15) 3.5 pts recebidos...`

---

## 🎯 Passo 4: Cruzamento e Checagem Final

Verifique se a integração foi um sucesso total pelas APIs de leitura.

### 4.1. Status de Sincronização no Microsserviço
Mostre a tela do app onde o coletor valida que tudo subiu para a nuvem.
- **Endpoint:** `GET http://localhost:8002/api/sincronizacao/status`
- **Headers:** `Authorization: Bearer <MS_TOKEN>`
*Retorno esperado:* `"pendentes": 0, "sincronizadas_hoje": 1*

### 4.2. Saldo de Pontos no Core
Mostre que o morador recebeu seu desconto (se aplicável) e pontuação.
- **Endpoint:** `GET http://localhost:8001/api/program/benefits/{ID_DO_IMOVEL}`
- **Headers:** `Authorization: Bearer <CORE_TOKEN_DE_MORADOR>`
*Aqui o cliente prova a consolidação da jornada: o morador de fato recebeu seus créditos a partir de um registro feito de forma desconectada e assíncrona pelo coletor.*

---
**💡 Dica para a apresentação:** Deixe as abas do RabbitMQ UI abertas (`http://localhost:15672`) nos gráficos em tempo real (Spikes) enquanto despacha os comandos HTTP!
