# FacturaLusa MCP

Servidor MCP em Python para ligar um cliente MCP ao FacturaLusa através da API REST oficial.

## Funcionalidades iniciais

- Procurar clientes e artigos.
- Criar clientes e artigos.
- Procurar documentos de venda.
- Criar vendas **apenas em Rascunho**.

A integração não emite, termina, assina, envia por email ou SMS documentos fiscais. Essas operações exigem validação e um fluxo de confirmação separado.

## Configuração local

1. Instalar Python 3.11 ou superior.
2. Criar ambiente virtual e instalar dependências:

   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Copiar `.env.example` para `.env` e definir `FACTURALUSA_API_KEY`.
4. Executar:

   ```bash
   python src/server.py
   ```

O servidor MCP Streamable HTTP fica disponível em `/mcp` na porta definida por `PORT` (por omissão 10000).

## Deploy na Render

1. Colocar estes ficheiros num repositório GitHub.
2. Na Render, escolher **New + → Blueprint** e selecionar o repositório.
3. A Render lê `render.yaml`.
4. Em Environment, definir `FACTURALUSA_API_KEY` com a chave gerada na conta FacturaLusa.
5. Fazer deploy e verificar os logs.

Não guardar a chave API no GitHub, no código ou em mensagens de chat. Usar apenas a variável de ambiente da Render.

## Ligação ao cliente MCP

URL do endpoint depois do deploy:

`https://NOME-DO-SERVICO.onrender.com/mcp`

O endpoint `/mcp` exige `Authorization: Bearer <MCP_ACCESS_TOKEN>`. A rota `/health` não exige autenticação e serve apenas para a verificação de saúde da Render. Nunca partilhar o token de acesso nem a chave API.

## Notas

- API base: `https://facturalusa.pt/api/v2`
- Autenticação: `Authorization: Bearer <API_KEY>`
- As pesquisas `find` são para consultas pontuais; não usar polling contínuo.
- Confirmar sempre os dados fiscais antes de criar qualquer documento.
