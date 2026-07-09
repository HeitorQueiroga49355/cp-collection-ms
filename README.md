# Coleta Premiada - Collection Microservice (MS)

## 📌 Propósito e Papel na Arquitetura
O **Collection Microservice** é um serviço desacoplado dedicado ao registro e validação das pesagens (coletas) de materiais recicláveis.
Sua principal função na arquitetura é receber alto volume de inserções vindas dos dispositivos dos leituristas (pontas na rua), armazenar evidências fotográficas de forma resiliente, realizar validações e repassar as informações confirmadas ao Core de maneira segura e assíncrona, garantindo a escalabilidade e a resiliência do sistema de pontuação.

## 🛠️ Stack Tecnológica
- **Backend:** Python, Django API
- **Banco de Dados:** MongoDB (Armazenamento NoSQL)
- **Mensageria:** RabbitMQ (Publicação de eventos na Fila de Mensagens)
- **Armazenamento:** S3 / MinIO (Upload de fotos das coletas)
- **Infraestrutura/Orquestração:** Docker, Docker Compose

## 📋 Pré-requisitos
- [Docker](https://docs.docker.com/engine/install/) e [Docker Compose](https://docs.docker.com/compose/install/) instalados
- [Git](https://git-scm.com/)

## 🚀 Instalação e Execução Local com Docker

1. **Clone este repositório:**
   ```bash
   git clone https://github.com/rangelro/cp-collection-ms.git
   cd cp-collection-ms
   ```

2. **Configure as Variáveis de Ambiente:**
   Copie o arquivo de exemplo e defina as configurações:
   ```bash
   cp .env.example .env
   ```

3. **Suba os containers:**
   O microserviço é desenhado para subir isoladamente ou acoplado à rede do Core.
   ```bash
   docker compose up -d
   ```

A documentação interativa (Swagger UI) do FastAPI ficará disponível nativamente através da rota de documentação em seu endpoint local (geralmente `http://localhost:8002/docs`).

## ⚙️ Variáveis de Ambiente
As variáveis de ambiente controlam o acesso ao RabbitMQ compartilhado, credenciais do banco isolado do microserviço e bucket MinIO. Verifique o arquivo `.env.example` para obter a lista exata e o formato das chaves esperadas.

## 🧪 Como rodar os testes
Para rodar a suíte de testes (com Pytest):
```bash
docker compose exec collection-app pytest
```

## 📚 Documentação Adicional
Consulte nossa Wiki para diagramas de contexto (C4), padrões de mensageria adotados e payloads de eventos:
👉 [Wiki do Projeto Coleta Premiada](https://github.com/rangelro/Coleta-Premiada/wiki)
