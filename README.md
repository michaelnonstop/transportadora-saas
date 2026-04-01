# Transportadora Control Pro

Sistema completo base para transportadora, com:

- Login
- Dashboard
- Cadastro de clientes
- Cadastro de colaboradores
- Cadastro e acompanhamento de serviços
- Financeiro
- Geração de PDF
- Bloqueio por assinatura/mensalidade

## Login demo

- **E-mail:** admin@demo.com
- **Senha:** 123456

## Como rodar

```bash
cd transportadora_app
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abra:

```bash
http://127.0.0.1:8000
```

## Estrutura

- `app/main.py` → backend FastAPI + SQLite
- `app/templates/` → telas HTML
- `app/static/style.css` → visual do sistema
- `app/transportadora.db` → banco SQLite gerado automaticamente ao iniciar

## Como funciona o bloqueio de mensalidade

- O usuário possui `status`, `due_date` e `grace_days`
- Se a assinatura vencer:
  - dentro da carência, sistema mostra aviso
  - após a carência, bloqueia acesso às telas protegidas
- Na tela **Assinatura**, o botão **Simular pagamento e renovar 30 dias** renova o acesso na versão demo

## Personalizações sugeridas

- Integrar Mercado Pago, Asaas ou Stripe
- Criptografar senhas
- Adicionar permissões por tipo de usuário
- Hospedar em VPS, Render, Railway ou outro serviço cloud
