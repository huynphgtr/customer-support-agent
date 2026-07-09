# Hands-On Guide: Amazon Bedrock AgentCore Workshop (Lab 1-8)

## General Information

| Info | Value |
|---|---|
| **AWS Account ID** | `` |
| **Region** | `us-east-1` |
| **Project Name** | `CustomerSupport2` |
| **Stack Name** | `AgentCore-CustomerSupport2-default` |
| **AgentCore CLI** | `@aws/agentcore` (npm) |
| **Python** | 3.12 |
| **OS** | Windows |

---

## Table of Contents

1. [Lab 1: Building the Agent Prototype](#lab-1-building-the-agent-prototype)
2. [Lab 2: Adding Memory](#lab-2-adding-memory)
3. [Lab 3: Scaling Tools with Gateway](#lab-3-scaling-tools-with-gateway)
4. [Lab 4: Production Features and Security](#lab-4-production-features-and-security)
5. [Lab 5: Online Evaluations](#lab-5-online-evaluations)
6. [Lab 6: Web Chat Frontend](#lab-6-web-chat-frontend)
7. [Lab 7: Policy Engine (Cedar)](#lab-7-policy-engine-cedar)
8. [Lab 8: AgentCore Harness (Zero-code)](#lab-8-agentcore-harness-zero-code)
9. [Cleanup - Delete Resources](#cleanup---delete-resources)
10. [Troubleshooting - Errors Encountered](#troubleshooting---errors-encountered)

---

## Lab 1: Building the Agent Prototype

### Objective
Create a customer support agent with 3 tools: return policy lookup, product info search, and Exa web search.

### Step 1: Install Prerequisites

```powershell
# Install AgentCore CLI (npm)
npm install -g @aws/agentcore

# Install uv (Python package manager - REQUIRED for agentcore dev)
pip install uv
```

### Step 2: Create Project

```powershell
agentcore create
# Select: Strands Agents, Amazon Bedrock, Memory optional, CodeZip
# Project name: CustomerSupport2
```

### Step 3: Replace main.py

Replace the entire content of `app/CustomerSupport2/main.py` with customer support code:
- 2 tools: `get_return_policy()`, `get_product_info()`
- System prompt for customer support
- Exa MCP client for web search
- Add "Do NOT use emojis" to system prompt (fixes Unicode error on Windows)

### Step 4: Run Local Dev Server

```powershell
# Set UTF-8 before running (fixes emoji error)
$env:PYTHONUTF8 = "1"
agentcore dev
```

### Step 5: Test Agent

```powershell
# In a separate terminal
agentcore invoke --dev '{"prompt":"What is the return policy for electronics?"}'
```

### Step 6: Deploy to AWS

```powershell
agentcore deploy -y -v
```

### Step 7: Test Deployed Agent

```powershell
agentcore invoke "What is the return policy for electronics?" --stream
```

---

## Lab 2: Adding Memory

### Objective
Add AgentCore Memory (SEMANTIC + SUMMARIZATION) so the agent remembers users across sessions.

### Step 1: Update agentcore.json - Add Memory Strategies

In `agentcore/agentcore.json`, update the `memories` section:

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

**Note:** Use key `"type"` NOT `"strategyName"`.

### Step 2: Create memory/session.py

Create file `app/CustomerSupport2/memory/session.py`:

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

### Step 3: Update main.py

- Import memory session manager
- Modify `get_or_create_agent()` to accept `session_id`, `user_id`
- Add `session_manager` to Agent
- Update `invoke()` to get user_id from headers (use `.get()` to avoid KeyError)

### Step 4: Add requestHeaderAllowlist to Runtime Config

```json
"requestHeaderAllowlist": [
  "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id"
]
```

### Step 5: Deploy and Test

```powershell
agentcore deploy -y -v

# Test memory
$SESSION_A = [guid]::NewGuid().ToString()
agentcore invoke "My name is Sarah" --session-id $SESSION_A --user-id Sarah --stream

# Wait 2 minutes for memory extraction
Start-Sleep -Seconds 120

$SESSION_B = [guid]::NewGuid().ToString()
agentcore invoke "Do you know anything about me?" --session-id $SESSION_B --user-id Sarah --stream
```

---

## Lab 3: Scaling Tools with Gateway

### Objective
Expose a Lambda warranty check function through AgentCore Gateway (MCP endpoint).

### Step 1: Create Lambda Function (if not already existing)

Create file `lambda/warranty_check.py`:

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
# Create IAM role
aws iam create-role --region us-east-1 --role-name workshop-warranty-check-role --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name workshop-warranty-check-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# Wait 10s for IAM propagation
Start-Sleep -Seconds 10

# Zip and deploy
Compress-Archive -Path "lambda\warranty_check.py" -DestinationPath "lambda\warranty_check.zip" -Force
aws lambda create-function --region us-east-1 --function-name workshop-warranty-check --runtime python3.12 --role arn:aws:iam::<ACCOUNT_ID>:role/workshop-warranty-check-role --handler warranty_check.handler --zip-file fileb://lambda/warranty_check.zip
```

### Step 2: Create Tool Schema

Create file `app/CustomerSupport2/tool/warranty_schema.json`:

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

### Step 3: Add Gateway and Target

```powershell
agentcore add gateway --name my-gateway --runtimes CustomerSupport2
agentcore add gateway-target --type lambda-function-arn --name WarrantyCheck --lambda-arn <LAMBDA_ARN> --tool-schema-file app/CustomerSupport2/tool/warranty_schema.json --gateway my-gateway
```

### Step 4: Update mcp_client/client.py

Add function `get_gateway_mcp_client()`:

```python
def get_gateway_mcp_client() -> MCPClient | None:
    url = os.environ.get("AGENTCORE_GATEWAY_MY_GATEWAY_URL")
    if not url:
        return None
    return MCPClient(lambda: streamablehttp_client(url))
```

### Step 5: Update main.py

- Import `get_gateway_mcp_client`
- Add to `mcp_clients` list
- Remove `warranty_months` from PRODUCTS dict (now fetched via Gateway)

### Step 6: Deploy and Test

```powershell
agentcore deploy -y -v
agentcore invoke "Check the warranty for PROD-003" --session-id $([guid]::NewGuid().ToString()) --user-id Sarah --stream
```

---

## Lab 4: Production Features and Security

### Objective
Session continuity, observability, and JWT authentication with Cognito.

### Step 1: Create Cognito User Pool

```powershell
# Create User Pool
$POOL_ID = aws cognito-idp create-user-pool --region us-east-1 --pool-name "workshop-agentcore-pool" --auto-verified-attributes email --username-attributes email --policies "PasswordPolicy={MinimumLength=8,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=false}" --query "UserPool.Id" --output text

# Create Web Client (public, no secret)
$WEB_CLIENT_ID = aws cognito-idp create-user-pool-client --region us-east-1 --user-pool-id $POOL_ID --client-name "workshop-web-client" --explicit-auth-flows "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" --access-token-validity 60 --token-validity-units "AccessToken=minutes" --query "UserPoolClient.ClientId" --output text

# Create Machine Client (with secret, needed for Lab 8)
# First create Resource Server
aws cognito-idp create-resource-server --region us-east-1 --user-pool-id $POOL_ID --identifier "agentcore-gateway" --name "AgentCore Gateway" --scopes "ScopeName=read,ScopeDescription=Read access"

$M2M_CLIENT = aws cognito-idp create-user-pool-client --region us-east-1 --user-pool-id $POOL_ID --client-name "workshop-m2m-client" --generate-secret --explicit-auth-flows "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" --supported-identity-providers "COGNITO" --allowed-o-auth-flows "client_credentials" --allowed-o-auth-scopes "agentcore-gateway/read" --allowed-o-auth-flows-user-pool-client --output json
```

### Step 2: Update agentcore.json - Add JWT Auth

In runtime config:

```json
"authorizerType": "CUSTOM_JWT",
"authorizerConfiguration": {
  "customJwtAuthorizer": {
    "discoveryUrl": "https://cognito-idp.us-east-1.amazonaws.com/<POOL_ID>/.well-known/openid-configuration",
    "allowedClients": ["<WEB_CLIENT_ID>", "<M2M_CLIENT_ID>"]
  }
}
```

Add `"Authorization"` to `requestHeaderAllowlist`.

### Step 3: Remove Old Gateway, Create Secured Gateway

```powershell
agentcore remove gateway --name my-gateway -y
agentcore add gateway --name my-gateway-secure --runtimes CustomerSupport2 --authorizer-type CUSTOM_JWT --discovery-url $COGNITO_DISCOVERY_URL --allowed-clients "$WEB_CLIENT_ID,$M2M_CLIENT_ID"

# Re-add target
agentcore add gateway-target --type lambda-function-arn --name WarrantyCheck --lambda-arn <LAMBDA_ARN> --tool-schema-file app/CustomerSupport2/tool/warranty_schema.json --gateway my-gateway-secure
```

### Step 4: Update main.py - Add extract_user_id() from JWT

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

### Step 5: Update client.py - Forward Auth Header

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

### Step 6: Add PyJWT Dependency

Add `"PyJWT >= 2.8.0"` to `pyproject.toml` dependencies.

### Step 7: Deploy and Test

```powershell
agentcore deploy -y -v

# Create test user
aws cognito-idp admin-create-user --region us-east-1 --user-pool-id $POOL_ID --username workshopuser@example.com --temporary-password "TempPass1!" --user-attributes "Name=email,Value=workshopuser@example.com" "Name=email_verified,Value=true" --message-action SUPPRESS
aws cognito-idp admin-set-user-password --region us-east-1 --user-pool-id $POOL_ID --username workshopuser@example.com --password "WorkshopPass1!" --permanent

# Get token
$TOKEN = aws cognito-idp initiate-auth --region us-east-1 --auth-flow USER_PASSWORD_AUTH --client-id $WEB_CLIENT_ID --auth-parameters "USERNAME=workshopuser@example.com,PASSWORD=WorkshopPass1!" --query 'AuthenticationResult.AccessToken' --output text

# Test with token (should succeed)
$SESSION_3 = [guid]::NewGuid().ToString()
agentcore invoke "What is the return policy for electronics?" --session-id $SESSION_3 --bearer-token "$TOKEN" --stream

# Test without token (should fail)
agentcore invoke "Hello" --session-id $SESSION_3 --stream --json
```

---

## Lab 5: Online Evaluations

### Objective
Continuous quality monitoring with built-in evaluators.

### Step 1: Add Online Eval Config

```powershell
agentcore add online-eval --name QualityMonitor --runtime CustomerSupport2 --evaluator Builtin.GoalSuccessRate Builtin.Correctness Builtin.ToolSelectionAccuracy --sampling-rate 100 --enable-on-create
```

### Step 2: Deploy

```powershell
agentcore deploy -y -v
```

### Step 3: Generate Test Interactions

```powershell
$SESSION_EVAL = [guid]::NewGuid().ToString()
agentcore invoke "What can you tell me about the Smart Watch?" --session-id $SESSION_EVAL --bearer-token "$TOKEN" --stream
agentcore invoke "Check the warranty status for product PROD-001" --session-id $SESSION_EVAL --bearer-token "$TOKEN" --stream
```

### Step 4: Run On-Demand Evaluation

**Note:** Use `--session-id` or `--trace-id` specifically. Do NOT use `--days 1` (may fail with scope error).

```powershell
# Get trace IDs
agentcore traces list --limit 5

# Eval by session
agentcore run eval --runtime CustomerSupport2 --evaluator Builtin.GoalSuccessRate Builtin.Correctness --session-id <SESSION_ID>

# Or eval by trace
agentcore run eval --runtime CustomerSupport2 --evaluator Builtin.GoalSuccessRate --trace-id <TRACE_ID>
```

### Step 5: View Results

```powershell
agentcore evals history --runtime CustomerSupport2 --limit 5
```

### Step 6: Pause/Resume (Optional)

```powershell
agentcore pause online-eval QualityMonitor
agentcore resume online-eval QualityMonitor
```

---

## Lab 6: Web Chat Frontend

### Objective
Flask web UI with Cognito login (OAuth authorization code flow + PKCE).

### Step 1: Install Flask

```powershell
cd app\CustomerSupport2
uv add flask boto3 requests
cd ..\..
```

### Step 2: Create Cognito Hosted UI Domain

```powershell
aws cognito-idp create-user-pool-domain --region us-east-1 --user-pool-id <POOL_ID> --domain "workshop-agentcore-cs2"

# Update web client with OAuth settings
aws cognito-idp update-user-pool-client --region us-east-1 --user-pool-id <POOL_ID> --client-id <WEB_CLIENT_ID> --explicit-auth-flows "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" --supported-identity-providers "COGNITO" --callback-urls "http://localhost:8501/callback" --logout-urls "http://localhost:8501/" --allowed-o-auth-flows "code" --allowed-o-auth-scopes "openid" "email" "profile" --allowed-o-auth-flows-user-pool-client
```

### Step 3: Create Frontend Directory Structure

```powershell
mkdir app\CustomerSupport2\frontend\templates
```

### Step 4: Create frontend.py

File `app/CustomerSupport2/frontend/frontend.py` - Flask backend with:
- **PKCE support** (CRITICAL - Cognito public client requires PKCE)
- Static secret key (do NOT use `os.urandom()` to avoid session loss on reload)
- URL-encode ARN when calling AgentCore API (`urllib.parse.quote()`)
- SSE response parser (strip JSON quotes from `data: "text"` lines)
- `debug=False` (avoid watchdog restart killing sessions)

**Key code patterns in frontend.py:**

```python
from urllib.parse import quote

# URL-encode ARN
ENCODED_ARN = quote(RUNTIME_ARN, safe="")
INVOKE_URL = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{ENCODED_ARN}/invocations"

# Static secret key (NOT random - survives process restarts)
app.secret_key = "workshop-agentcore-dev-secret-key-do-not-use-in-prod"

# PKCE helpers
def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]

def generate_code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

# SSE Parser - must strip JSON quotes from each data line
for line in resp.text.split("\n"):
    line = line.strip()
    if line.startswith("data: "):
        data = line[6:]
        if data.startswith('"') and data.endswith('"'):
            data = json.loads(data)  # decode JSON string
        full_response += data
```

### Step 5: Create Templates

- `templates/login.html` - Login page with link to Cognito hosted UI
- `templates/index.html` - Chat UI with quick action buttons

### Step 6: Run Frontend

```powershell
cd app\CustomerSupport2\frontend
uv run python frontend.py
# Open browser: http://localhost:8501
# Login: workshopuser@example.com / WorkshopPass1!
```

---

## Lab 7: Policy Engine (Cedar)

### Objective
Fine-grained authorization - limit refunds to < $100, permit warranty checks for all users.

### Step 1: Create Lambda process_refund

Create file `lambda/process_refund.py`:

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

### Step 2: Create Tool Schema and Add Gateway Target

Create `app/CustomerSupport2/tool/refund_schema.json`:
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

### Step 3: Create Policy Engine

```powershell
agentcore add policy-engine --name CustomerSupportPolicyEngine --description "Governs customer support agent tool access" --attach-to-gateways my-gateway-secure --attach-mode ENFORCE
```

### Step 4: Deploy TARGET First (Without Policies)

**IMPORTANT:** Deploy the gateway target BEFORE adding policies. Deploying both simultaneously causes "unrecognized action" error.

```powershell
agentcore deploy -y -v
```

### Step 5: Add Cedar Policies to agentcore.json

**CRITICAL NOTES:**
- Use escaped quotes `\"...\"` for Cedar entity literals inside JSON
- Use `"validationMode": "IGNORE_ALL_FINDINGS"` to bypass validation issues

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

Add `policyEngineConfiguration` to gateway:
```json
"policyEngineConfiguration": {
  "policyEngineName": "CustomerSupportPolicyEngine",
  "mode": "ENFORCE"
}
```

### Step 6: Deploy and Test

```powershell
agentcore deploy -y -v
```

Test in chat UI:
- `"Refund $50 for order ORD-12345, item damaged"` -> Succeeds
- `"Refund $500 for order ORD-67890"` -> Denied by policy
- `"Check warranty for PROD-002"` -> Succeeds

---

## Lab 8: AgentCore Harness (Zero-code)

### Objective
Create a declarative agent without writing any code - CLI configuration only.

### Step 1: Create Harness

```powershell
agentcore add harness --name OrderResearchAgent --model-provider bedrock --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 --system-prompt "You are an order research specialist. Help customers investigate order issues, check warranties, and produce detailed analysis reports. Always be thorough and provide structured summaries. Save reports to /tmp/ when asked." --tools agentcore_code_interpreter
```

### Step 2: Create Machine Client (with Secret)

Cognito `client_credentials` flow requires a client with a secret and a resource server.

```powershell
# Create resource server (if not already done)
aws cognito-idp create-resource-server --region us-east-1 --user-pool-id <POOL_ID> --identifier "agentcore-gateway" --name "AgentCore Gateway" --scopes "ScopeName=read,ScopeDescription=Read access"

# Create M2M client with secret
aws cognito-idp create-user-pool-client --region us-east-1 --user-pool-id <POOL_ID> --client-name "workshop-m2m-client" --generate-secret --explicit-auth-flows "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" --supported-identity-providers "COGNITO" --allowed-o-auth-flows "client_credentials" --allowed-o-auth-scopes "agentcore-gateway/read" --allowed-o-auth-flows-user-pool-client
```

Add the M2M Client ID to `allowedClients` in both the runtime and gateway sections of `agentcore.json`.

### Step 3: Create Credential Provider

```powershell
$COGNITO_SCOPE = "agentcore-gateway/read"
agentcore add credential --type oauth --name gateway-egress-oauth --discovery-url "https://cognito-idp.us-east-1.amazonaws.com/<POOL_ID>/.well-known/openid-configuration" --client-id <M2M_CLIENT_ID> --client-secret <M2M_CLIENT_SECRET> --scopes $COGNITO_SCOPE
```

### Step 4: Add Gateway Tool to Harness

```powershell
$GATEWAY_ARN = "<GATEWAY_ARN_FROM_DEPLOYED_STATE>"
$PROVIDER_ARN = "arn:aws:bedrock-agentcore:us-east-1:<ACCOUNT_ID>:token-vault/default/oauth2credentialprovider/gateway-egress-oauth"

agentcore add tool --harness OrderResearchAgent --type agentcore_gateway --name my-gateway-secure --gateway-arn $GATEWAY_ARN --outbound-auth oauth --provider-arn $PROVIDER_ARN --scopes $COGNITO_SCOPE --grant-type CLIENT_CREDENTIALS
```

### Step 5: Deploy and Test

```powershell
agentcore deploy -y -v

# Test basic invocation
$SESSION = [guid]::NewGuid().ToString()
agentcore invoke --harness OrderResearchAgent --session-id $SESSION --actor-id "analyst-1" "Check the warranty for PROD-001 and PROD-003."

# Shell access (inspect files created by agent)
agentcore invoke --exec --harness OrderResearchAgent --session-id $SESSION "cat /tmp/warranty_report.md"

# Override model per invocation
agentcore invoke --harness OrderResearchAgent --model-id us.amazon.nova-2-lite-v1:0 --session-id $SESSION --actor-id "analyst-1" "Summarize in 3 bullet points."

# Test policy enforcement (should be denied - amount >= 100)
agentcore invoke --harness OrderResearchAgent --session-id $([guid]::NewGuid().ToString()) --actor-id "analyst-1" "Process a refund of $500 for order ORD-12345"
```

### Step 6 (Bonus): Human-in-the-Loop

```powershell
# Add inline function tool
agentcore add tool --harness OrderResearchAgent --type inline_function --name approve_exception --description "Request manager approval for refund exceeding limit." --input-schema '{"type":"object","properties":{"order_id":{"type":"string"},"amount":{"type":"number"},"reason":{"type":"string"}},"required":["order_id","amount","reason"]}'

agentcore deploy -y -v

# Test HITL (requires Python script - see lab guide for test_hitl.py)
$env:HARNESS_ARN = aws bedrock-agentcore-control list-harnesses --query "harnesses[?contains(harnessName, 'OrderResearchAgent')].arn | [0]" --output text
python3 app/OrderResearchAgent/test_hitl.py
```

---

## Cleanup - Delete Resources

### Delete Entire AgentCore Stack

```powershell
# AgentCore CLI does NOT have a "destroy" command
# Delete directly via CloudFormation
aws cloudformation delete-stack --region us-east-1 --stack-name AgentCore-CustomerSupport2-default

# Wait and verify
aws cloudformation describe-stacks --region us-east-1 --stack-name AgentCore-CustomerSupport2-default --query "Stacks[0].StackStatus" --output text
# Expected: "Stack does not exist" (deletion complete)
```

### Delete Manually-Created Resources (outside stack)

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

# OAuth credential (if still exists)
aws bedrock-agentcore-control delete-oauth2-credential-provider --region us-east-1 --name gateway-egress-oauth
```

### Delete Local State File

```powershell
# Delete deployed-state.json so agentcore status no longer shows stale "Deployed"
Remove-Item agentcore\.cli\deployed-state.json -Force
```

### Verify Complete Cleanup

```powershell
# Check no stacks remain
aws cloudformation list-stacks --region us-east-1 --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query "StackSummaries[?contains(StackName, 'AgentCore')]" --output table

# Check no Lambda functions
aws lambda list-functions --region us-east-1 --query "Functions[].FunctionName" --output text

# Check no Cognito pools
aws cognito-idp list-user-pools --region us-east-1 --max-results 10 --output table

# Verify agentcore status shows "Local only"
agentcore status
```

---

## Troubleshooting - Errors Encountered

### Lab 1

| # | Error | Root Cause | Fix |
|---|---|---|---|
| 1 | `[WinError 2] The system cannot find the file specified` | CLI calls `uv` but it's not installed | `pip install uv` |
| 2 | `Method Not Allowed` | Accessing invoke URL via GET (browser) | Use POST request or `agentcore invoke --dev` |
| 3 | `Got unexpected extra argument(s)` | Shell splits JSON payload into multiple args due to spaces | Use single-quote: `'{"prompt":"Hello"}'` |
| 4 | `charmap codec can't encode character \U0001f44b` | Windows console doesn't support Unicode emoji | Add "Do NOT use emojis" to system prompt, or set `$env:PYTHONUTF8="1"` |

### Lab 2

| # | Error | Root Cause | Fix |
|---|---|---|---|
| 5 | `memories[0].strategies[0].type: expected "SEMANTIC"` | Used key `strategyName` instead of `type` in JSON | Change to `"type": "SEMANTIC"` |
| 6 | `KeyError: 'x-amzn-bedrock-agentcore-runtime-custom-user-id'` | New CLI passes user_id differently, header doesn't exist | Use `.get()` with fallback instead of `dict['key']` |

### Lab 3

| # | Error | Root Cause | Fix |
|---|---|---|---|
| 7 | `ParameterNotFound` (SSM) | Lambda not created by prerequisites stack | Create Lambda manually via AWS CLI |

### Lab 4

| # | Error | Root Cause | Fix |
|---|---|---|---|
| 8 | `ParameterNotFound` (Cognito SSM params) | No prerequisites CloudFormation stack | Create Cognito resources manually |

### Lab 5

| # | Error | Root Cause | Fix |
|---|---|---|---|
| 9 | `Provided input has no spans with supported scope` | `--days 1` queries old traces without strands spans | Use `--session-id` or `--trace-id` instead of `--days` |

### Lab 6

| # | Error | Root Cause | Fix |
|---|---|---|---|
| 10 | `400 Client Error` on token exchange | Cognito public client (no secret) requires PKCE | Add code_verifier + code_challenge (S256) to OAuth flow |
| 11 | Login OK but no chat page | `os.urandom(32)` generates new secret key on each Flask reload -> session lost | Use static secret key string |
| 12 | Watchdog restart during OAuth callback | File changes in `.venv` trigger reload -> code_verifier lost | Set `debug=False` |
| 13 | `404 Not Found` when invoking agent | ARN contains `:` and `/` not URL-encoded | Use `urllib.parse.quote(ARN, safe="")` |
| 14 | Response shows raw SSE format | Parser doesn't strip JSON quotes from `data: "text"` lines | Decode JSON string before concatenating |

### Lab 7

| # | Error | Root Cause | Fix |
|---|---|---|---|
| 15 | `expected kw_in, kw_has, kw_like...` (Cedar parse error) | Cedar entity literals missing double quotes | Add escaped quotes `\"...\"` in JSON statement |
| 16 | `unrecognized action ProcessRefund___process_refund` | Target not yet deployed (previous rollback), Cedar can't find action | Deploy target FIRST (no policy), then add policy with `validationMode: IGNORE_ALL_FINDINGS` |

### Lab 8

| # | Error | Root Cause | Fix |
|---|---|---|---|
| 17 | Machine client secret = `None` | Client created without `--generate-secret` | Create new client with `--generate-secret` + resource server for client_credentials flow |
| 18 | `Tool already exists` | Tool was added in a previous run | Skip and continue with deploy |

### Cleanup

| # | Error | Root Cause | Fix |
|---|---|---|---|
| 19 | `agentcore status` still shows "Deployed" after deleting stack | CLI reads from local `deployed-state.json` file | Delete `agentcore/.cli/deployed-state.json` |
| 20 | `unknown command 'destroy'` | AgentCore CLI has no destroy command | Use `aws cloudformation delete-stack` directly |

---

## Important Notes

1. **Consistent region**: All resources must be in the same region (us-east-1).
2. **Token expiration**: Cognito access token expires after 60 minutes. Refresh with `aws cognito-idp initiate-auth`.
3. **Deploy order**: Gateway targets must be deployed BEFORE adding Cedar policies that reference them.
4. **Cedar syntax**: Entity literals MUST have quotes: `AgentCore::Action::"TargetName___tool_name"`.
5. **Windows-specific issues**:
   - Use `$env:PYTHONUTF8="1"` before running agent
   - Flask frontend must use `debug=False` to avoid watchdog issues
   - URL-encode ARN when calling REST API
6. **Trust but verify**: Always check actual resources on AWS Console or AWS CLI. Do not rely solely on the local state file for accuracy.
7. **Cost management**: Run `aws cloudformation delete-stack` immediately when done. The `agentcore status` showing "Local only" confirms nothing is running on AWS.
