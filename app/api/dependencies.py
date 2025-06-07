#!/usr/bin/env python3
"""
Dependências FastAPI
===================

Define dependências reutilizáveis para endpoints da API:
- Validação de autenticação
- Rate limiting
- Validação de parâmetros
- Injeção de serviços
- Logging de requests
"""

import time
import hashlib
import logging
from typing import Optional, Dict, Any, Annotated
from fastapi import Depends, HTTPException, Header, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.services import get_orchestrator_service, get_queue_manager, get_storage_service

logger = logging.getLogger(__name__)

# Security schemes
security = HTTPBearer(auto_error=False) if settings.API_KEY_ENABLED else None


class AuthenticationError(HTTPException):
    """Erro de autenticação customizado"""
    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"}
        )


class RateLimitError(HTTPException):
    """Erro de rate limiting customizado"""
    def __init__(self, detail: str = "Rate limit exceeded"):
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": "60"}
        )


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)] = None,
    x_api_key: Annotated[str, Header()] = None
) -> Optional[Dict[str, Any]]:
    """
    Valida autenticação do usuário
    
    Suporta:
    - Bearer token no header Authorization
    - API key no header X-API-Key
    """
    if not settings.API_KEY_ENABLED:
        # Autenticação desabilitada - retornar usuário anônimo
        return {
            "user_id": "anonymous",
            "user_type": "anonymous",
            "permissions": ["read", "write"],
            "authenticated": False
        }
    
    # Verificar Bearer token
    if credentials and credentials.credentials:
        token = credentials.credentials
        user = validate_bearer_token(token)
        if user:
            return user
    
    # Verificar API key
    if x_api_key:
        user = validate_api_key(x_api_key)
        if user:
            return user
    
    # Nenhuma autenticação válida
    raise AuthenticationError("Invalid or missing authentication credentials")


def validate_bearer_token(token: str) -> Optional[Dict[str, Any]]:
    """Valida Bearer token"""
    try:
        # Em produção, validar contra JWT ou banco de dados
        # Por enquanto, validação simples
        
        if not token or len(token) < 10:
            return None
        
        # Verificar no Redis se token está na blacklist
        redis_client = get_redis_client()
        if redis_client.cache_exists(f"blacklisted_token:{token}"):
            return None
        
        # Token válido - retornar usuário
        return {
            "user_id": f"user_{hashlib.md5(token.encode()).hexdigest()[:8]}",
            "user_type": "authenticated",
            "permissions": ["read", "write", "admin"],
            "authenticated": True,
            "auth_method": "bearer_token"
        }
        
    except Exception as e:
        logger.warning(f"Bearer token validation failed: {e}")
        return None


def validate_api_key(api_key: str) -> Optional[Dict[str, Any]]:
    """Valida API key"""
    try:
        # Em produção, validar contra banco de dados
        # Por enquanto, validação simples
        
        if not api_key or len(api_key) < 20:
            return None
        
        # Verificar formato básico (prefixo + hash)
        if not api_key.startswith("ocr_"):
            return None
        
        # API key válida - retornar usuário
        return {
            "user_id": f"api_{hashlib.md5(api_key.encode()).hexdigest()[:8]}",
            "user_type": "api_client",
            "permissions": ["read", "write"],
            "authenticated": True,
            "auth_method": "api_key"
        }
        
    except Exception as e:
        logger.warning(f"API key validation failed: {e}")
        return None


