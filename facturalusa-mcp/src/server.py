import json
import os
from typing import Any

import httpx
import uvicorn
from mcp.server.fastmcp import FastMCP

API_BASE = os.getenv("FACTURALUSA_API_BASE", "https://facturalusa.pt/api/v2").rstrip("/")
API_KEY = os.getenv("FACTURALUSA_API_KEY", "").strip()
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30"))

mcp = FastMCP(
    "FacturaLusa",
    instructions=(
        "Integração oficial com a API REST do FacturaLusa. "
        "As operações de criação de clientes e artigos alteram dados reais. "
        "A criação de vendas está limitada a Rascunho; nunca emite nem assina "
        "documentos fiscais automaticamente."
    ),
)

class FacturalusaError(RuntimeError):
    pass

async def api_request(method: str, path: str, payload: dict[str, Any] | None = None):
    if not API_KEY:
        raise FacturalusaError(
            "Falta configurar FACTURALUSA_API_KEY nas variáveis de ambiente do servidor."
        )

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.request(
            method,
            f"{API_BASE}/{path.lstrip('/')}",
            headers=headers,
            json=payload,
        )

    try:
        data = response.json()
    except ValueError:
        data = {"raw_response": response.text[:4000]}

    if response.is_error:
        raise FacturalusaError(
            f"FacturaLusa respondeu HTTP {response.status_code}: "
            f"{json.dumps(data, ensure_ascii=False)[:4000]}"
        )
    return data

def parse_payload(payload_json: str) -> dict[str, Any]:
    try:
        value = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON inválido: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("O conteúdo tem de ser um objeto JSON.")
    return value

@mcp.tool()
async def procurar_cliente(valor: str, procurar_em: str = "Name") -> dict:
    """Procura um cliente por ID, Code, Name, Email, Vat Number ou Mobile."""
    allowed = {"ID", "Code", "Name", "Email", "Vat Number", "Mobile"}
    if procurar_em not in allowed:
        raise ValueError(f"procurar_em tem de ser um de: {', '.join(sorted(allowed))}")
    return await api_request("POST", "/customers/find", {
        "value": valor, "search_in": procurar_em
    })

@mcp.tool()
async def criar_cliente(dados_json: str) -> dict:
    """Cria um cliente. Envia um objeto JSON com name, type e vat_type obrigatórios."""
    data = parse_payload(dados_json)
    missing = [key for key in ("name", "type", "vat_type") if not data.get(key)]
    if missing:
        raise ValueError(f"Campos obrigatórios em falta: {', '.join(missing)}")
    if data["type"] not in {"Empresarial", "Particular"}:
        raise ValueError("type tem de ser Empresarial ou Particular.")
    if data["vat_type"] not in {"Debitar IVA", "IVA incluído", "Não fazer nada"}:
        raise ValueError("vat_type inválido.")
    return await api_request("POST", "/customers", data)

@mcp.tool()
async def procurar_artigo(valor: str, procurar_em: str = "Description") -> dict:
    """Procura um artigo por ID, Reference, Description ou Barcode."""
    allowed = {"ID", "Reference", "Description", "Barcode"}
    if procurar_em not in allowed:
        raise ValueError(f"procurar_em tem de ser um de: {', '.join(sorted(allowed))}")
    return await api_request("POST", "/items/find", {
        "value": valor, "search_in": procurar_em
    })

@mcp.tool()
async def criar_artigo(dados_json: str) -> dict:
    """Cria um artigo. JSON exige description, unit, vat e type."""
    data = parse_payload(dados_json)
    missing = [key for key in ("description", "unit", "vat", "type") if key not in data or data[key] in (None, "")]
    if missing:
        raise ValueError(f"Campos obrigatórios em falta: {', '.join(missing)}")
    allowed_types = {
        "Embalagens", "Matérias primas", "Mercadorias",
        "Produtos acabados e intermédios", "Serviços",
        "Subprodutos", "Transporte", "Vasilhame"
    }
    if data["type"] not in allowed_types:
        raise ValueError("Tipo de artigo inválido.")
    return await api_request("POST", "/items", data)

@mcp.tool()
async def procurar_documento(valor: str, procurar_em: str = "Document Number") -> dict:
    """Procura pontualmente uma venda por ID, Document Number ou External Reference."""
    allowed = {"ID", "Document Number", "External Reference"}
    if procurar_em not in allowed:
        raise ValueError(f"procurar_em tem de ser um de: {', '.join(sorted(allowed))}")
    return await api_request("POST", "/sales/find", {
        "value": valor, "search_in": procurar_em
    })

@mcp.tool()
async def criar_rascunho_venda(dados_json: str) -> dict:
    """
    Cria uma venda apenas em estado Rascunho.
    JSON exige issue_date, document_type, customer, vat_type e items.
    Não emite, assina, envia por email ou SMS.
    """
    data = parse_payload(dados_json)
    required = ("issue_date", "document_type", "customer", "vat_type", "items")
    missing = [key for key in required if key not in data or data[key] in (None, "")]
    if missing:
        raise ValueError(f"Campos obrigatórios em falta: {', '.join(missing)}")
    if not isinstance(data["items"], list) or not data["items"]:
        raise ValueError("items tem de ser uma lista com pelo menos um artigo.")
    if len(data["items"]) > 100:
        raise ValueError("Um documento não pode ter mais de 100 artigos.")
    if data["vat_type"] not in {"Debitar IVA", "IVA incluído", "Não fazer nada"}:
        raise ValueError("vat_type inválido.")

    # Proteções: esta integração nunca termina, assina ou envia documentos.
    data["status"] = "Rascunho"
    for key in ("force_print", "force_send_email", "force_send_sms", "force_sign"):
        data.pop(key, None)

    return await api_request("POST", "/sales", data)

class AccessAndHealthMiddleware:
    """Protege o endpoint MCP com um token separado da chave FacturaLusa."""

    def __init__(self, app):
        self.app = app
        self.access_token = os.getenv("MCP_ACCESS_TOKEN", "").strip()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        if path == "/health":
            body = b'{"status":"ok"}'
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())],
            })
            await send({"type": "http.response.body", "body": body})
            return

        headers = dict(scope.get("headers", []))
        supplied = headers.get(b"authorization", b"").decode("latin1")
        expected = f"Bearer {self.access_token}" if self.access_token else ""

        if not expected or supplied != expected:
            body = b'{"error":"Unauthorized"}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())],
            })
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)


if __name__ == "__main__":
    if not os.getenv("MCP_ACCESS_TOKEN", "").strip():
        raise RuntimeError("Define MCP_ACCESS_TOKEN antes de iniciar o servidor.")
    app = mcp.streamable_http_app()
    app.add_middleware(AccessAndHealthMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
