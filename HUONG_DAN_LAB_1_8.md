# Huong Dan Thuc Hanh: Amazon Bedrock AgentCore Workshop (Lab 1-8)

## Thong Tin Chung

| Thong tin | Gia tri |
|---|---|
| **AWS Account ID** | `` |
| **Region** | `us-east-1` |
| **Project Name** | `CustomerSupport2` |
| **Stack Name** | `AgentCore-CustomerSupport2-default` |
| **AgentCore CLI** | `@aws/agentcore` (npm) |
| **Python** | 3.12 |
| **OS** | Windows |

---

## Muc Luc

1. [Lab 1: Building the Agent Prototype](#lab-1-building-the-agent-prototype)
2. [Lab 2: Adding Memory](#lab-2-adding-memory)
3. [Lab 3: Scaling Tools with Gateway](#lab-3-scaling-tools-with-gateway)
4. [Lab 4: Production Features and Security](#lab-4-production-features-and-security)
5. [Lab 5: Online Evaluations](#lab-5-online-evaluations)
6. [Lab 6: Web Chat Frontend](#lab-6-web-chat-frontend)
7. [Lab 7: Policy Engine (Cedar)](#lab-7-policy-engine-cedar)
8. [Lab 8: AgentCore Harness (Zero-code)](#lab-8-agentcore-harness-zero-code)
9. [Cleanup - Xoa Resources](#cleanup---xoa-resources)
10. [Tong Hop Loi Gap Phai](#tong-hop-loi-gap-phai)

---

## Lab 1: Building the Agent Prototype

### Muc tieu
Tao customer support agent voi 3 tools: return policy, product info, Exa web search.

### Buoc 1: Cai dat Prerequisites

```powershell
# Cai AgentCore CLI (npm)
npm install -g @aws/agentcore

# Cai uv (Python package manager - BAT BUOC cho agentcore dev)
pip install uv
```

### Buoc 2: Tao Project

```powershell
agentcore create
# Chon: Strands Agents, Amazon Bedrock, Memory tuy chon, CodeZip
# Ten project: CustomerSupport2
```

### Buoc 3: Thay the main.py

Thay toan bo noi dung `app/CustomerSupport2/main.py` voi code customer support:
- 2 tools: `get_return_policy()`, `get_product_info()`
- System prompt cho customer support
- Exa MCP client cho web search
- Them dong "Do NOT use emojis" vao system prompt (fix loi Unicode tren Windows)    

### Buoc 4: Chay Local Dev Server

```powershell
# Set UTF-8 truoc khi chay (fix loi emoji)
$env:PYTHONUTF8 = "1"
agentcore dev
```

### Buoc 5: Test Agent

```powershell
# Trong terminal khac
agentcore invoke --dev '{"prompt":"What is the return policy for electronics?"}'
```

### Buoc 6: Deploy len AWS

```powershell
agentcore deploy -y -v
```

### Buoc 7: Test deployed agent

```powershell
agentcore invoke "What is the return policy for electronics?" --stream
```

---

## Lab 2: Adding Memory

### Muc tieu
Them AgentCore Memory (SEMANTIC + SUMMARIZATION) de agent nho users across sessions.

### Buoc 1: Cap nhat agentcore.json - them memory strategies

Trong `agentcore/agentcore.json`, sua section `memories`:

```json
"memories": [
  {
    "name": "SharedMemory",
    "eventExpiryDuration": 30,
    "strategies": [
      {
        "type": "SEMANTIC",
        "namespaces": ["/users/{actorId}/facts"]
      },
      {
        "type": "SUMMARIZATION",
        "namespaces": ["/summaries/{actorId}/{sessionId}"]
      }
    ]
  }
]
```

**Luu y:** Dung key `"type"` KHONG PHAI `"strategyName"`.

### Buoc 2: Tao memory/session.py

Tao file `app/CustomerSupport2/memory/session.py`:

```python
import os
from typing import Optional
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig, RetrievalConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

MEMORY_ID = os.getenv("MEMORY_SHAREDMEMORY_ID")
REGION = os.getenv("AWS_REGION")

def get_memory_session_manager(session_id: str, actor_id: str) -> Optional[AgentCoreMemorySessionManager]:
    if not MEMORY_ID:
        return None
    retrieval_config = {
        f"/users/{actor_id}/facts": RetrievalConfig(top_k=3, relevance_score=0.3),
        f"/summaries/{actor_id}/{session_id}": RetrievalConfig(top_k=3, relevance_score=0.3)
    }
    return AgentCoreMemorySessionManager(
        AgentCoreMemoryConfig(
            memory_id=MEMORY_ID,
            session_id=session_id,
            actor_id=actor_id,
            retrieval_config=retrieval_config,
        ),
        REGION
    )
```

### Buoc 3: Cap nhat main.py

- Import memory session manager
- Thay doi `get_or_create_agent()` nhan `session_id`, `user_id`
- Them `session_manager` vao Agent
- Cap nhat `invoke()` de lay user_id tu headers (dung `.get()` de tranh KeyError)

### Buoc 4: Them requestHeaderAllowlist vao runtime config

```json
"requestHeaderAllowlist": [
  "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id"
]
```

### Buoc 5: Deploy va test

```powershell
agentcore deploy -y -v

# Test memory
$SESSION_A = [guid]::NewGuid().ToString()
agentcore invoke "My name is Sarah" --session-id $SESSION_A --user-id Sarah --stream

# Doi 2 phut
Start-Sleep -Seconds 120

$SESSION_B = [guid]::NewGuid().ToString()
agentcore invoke "Do you know anything about me?" --session-id $SESSION_B --user-id Sarah --stream
```

---

## Lab 3: Scaling Tools with Gateway

### Muc tieu
Expose Lambda warranty check qua AgentCore Gateway (MCP endpoint).

### Buoc 1: Tao Lambda function (neu chua co)

Tao file `lambda/warranty_check.py`:

```python
import json
WARRANTIES = {
    "PROD-001": {"product": "Wireless Headphones", "warranty_months": 12, "status": "active", "expires": "2027-03-01"},
    "PROD-002": {"product": "Smart Watch", "warranty_months": 24, "status": "active", "expires": "2028-01-15"},
    "PROD-003": {"product": "Laptop Stand", "warranty_months": 6, "status": "expired", "expires": "2026-01-01"},
    "PROD-004": {"product": "USB-C Hub", "warranty_months": 12, "status": "active", "expires": "2027-06-20"},
}
def handler(event, context):
    product_id = event.get("product_id", "").upper()
    if product_id in WARRANTIES:
        return {"statusCode": 200, "body": json.dumps(WARRANTIES[product_id])}
    return {"statusCode": 404, "body": json.dumps({"error": f"No warranty found for {product_id}"})}
```

Deploy Lambda:

```powershell
# Tao IAM role
aws iam create-role --region us-east-1 --role-name workshop-warranty-check-role --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name workshop-warranty-check-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Doi 10s cho IAM propagate
Start-Sleep -Seconds 10

# Zip va deploy
Compress-Archive -Path "lambda\warranty_check.py" -DestinationPath "lambda\warranty_check.zip" -Force
aws lambda create-function --region us-east-1 --function-name workshop-warranty-check --runtime python3.12 --role arn:aws:iam::<ACCOUNT_ID>:role/workshop-warranty-check-role --handler warranty_check.handler --zip-file fileb://lambda/warranty_check.zip
```

### Buoc 2: Tao tool schema

Tao file `app/CustomerSupport2/tool/warranty_schema.json`:

```json
[
  {
    "name": "check_warranty",
    "description": "Check the warranty status of a product by its product ID.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "product_id": {
          "type": "string",
          "description": "The product ID to check warranty for (e.g. PROD-001)"
        }
      },
      "required": ["product_id"]
    }
  }
]
```

### Buoc 3: Them Gateway va Target

```powershell
agentcore add gateway --name my-gateway --runtimes CustomerSupport2
agentcore add gateway-target --type lambda-function-arn --name WarrantyCheck --lambda-arn <LAMBDA_ARN> --tool-schema-file app/CustomerSupport2/tool/warranty_schema.json --gateway my-gateway
```

### Buoc 4: Cap nhat mcp_client/client.py

Them function `get_gateway_mcp_client()`:

```python
def get_gateway_mcp_client() -> MCPClient | None:
    url = os.environ.get("AGENTCORE_GATEWAY_MY_GATEWAY_URL")
    if not url:
        return None
    return MCPClient(lambda: streamablehttp_client(url))
```

### Buoc 5: Cap nhat main.py

- Import `get_gateway_mcp_client`
- Them vao `mcp_clients` list
- Xoa `warranty_months` khoi PRODUCTS dict

### Buoc 6: Deploy va test

```powershell
agentcore deploy -y -v
agentcore invoke "Check the warranty for PROD-003" --session-id $([guid]::NewGuid().ToString()) --user-id Sarah --stream
```

---

## Lab 4: Production Features and Security

### Muc tieu
Session continuity, observability, JWT auth voi Cognito.

### Buoc 1: Tao Cognito User Pool

```powershell
# Tao User Pool
$POOL_ID = aws cognito-idp create-user-pool --region us-east-1 --pool-name "workshop-agentcore-pool" --auto-verified-attributes email --username-attributes email --policies "PasswordPolicy={MinimumLength=8,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=false}" --query "UserPool.Id" --output text

# Tao Web Client (public, khong co secret)
$WEB_CLIENT_ID = aws cognito-idp create-user-pool-client --region us-east-1 --user-pool-id $POOL_ID --client-name "workshop-web-client" --explicit-auth-flows "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" --access-token-validity 60 --token-validity-units "AccessToken=minutes" --query "UserPoolClient.ClientId" --output text

# Tao Machine Client (co secret, cho Lab 8)
# Truoc tien tao Resource Server
aws cognito-idp create-resource-server --region us-east-1 --user-pool-id $POOL_ID --identifier "agentcore-gateway" --name "AgentCore Gateway" --scopes "ScopeName=read,ScopeDescription=Read access"

$M2M_CLIENT = aws cognito-idp create-user-pool-client --region us-east-1 --user-pool-id $POOL_ID --client-name "workshop-m2m-client" --generate-secret --explicit-auth-flows "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" --supported-identity-providers "COGNITO" --allowed-o-auth-flows "client_credentials" --allowed-o-auth-scopes "agentcore-gateway/read" --allowed-o-auth-flows-user-pool-client --output json
```

### Buoc 2: Cap nhat agentcore.json - them JWT auth

Trong runtime config:

```json
"authorizerType": "CUSTOM_JWT",
"authorizerConfiguration": {
  "customJwtAuthorizer": {
    "discoveryUrl": "https://cognito-idp.us-east-1.amazonaws.com/<POOL_ID>/.well-known/openid-configuration",
    "allowedClients": ["<WEB_CLIENT_ID>", "<M2M_CLIENT_ID>"]
  }
}
```

Them `"Authorization"` vao `requestHeaderAllowlist`.

### Buoc 3: Xoa gateway cu, tao gateway moi voi auth

```powershell
agentcore remove gateway --name my-gateway -y
agentcore add gateway --name my-gateway-secure --runtimes CustomerSupport2 --authorizer-type CUSTOM_JWT --discovery-url $COGNITO_DISCOVERY_URL --allowed-clients "$WEB_CLIENT_ID,$M2M_CLIENT_ID"

# Re-add target
agentcore add gateway-target --type lambda-function-arn --name WarrantyCheck --lambda-arn <LAMBDA_ARN> --tool-schema-file app/CustomerSupport2/tool/warranty_schema.json --gateway my-gateway-secure
```

### Buoc 4: Cap nhat main.py - them extract_user_id() tu JWT

```python
import jwt

def extract_user_id(auth_header) -> str | None:
    if auth_header and auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ", 1)[1]
            claims = jwt.decode(token, options={"verify_signature": False})
            return claims.get("username")
        except Exception:
            pass
    return None
```

### Buoc 5: Cap nhat client.py - forward auth header

```python
def get_gateway_mcp_client(auth_header: str) -> MCPClient | None:
    url = os.environ.get("AGENTCORE_GATEWAY_MY_GATEWAY_SECURE_URL") or os.environ.get("AGENTCORE_GATEWAY_MY_GATEWAY_URL")
    if not url:
        return None
    headers = {}
    if auth_header:
        headers["Authorization"] = auth_header
    return MCPClient(lambda: streamablehttp_client(url=url, headers=headers))
```

### Buoc 6: Them PyJWT dependency

Them `"PyJWT >= 2.8.0"` vao `pyproject.toml` dependencies.

### Buoc 7: Deploy va test

```powershell
agentcore deploy -y -v

# Tao test user
aws cognito-idp admin-create-user --region us-east-1 --user-pool-id $POOL_ID --username workshopuser@example.com --temporary-password "TempPass1!" --user-attributes "Name=email,Value=workshopuser@example.com" "Name=email_verified,Value=true" --message-action SUPPRESS
aws cognito-idp admin-set-user-password --region us-east-1 --user-pool-id $POOL_ID --username workshopuser@example.com --password "WorkshopPass1!" --permanent

# Lay token
$TOKEN = aws cognito-idp initiate-auth --region us-east-1 --auth-flow USER_PASSWORD_AUTH --client-id $WEB_CLIENT_ID --auth-parameters "USERNAME=workshopuser@example.com,PASSWORD=WorkshopPass1!" --query 'AuthenticationResult.AccessToken' --output text

# Test voi token
$SESSION_3 = [guid]::NewGuid().ToString()
agentcore invoke "What is the return policy for electronics?" --session-id $SESSION_3 --bearer-token "$TOKEN" --stream

# Test khong token (phai fail)
agentcore invoke "Hello" --session-id $SESSION_3 --stream --json
```

---

## Lab 5: Online Evaluations

### Muc tieu
Continuous quality monitoring voi built-in evaluators.

### Buoc 1: Them online eval config

```powershell
agentcore add online-eval --name QualityMonitor --runtime CustomerSupport2 --evaluator Builtin.GoalSuccessRate Builtin.Correctness Builtin.ToolSelectionAccuracy --sampling-rate 100 --enable-on-create
```

### Buoc 2: Deploy

```powershell
agentcore deploy -y -v
```

### Buoc 3: Generate test interactions

```powershell
$SESSION_EVAL = [guid]::NewGuid().ToString()
agentcore invoke "What can you tell me about the Smart Watch?" --session-id $SESSION_EVAL --bearer-token "$TOKEN" --stream
agentcore invoke "Check the warranty status for product PROD-001" --session-id $SESSION_EVAL --bearer-token "$TOKEN" --stream
```

### Buoc 4: Run on-demand evaluation

**Luu y:** Dung `--session-id` hoac `--trace-id` cu the, KHONG dung `--days 1` (co the loi).

```powershell
# Lay trace ID
agentcore traces list --limit 5

# Eval theo session
agentcore run eval --runtime CustomerSupport2 --evaluator Builtin.GoalSuccessRate Builtin.Correctness --session-id <SESSION_ID>

# Hoac eval theo trace
agentcore run eval --runtime CustomerSupport2 --evaluator Builtin.GoalSuccessRate --trace-id <TRACE_ID>
```

### Buoc 5: Xem ket qua

```powershell
agentcore evals history --runtime CustomerSupport2 --limit 5
```

### Buoc 6: Pause/Resume (optional)

```powershell
agentcore pause online-eval QualityMonitor
agentcore resume online-eval QualityMonitor
```

---

## Lab 6: Web Chat Frontend

### Muc tieu
Flask web UI voi Cognito login (OAuth authorization code + PKCE).

### Buoc 1: Cai dat Flask

```powershell
cd app\CustomerSupport2
uv add flask boto3 requests
cd ..\..
```

### Buoc 2: Tao Cognito Hosted UI Domain

```powershell
aws cognito-idp create-user-pool-domain --region us-east-1 --user-pool-id <POOL_ID> --domain "workshop-agentcore-cs2"

# Cap nhat web client voi OAuth settings
aws cognito-idp update-user-pool-client --region us-east-1 --user-pool-id <POOL_ID> --client-id <WEB_CLIENT_ID> --explicit-auth-flows "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" --supported-identity-providers "COGNITO" --callback-urls "http://localhost:8501/callback" --logout-urls "http://localhost:8501/" --allowed-o-auth-flows "code" --allowed-o-auth-scopes "openid" "email" "profile" --allowed-o-auth-flows-user-pool-client
```

### Buoc 3: Tao frontend directory structure

```powershell
mkdir app\CustomerSupport2\frontend\templates
```

### Buoc 4: Tao frontend.py

File `app/CustomerSupport2/frontend/frontend.py` - Flask backend voi:
- **PKCE support** (QUAN TRONG - Cognito public client yeu cau PKCE)
- Static secret key (khong dung `os.urandom()` de tranh mat session khi reload)
- URL-encode ARN khi goi AgentCore API (`urllib.parse.quote()`)
- SSE response parser (strip JSON quotes tu `data: "text"` lines)
- `debug=False` (tranh watchdog restart lam mat session)

**Diem quan trong trong frontend.py:**

```python
from urllib.parse import quote

# URL-encode ARN
ENCODED_ARN = quote(RUNTIME_ARN, safe="")
INVOKE_URL = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{ENCODED_ARN}/invocations"

# Static secret key
app.secret_key = "workshop-agentcore-dev-secret-key-do-not-use-in-prod"

# PKCE
def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]

def generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

# SSE Parser - strip JSON quotes
for line in resp.text.split("\n"):
    line = line.strip()
    if line.startswith("data: "):
        data = line[6:]
        if data.startswith('"') and data.endswith('"'):
            data = json.loads(data)  # decode JSON string
        full_response += data
```

### Buoc 5: Tao templates

- `templates/login.html` - Login page voi link den Cognito hosted UI
- `templates/index.html` - Chat UI voi quick actions

### Buoc 6: Chay frontend

```powershell
cd app\CustomerSupport2\frontend
uv run python frontend.py
# Mo browser: http://localhost:8501
# Login: workshopuser@example.com / WorkshopPass1!
```

---

## Lab 7: Policy Engine (Cedar)

### Muc tieu
Fine-grained authorization - han che refund < $100, permit warranty check.

### Buoc 1: Tao Lambda process_refund

Tao file `lambda/process_refund.py`:

```python
import json
def handler(event, context):
    order_id = event.get("order_id", "")
    amount = event.get("amount", 0)
    reason = event.get("reason", "")
    if not order_id or not amount or not reason:
        return {"statusCode": 400, "body": json.dumps({"error": "Missing fields"})}
    return {"statusCode": 200, "body": json.dumps({
        "status": "approved", "order_id": order_id,
        "refund_amount": amount, "reason": reason,
        "message": f"Refund of ${amount} for order {order_id} processed."
    })}
```

Deploy:
```powershell
Compress-Archive -Path "lambda\process_refund.py" -DestinationPath "lambda\process_refund.zip" -Force
aws lambda create-function --region us-east-1 --function-name workshop-process-refund --runtime python3.12 --role <ROLE_ARN> --handler process_refund.handler --zip-file fileb://lambda/process_refund.zip
```

### Buoc 2: Tao tool schema va add gateway target

Tao `app/CustomerSupport2/tool/refund_schema.json`:
```json
[
  {
    "name": "process_refund",
    "description": "Process a customer refund for a given order.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "order_id": {"type": "string", "description": "Order ID"},
        "amount": {"type": "integer", "description": "Refund amount in whole dollars"},
        "reason": {"type": "string", "description": "Reason for refund"}
      },
      "required": ["order_id", "amount", "reason"]
    }
  }
]
```

```powershell
agentcore add gateway-target --type lambda-function-arn --name ProcessRefund --lambda-arn <REFUND_LAMBDA_ARN> --tool-schema-file app/CustomerSupport2/tool/refund_schema.json --gateway my-gateway-secure
```

### Buoc 3: Tao Policy Engine

```powershell
agentcore add policy-engine --name CustomerSupportPolicyEngine --description "Governs customer support agent tool access" --attach-to-gateways my-gateway-secure --attach-mode ENFORCE
```

### Buoc 4: Deploy TARGET truoc (khong co policy)

**QUAN TRONG:** Deploy gateway target TRUOC khi them policies. Neu deploy cung luc se gap loi "unrecognized action".

```powershell
agentcore deploy -y -v
```

### Buoc 5: Them Cedar policies vao agentcore.json

**QUAN TRONG:** 
- Dung escaped quotes `\"...\"` cho Cedar entity literals trong JSON
- Dung `"validationMode": "IGNORE_ALL_FINDINGS"` de bypass validation issues

```json
"policyEngines": [
  {
    "name": "CustomerSupportPolicyEngine",
    "description": "Governs customer support agent tool access",
    "policies": [
      {
        "name": "refund_limit_policy",
        "description": "Allow refunds under 100 dollars only",
        "statement": "permit(principal, action == AgentCore::Action::\"ProcessRefund___process_refund\", resource == AgentCore::Gateway::\"<GATEWAY_ARN>\") when { ((context.input).amount) < 100 };",
        "validationMode": "IGNORE_ALL_FINDINGS",
        "enforcementMode": "ACTIVE",
        "authorizationPhase": "INITIATE"
      },
      {
        "name": "warranty_check_policy",
        "description": "Allow all authenticated users to check warranties",
        "statement": "permit(principal, action == AgentCore::Action::\"WarrantyCheck___check_warranty\", resource == AgentCore::Gateway::\"<GATEWAY_ARN>\") when { (principal is AgentCore::OAuthUser) };",
        "validationMode": "IGNORE_ALL_FINDINGS",
        "enforcementMode": "ACTIVE",
        "authorizationPhase": "INITIATE"
      }
    ]
  }
]
```

Them `policyEngineConfiguration` vao gateway:
```json
"policyEngineConfiguration": {
  "policyEngineName": "CustomerSupportPolicyEngine",
  "mode": "ENFORCE"
}
```

### Buoc 6: Deploy va test

```powershell
agentcore deploy -y -v
```

Test trong chat UI:
- `"Refund $50 for order ORD-12345, item damaged"` -> Thanh cong
- `"Refund $500 for order ORD-67890"` -> Bi deny
- `"Check warranty for PROD-002"` -> Thanh cong

---

## Lab 8: AgentCore Harness (Zero-code)

### Muc tieu
Tao declarative agent khong can viet code - chi CLI config.

### Buoc 1: Tao Harness

```powershell
agentcore add harness --name OrderResearchAgent --model-provider bedrock --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 --system-prompt "You are an order research specialist. Help customers investigate order issues, check warranties, and produce detailed analysis reports. Always be thorough and provide structured summaries. Save reports to /tmp/ when asked." --tools agentcore_code_interpreter
```

### Buoc 2: Tao Machine Client (voi secret)

Cognito `client_credentials` flow yeu cau client co secret va resource server.

```powershell
# Tao resource server (neu chua co)
aws cognito-idp create-resource-server --region us-east-1 --user-pool-id <POOL_ID> --identifier "agentcore-gateway" --name "AgentCore Gateway" --scopes "ScopeName=read,ScopeDescription=Read access"

# Tao M2M client voi secret
aws cognito-idp create-user-pool-client --region us-east-1 --user-pool-id <POOL_ID> --client-name "workshop-m2m-client" --generate-secret --explicit-auth-flows "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" --supported-identity-providers "COGNITO" --allowed-o-auth-flows "client_credentials" --allowed-o-auth-scopes "agentcore-gateway/read" --allowed-o-auth-flows-user-pool-client
```

Them M2M Client ID vao `allowedClients` trong ca runtime va gateway cua `agentcore.json`.

### Buoc 3: Tao credential provider

```powershell
$COGNITO_SCOPE = "agentcore-gateway/read"
agentcore add credential --type oauth --name gateway-egress-oauth --discovery-url "https://cognito-idp.us-east-1.amazonaws.com/<POOL_ID>/.well-known/openid-configuration" --client-id <M2M_CLIENT_ID> --client-secret <M2M_CLIENT_SECRET> --scopes $COGNITO_SCOPE
```

### Buoc 4: Add Gateway tool vao harness

```powershell
$GATEWAY_ARN = "<GATEWAY_ARN_TU_DEPLOYED_STATE>"
$PROVIDER_ARN = "arn:aws:bedrock-agentcore:us-east-1:<ACCOUNT_ID>:token-vault/default/oauth2credentialprovider/gateway-egress-oauth"

agentcore add tool --harness OrderResearchAgent --type agentcore_gateway --name my-gateway-secure --gateway-arn $GATEWAY_ARN --outbound-auth oauth --provider-arn $PROVIDER_ARN --scopes $COGNITO_SCOPE --grant-type CLIENT_CREDENTIALS
```

### Buoc 5: Deploy va test

```powershell
agentcore deploy -y -v

# Test
$SESSION = [guid]::NewGuid().ToString()
agentcore invoke --harness OrderResearchAgent --session-id $SESSION --actor-id "analyst-1" "Check the warranty for PROD-001 and PROD-003."

# Shell access
agentcore invoke --exec --harness OrderResearchAgent --session-id $SESSION "cat /tmp/warranty_report.md"

# Override model
agentcore invoke --harness OrderResearchAgent --model-id us.amazon.nova-2-lite-v1:0 --session-id $SESSION --actor-id "analyst-1" "Summarize in 3 bullet points."

# Test policy enforcement
agentcore invoke --harness OrderResearchAgent --session-id $([guid]::NewGuid().ToString()) --actor-id "analyst-1" "Process a refund of $500 for order ORD-12345"
```

### Buoc 6 (Bonus): Human-in-the-Loop

```powershell
# Them inline function
agentcore add tool --harness OrderResearchAgent --type inline_function --name approve_exception --description "Request manager approval for refund exceeding limit." --input-schema '{"type":"object","properties":{"order_id":{"type":"string"},"amount":{"type":"number"},"reason":{"type":"string"}},"required":["order_id","amount","reason"]}'

agentcore deploy -y -v

# Test HITL (can Python script - xem lab guide)
$env:HARNESS_ARN = aws bedrock-agentcore-control list-harnesses --query "harnesses[?contains(harnessName, 'OrderResearchAgent')].arn | [0]" --output text
python3 app/OrderResearchAgent/test_hitl.py
```

---

## Cleanup - Xoa Resources

### Xoa toan bo AgentCore stack

```powershell
# AgentCore CLI khong co lenh "destroy"
# Xoa truc tiep qua CloudFormation
aws cloudformation delete-stack --region us-east-1 --stack-name AgentCore-CustomerSupport2-default

# Doi va kiem tra
aws cloudformation describe-stacks --region us-east-1 --stack-name AgentCore-CustomerSupport2-default --query "Stacks[0].StackStatus" --output text
# Ket qua mong doi: "Stack does not exist" (da xoa xong)
```

### Xoa resources tao thu cong (ngoai stack)

```powershell
# Lambda functions
aws lambda delete-function --region us-east-1 --function-name workshop-warranty-check
aws lambda delete-function --region us-east-1 --function-name workshop-process-refund

# IAM role
aws iam detach-role-policy --role-name workshop-warranty-check-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name workshop-warranty-check-role

# Cognito
aws cognito-idp delete-user-pool-domain --region us-east-1 --user-pool-id <POOL_ID> --domain workshop-agentcore-cs2
aws cognito-idp delete-user-pool --region us-east-1 --user-pool-id <POOL_ID>

# OAuth credential (neu con)
aws bedrock-agentcore-control delete-oauth2-credential-provider --region us-east-1 --name gateway-egress-oauth
```

### Xoa local state file

```powershell
# Xoa file deployed-state.json de agentcore status khong hien "Deployed" cu
Remove-Item agentcore\.cli\deployed-state.json -Force
```

### Xac nhan da xoa sach

```powershell
# Kiem tra khong con stack
aws cloudformation list-stacks --region us-east-1 --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query "StackSummaries[?contains(StackName, 'AgentCore')]" --output table

# Kiem tra khong con Lambda
aws lambda list-functions --region us-east-1 --query "Functions[].FunctionName" --output text

# Kiem tra khong con Cognito
aws cognito-idp list-user-pools --region us-east-1 --max-results 10 --output table

# Kiem tra agentcore status hien "Local only"
agentcore status
```

---

## Tong Hop Loi Gap Phai

### Lab 1

| # | Loi | Nguyen nhan | Cach fix |
|---|---|---|---|
| 1 | `[WinError 2] The system cannot find the file specified` | CLI goi `uv` nhung chua cai | `pip install uv` |
| 2 | `Method Not Allowed` | Truy cap invoke URL bang GET (browser) | Dung POST request hoac `agentcore invoke --dev` |
| 3 | `Got unexpected extra argument(s)` | Shell tach JSON payload thanh nhieu args vi co dau cach | Dung single-quote: `'{"prompt":"Hello"}'` |
| 4 | `charmap codec can't encode character \U0001f44b` | Windows console khong ho tro Unicode emoji | Them "Do NOT use emojis" vao system prompt, hoac set `$env:PYTHONUTF8="1"` |

### Lab 2

| # | Loi | Nguyen nhan | Cach fix |
|---|---|---|---|
| 5 | `memories[0].strategies[0].type: expected "SEMANTIC"` | Dung key `strategyName` thay vi `type` trong JSON | Doi thanh `"type": "SEMANTIC"` |
| 6 | `KeyError: 'x-amzn-bedrock-agentcore-runtime-custom-user-id'` | CLI moi truyen user_id khac, header khong ton tai | Dung `.get()` voi fallback thay vi `dict['key']` truc tiep |

### Lab 3

| # | Loi | Nguyen nhan | Cach fix |
|---|---|---|---|
| 7 | `ParameterNotFound` (SSM) | Lambda chua duoc tao tu prerequisites stack | Tao Lambda thu cong bang AWS CLI |

### Lab 4

| # | Loi | Nguyen nhan | Cach fix |
|---|---|---|---|
| 8 | `ParameterNotFound` (Cognito SSM params) | Khong co prerequisites CloudFormation stack | Tao Cognito resources thu cong |

### Lab 5

| # | Loi | Nguyen nhan | Cach fix |
|---|---|---|---|
| 9 | `Provided input has no spans with supported scope` | `--days 1` query ca traces cu khong co strands spans | Dung `--session-id` hoac `--trace-id` cu the thay vi `--days` |

### Lab 6

| # | Loi | Nguyen nhan | Cach fix |
|---|---|---|---|
| 10 | `400 Client Error` khi exchange token | Cognito public client (khong co secret) yeu cau PKCE | Them code_verifier + code_challenge (S256) vao OAuth flow |
| 11 | Login OK nhung khong vao chat | `os.urandom(32)` tao secret key moi moi lan Flask reload -> session mat | Dung static secret key string |
| 12 | Watchdog restart giua OAuth callback | File thay doi trong `.venv` trigger reload -> mat code_verifier | Set `debug=False` |
| 13 | `404 Not Found` khi invoke agent | ARN chua `:` va `/` khong duoc URL-encode | Dung `urllib.parse.quote(ARN, safe="")` |
| 14 | Response hien raw SSE format | Parser khong strip JSON quotes tu `data: "text"` | Decode JSON string truoc khi concat |

### Lab 7

| # | Loi | Nguyen nhan | Cach fix |
|---|---|---|---|
| 15 | `expected kw_in, kw_has, kw_like...` (Cedar parse error) | Cedar entity literals thieu dau ngoac kep | Them escaped quotes `\"...\"` trong JSON statement |
| 16 | `unrecognized action ProcessRefund___process_refund` | Target chua deploy (rollback), Cedar khong nhan action | Deploy target TRUOC (khong co policy), sau do them policy voi `validationMode: IGNORE_ALL_FINDINGS` |

### Lab 8

| # | Loi | Nguyen nhan | Cach fix |
|---|---|---|---|
| 17 | Machine client secret = `None` | Client tao khong co `--generate-secret` | Tao client moi voi `--generate-secret` + resource server cho client_credentials flow |
| 18 | `Tool already exists` | Tool da add tu lan chay truoc | Bo qua, tiep tuc deploy |

### Cleanup

| # | Loi | Nguyen nhan | Cach fix |
|---|---|---|---|
| 19 | `agentcore status` van hien "Deployed" sau khi xoa stack | CLI doc tu file local `deployed-state.json` | Xoa file `agentcore/.cli/deployed-state.json` |
| 20 | `unknown command 'destroy'` | AgentCore CLI khong co lenh destroy | Dung `aws cloudformation delete-stack` truc tiep |

---

## Ghi Chu Quan Trong

1. **Region nhat quan**: Tat ca resources phai o cung region (us-east-1).
2. **Token het han**: Cognito access token het han sau 60 phut. Lay lai bang `aws cognito-idp initiate-auth`.
3. **Deploy order**: Gateway targets phai deploy truoc khi them Cedar policies reference chung.
4. **Cedar syntax**: Entity literals PHAI co quotes: `AgentCore::Action::"TargetName___tool_name"`.
5. **Windows specifics**: 
   - Dung `$env:PYTHONUTF8="1"` truoc khi chay agent
   - Flask frontend dung `debug=False` de tranh watchdog issues
   - URL-encode ARN khi goi REST API
6. **agentcore status tin cay**: Luon kiem tra resources THUC TE tren AWS Console hoac AWS CLI, khong chi tin vao local state file.
