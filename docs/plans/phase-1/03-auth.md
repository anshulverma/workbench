# Step 3: Auth Endpoints

Parent spec: [workbench-design.md](../2026-05-21-workbench-design.md)
Depends on: [02-database-schema.md](02-database-schema.md)

## Goal

User registration, login, and token-based authentication. All subsequent API endpoints will require a valid token.

## Files to Create

```
server/
  api/
    __init__.py
    auth.py              -- registration, login, token generation
  auth/
    __init__.py
    password.py          -- password hashing (bcrypt)
    token.py             -- JWT token creation and validation
    dependencies.py      -- FastAPI Depends for auth
  schemas/
    __init__.py
    auth.py              -- Pydantic request/response models
```

## Update requirements.txt

Add:
```
python-jose[cryptography]>=3.3
passlib[bcrypt]>=1.7
```

## Endpoints

### POST /auth/register

Request:
```json
{
  "email": "user@example.com",
  "name": "Anshul Verma",
  "password": "..."
}
```

Response (201):
```json
{
  "id": "uuid",
  "email": "user@example.com",
  "name": "Anshul Verma",
  "created_at": "2026-05-22T..."
}
```

Errors:
- 409 if email already exists

### POST /auth/login

Request:
```json
{
  "email": "user@example.com",
  "password": "..."
}
```

Response (200):
```json
{
  "access_token": "jwt-token",
  "token_type": "bearer",
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "name": "Anshul Verma"
  }
}
```

Errors:
- 401 if invalid credentials

### POST /auth/token

Generate a long-lived API token for the Claude Code plugin and MCP server. Requires an existing session token.

Request: empty (authenticated via bearer token)

Response (200):
```json
{
  "api_token": "wb_...",
  "expires_at": null
}
```

Long-lived tokens do not expire by default. They can be revoked by the user.

## Auth Dependencies

```python
async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Validate JWT or API token and return the user."""
```

All subsequent endpoints use `Depends(get_current_user)`.

## Token Format

- **Session tokens**: JWT with `sub` (user ID), `exp` (24h), signed with `SECRET_KEY`
- **API tokens**: random 64-char hex string prefixed with `wb_`, stored hashed in a new `api_tokens` table

### api_tokens table (add to models)

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| user_id | UUID | FK → users |
| token_hash | String(255) | bcrypt hash of the token |
| created_at | DateTime | |
| revoked_at | DateTime | nullable |

## Password Hashing

- Use `passlib` with bcrypt
- `hash_password(plain) → hash`
- `verify_password(plain, hash) → bool`

## Implementation Plan

_To be finalized._

## Acceptance Criteria

1. Register a new user — returns 201 with user data
2. Register with duplicate email — returns 409
3. Login with correct credentials — returns JWT token
4. Login with wrong password — returns 401
5. Authenticated request with valid JWT — succeeds
6. Authenticated request with invalid/expired JWT — returns 401
7. Generate API token — returns `wb_...` prefixed token
8. Authenticated request with valid API token — succeeds
9. Passwords are bcrypt-hashed in the database (not plaintext)