def check_rate_limit(
    request: Request,
    user: Annotated[Dict[str, Any], Depends(get_current_user)] = None
) -> bool:
    """
    Verifica rate limiting
    
    Aplica limites diferentes baseado no tipo de usuário
    """
    if not settings.RATE_LIMIT_ENABLED:
        return True
    
    try:
        # Identificar cliente
        if user and user.get("authenticated"):
            client_id = user["user_id"]
            user_type = user.get("user_type", "authenticated")
        else:
            # Usar IP para usuários não autenticados
            client_ip = request.client.host
            client_id = f"ip_{client_ip}"
            user_type = "anonymous"
        
        # Determinar limites baseado no tipo de usuário
        if user_type == "api_client":
            limit = settings.RATE_LIMIT_CALLS * 5  # API clients tem limite maior
        elif user_type == "authenticated":
            limit = settings.RATE_LIMIT_CALLS * 2  # Usuários autenticados
        else:
            limit = settings.RATE_LIMIT_CALLS  # Usuários anônimos
        
        window = settings.RATE_LIMIT_PERIOD
        
        # Verificar rate limit no Redis
        redis_client = get_redis_client()
        if not redis_client.check_rate_limit(client_id, limit, window):
            raise RateLimitError(
                f"Rate limit exceeded. Limit: {limit} requests per {window} seconds"
            )
        
        return True
        
    except RateLimitError:
        raise
    except Exception as e:
        logger.warning(f"Rate limit check failed: {e}")
        # Em caso de erro, permitir (fail-open)
        return True


def get_request_context(request: Request) -> Dict[str, Any]:
    """
    Extrai contexto da requisição para logging e métricas
    """
    return {
        "method": request.method,
        "url": str(request.url),
        "path": request.url.path,
        "query_params": dict(request.query_params),
        "client_host": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "content_type": request.headers.get("content-type"),
        "content_length": request.headers.get("content-length"),
        "timestamp": time.time()
    }


def validate_file_upload(
    request: Request,
    max_file_size: int = None
) -> bool:
    """
    Valida upload de arquivo
    """
    max_size = max_file_size or settings.MAX_FILE_SIZE
    
    # Verificar Content-Length
    content_length = request.headers.get("content-length")
    if content_length:
        if int(content_length) > max_size:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File too large. Maximum size: {max_size / (1024*1024):.1f}MB"
            )
    
    return True


def get_orchestrator_service_dep():
    """Dependência para injetar orchestrator service"""
    return get_orchestrator_service()


def get_queue_manager_dep():
    """Dependência para injetar queue manager"""
    return get_queue_manager()


def get_storage_service_dep():
    """Dependência para injetar storage service"""
    return get_storage_service()


def get_redis_client_dep():
    """Dependência para injetar Redis client"""
    return get_redis_client()


def validate_admin_permission(
    user: Annotated[Dict[str, Any], Depends(get_current_user)]
) -> Dict[str, Any]:
    """
    Valida permissões de administrador
    """
    if not user.get("authenticated"):
        raise AuthenticationError("Authentication required for admin operations")
    
    permissions = user.get("permissions", [])
    if "admin" not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator permissions required"
        )
    
    return user


def validate_write_permission(
    user: Annotated[Dict[str, Any], Depends(get_current_user)]
) -> Dict[str, Any]:
    """
    Valida permissões de escrita
    """
    permissions = user.get("permissions", [])
    if "write" not in permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write permissions required"
        )
    
    return user


def create_request_id() -> str:
    """
    Cria ID único para a requisição
    """
    import uuid
    return str(uuid.uuid4())


def log_request_start(
    request: Request,
    request_id: Annotated[str, Depends(create_request_id)],
    user: Annotated[Dict[str, Any], Depends(get_current_user)] = None
):
    """
    Log do início da requisição
    """
    context = get_request_context(request)
    
    logger.info(
        f"Request started: {request_id} - {context['method']} {context['path']} "
        f"from {context['client_host']} by {user.get('user_id', 'anonymous') if user else 'anonymous'}"
    )
    
    # Salvar contexto no Redis para uso posterior
    try:
        redis_client = get_redis_client()
        redis_client.cache_set(
            f"request_context:{request_id}",
            {
                "context": context,
                "user": user,
                "start_time": time.time()
            },
            ttl=3600  # 1 hora
        )
    except Exception as e:
        logger.warning(f"Failed to save request context: {e}")
    
    return request_id


def validate_content_type(
    request: Request,
    allowed_types: list = None
) -> bool:
    """
    Valida Content-Type da requisição
    """
    if not allowed_types:
        allowed_types = [
            "application/json",
            "multipart/form-data",
            "application/x-www-form-urlencoded"
        ]
    
    content_type = request.headers.get("content-type", "").split(";")[0]
    
    if content_type and content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type: {content_type}. "
                   f"Allowed types: {', '.join(allowed_types)}"
        )
    
    return True


class CommonDependencies:
    """
    Classe para agrupar dependências comuns
    """
    
    @staticmethod
    def authenticated_user():
        """Usuário autenticado"""
        return Depends(get_current_user)
    
    @staticmethod
    def admin_user():
        """Usuário com permissões de admin"""
        return Depends(validate_admin_permission)
    
    @staticmethod
    def rate_limited():
        """Rate limiting aplicado"""
        return Depends(check_rate_limit)
    
    @staticmethod
    def request_logged():
        """Request com logging"""
        return Depends(log_request_start)
    
    @staticmethod
    def file_upload_validated():
        """Upload de arquivo validado"""
        return Depends(validate_file_upload)


# Dependências pré-configuradas para uso comum
AuthenticatedUser = Annotated[Dict[str, Any], Depends(get_current_user)]
AdminUser = Annotated[Dict[str, Any], Depends(validate_admin_permission)]
RateLimited = Annotated[bool, Depends(check_rate_limit)]
RequestId = Annotated[str, Depends(log_request_start)]
RequestContext = Annotated[Dict[str, Any], Depends(get_request_context)]

# Serviços injetados
OrchestratorService = Annotated[Any, Depends(get_orchestrator_service_dep)]
QueueManager = Annotated[Any, Depends(get_queue_manager_dep)]
StorageService = Annotated[Any, Depends(get_storage_service_dep)]
RedisClient = Annotated[Any, Depends(get_redis_client_dep)]


# Funções utilitárias para middleware
def extract_client_info(request: Request) -> Dict[str, Any]:
    """
    Extrai informações do cliente
    """
    return {
        "ip": request.client.host if request.client else "unknown",
        "user_agent": request.headers.get("user-agent", "unknown"),
        "referer": request.headers.get("referer"),
        "accept_language": request.headers.get("accept-language"),
        "accept_encoding": request.headers.get("accept-encoding")
    }


def is_health_check_request(request: Request) -> bool:
    """
    Verifica se é uma requisição de health check
    """
    health_paths = ["/health", "/ping", "/readiness", "/liveness"]
    return request.url.path in health_paths


def should_skip_auth(request: Request) -> bool:
    """
    Verifica se deve pular autenticação para certas rotas
    """
    public_paths = [
        "/docs",
        "/redoc", 
        "/openapi.json",
        "/health",
        "/ping",
        "/",
        "/favicon.ico"
    ]
    
    return request.url.path in public_paths or is_health_check_request(request)


def get_priority_from_user(user: Dict[str, Any]) -> int:
    """
    Determina prioridade baseada no tipo de usuário
    """
    if not user:
        return 3  # Baixa prioridade para não autenticados
    
    user_type = user.get("user_type", "anonymous")
    
    if user_type == "api_client":
        return 8  # Alta prioridade para API clients
    elif user_type == "authenticated":
        return 6  # Prioridade média para usuários autenticados
    else:
        return 3  # Baixa prioridade para anônimos


# Cache de dependências para otimização
_dependency_cache = {}


def get_cached_dependency(key: str, factory_func, ttl: int = 300):
    """
    Cache de dependências para otimizar performance
    """
    current_time = time.time()
    
    if key in _dependency_cache:
        cached_item = _dependency_cache[key]
        if current_time - cached_item["created_at"] < ttl:
            return cached_item["value"]
    
    # Criar nova instância
    value = factory_func()
    _dependency_cache[key] = {
        "value": value,
        "created_at": current_time
    }
    
    return value


if __name__ == "__main__":
    """Teste das dependências"""
    print("=== API Dependencies Test ===")
    
    # Teste de validação de token
    test_token = "test_token_12345678901234567890"
    user = validate_bearer_token(test_token)
    print(f"Bearer token validation: {user}")
    
    # Teste de validação de API key
    test_api_key = "ocr_1234567890abcdef1234567890abcdef"
    user = validate_api_key(test_api_key)
    print(f"API key validation: {user}")
    
    # Teste de criação de request ID
    request_id = create_request_id()
    print(f"Request ID: {request_id}")
    
    print("\n✅ Dependencies test completed")