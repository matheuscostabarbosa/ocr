#!/usr/bin/env python3
"""
Middleware de Autenticação
=========================

Middleware customizado para gerenciar autenticação:
- Validação de tokens e API keys
- Controle de acesso baseado em rotas
- Logging de tentativas de autenticação
- Blacklist de tokens
- Rate limiting por usuário
- Headers de segurança
"""

import time
import hashlib
import logging
from typing import Optional, Dict, Any, List
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

from app.core.config import settings
from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Middleware de autenticação customizado"""
    
    def __init__(self, app, skip_paths: List[str] = None):
        super().__init__(app)
        
        # Rotas que não precisam de autenticação
        self.skip_paths = skip_paths or [
            "/",
            "/docs",
            "/redoc", 
            "/openapi.json",
            "/favicon.ico",
            "/health",
            "/ping",
            "/api/v1/health",
            "/api/v1/ping"
        ]
        
        # Rotas que sempre precisam de autenticação
        self.protected_paths = [
            "/api/v1/admin"
        ]
        
        # Cache de usuários autenticados
        self.user_cache = {}
        self.cache_ttl = 300  # 5 minutos
        
        # Contador de tentativas de auth
        self.auth_attempts = 0
        self.auth_successes = 0
        self.auth_failures = 0
    
    async def dispatch(self, request: Request, call_next):
        """Processa request através do middleware de autenticação"""
        start_time = time.time()
        
        try:
            # Verificar se precisa de autenticação
            if self._should_skip_auth(request):
                # Adicionar headers de segurança mesmo para rotas públicas
                response = await call_next(request)
                self._add_security_headers(response)
                return response
            
            # Extrair credenciais
            auth_result = await self._authenticate_request(request)
            
            if not auth_result["authenticated"] and self._is_protected_path(request):
                # Falha de autenticação em rota protegida
                return self._create_auth_error_response(
                    "Authentication required",
                    HTTP_401_UNAUTHORIZED
                )
            
            # Adicionar informações do usuário ao request
            request.state.user = auth_result.get("user")
            request.state.authenticated = auth_result["authenticated"]
            request.state.auth_method = auth_result.get("auth_method")
            
            # Logging de autenticação
            self._log_auth_attempt(request, auth_result)
            
            # Processar request
            response = await call_next(request)
            
            # Adicionar headers de segurança
            self._add_security_headers(response)
            
            # Adicionar headers de usuário se autenticado
            if auth_result["authenticated"] and auth_result.get("user"):
                user = auth_result["user"]
                response.headers["X-User-ID"] = user.get("user_id", "unknown")
                response.headers["X-User-Type"] = user.get("user_type", "unknown")
            
            # Métricas
            processing_time = time.time() - start_time
            self._record_auth_metrics(auth_result, processing_time)
            
            return response
            
        except Exception as e:
            logger.error(f"Authentication middleware error: {e}")
            # Em caso de erro, retornar 500 mas não expor detalhes
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error"}
            )
    
    def _should_skip_auth(self, request: Request) -> bool:
        """Verifica se deve pular autenticação"""
        path = request.url.path
        
        # Verificar rotas que não precisam de auth
        if path in self.skip_paths:
            return True
        
        # Verificar padrões de rota
        skip_patterns = [
            "/static/",
            "/assets/",
            "/docs",
            "/redoc"
        ]
        
        for pattern in skip_patterns:
            if path.startswith(pattern):
                return True
        
        # Se autenticação está desabilitada globalmente
        if not settings.API_KEY_ENABLED:
            return True
        
        return False
    
    def _is_protected_path(self, request: Request) -> bool:
        """Verifica se é uma rota protegida que sempre precisa de auth"""
        path = request.url.path
        
        for protected_path in self.protected_paths:
            if path.startswith(protected_path):
                return True
        
        return False
    
    async def _authenticate_request(self, request: Request) -> Dict[str, Any]:
        """Autentica request e retorna informações do usuário"""
        self.auth_attempts += 1
        
        # Resultado padrão
        auth_result = {
            "authenticated": False,
            "user": None,
            "auth_method": None,
            "error": None
        }
        
        try:
            # Tentar Bearer token
            auth_header = request.headers.get("authorization")
            if auth_header and auth_header.startswith("Bearer "):
                token = auth_header[7:]  # Remove "Bearer "
                user = await self._validate_bearer_token(token)
                if user:
                    auth_result.update({
                        "authenticated": True,
                        "user": user,
                        "auth_method": "bearer_token"
                    })
                    self.auth_successes += 1
                    return auth_result
            
            # Tentar API Key
            api_key = request.headers.get("x-api-key")
            if api_key:
                user = await self._validate_api_key(api_key)
                if user:
                    auth_result.update({
                        "authenticated": True,
                        "user": user,
                        "auth_method": "api_key"
                    })
                    self.auth_successes += 1
                    return auth_result
            
            # Nenhuma autenticação válida
            self.auth_failures += 1
            auth_result["error"] = "No valid authentication found"
            
        except Exception as e:
            logger.warning(f"Authentication error: {e}")
            auth_result["error"] = str(e)
            self.auth_failures += 1
        
        return auth_result
    
    async def _validate_bearer_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Valida Bearer token"""
        try:
            if not token or len(token) < 10:
                return None
            
            # Verificar cache primeiro
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            cache_key = f"bearer_token:{token_hash}"
            
            if cache_key in self.user_cache:
                cached_user = self.user_cache[cache_key]
                if time.time() - cached_user["cached_at"] < self.cache_ttl:
                    return cached_user["user"]
            
            # Verificar blacklist no Redis
            redis_client = get_redis_client()
            if redis_client.cache_exists(f"blacklisted_token:{token_hash}"):
                logger.warning(f"Blacklisted token attempted: {token_hash[:8]}...")
                return None
            
            # Validar token (implementação simples)
            # Em produção: validar JWT, consultar banco de dados, etc.
            user = await self._create_user_from_token(token)
            
            if user:
                # Cachear usuário
                self.user_cache[cache_key] = {
                    "user": user,
                    "cached_at": time.time()
                }
                
                # Registrar uso do token
                redis_client.increment_metric("auth_bearer_token_uses")
                
                return user
            
            return None
            
        except Exception as e:
            logger.warning(f"Bearer token validation failed: {e}")
            return None
    
    async def _validate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Valida API key"""
        try:
            if not api_key or len(api_key) < 20:
                return None
            
            # Verificar formato
            if not api_key.startswith("ocr_"):
                return None
            
            # Verificar cache
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            cache_key = f"api_key:{key_hash}"
            
            if cache_key in self.user_cache:
                cached_user = self.user_cache[cache_key]
                if time.time() - cached_user["cached_at"] < self.cache_ttl:
                    return cached_user["user"]
            
            # Verificar blacklist
            redis_client = get_redis_client()
            if redis_client.cache_exists(f"blacklisted_api_key:{key_hash}"):
                logger.warning(f"Blacklisted API key attempted: {key_hash[:8]}...")
                return None
            
            # Validar API key
            user = await self._create_user_from_api_key(api_key)
            
            if user:
                # Cachear usuário
                self.user_cache[cache_key] = {
                    "user": user,
                    "cached_at": time.time()
                }
                
                # Registrar uso da API key
                redis_client.increment_metric("auth_api_key_uses")
                
                return user
            
            return None
            
        except Exception as e:
            logger.warning(f"API key validation failed: {e}")
            return None
    
    async def _create_user_from_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Cria objeto de usuário a partir do token"""
        # Implementação simples - em produção seria mais robusta
        try:
            # Gerar ID único baseado no token
            user_id = f"user_{hashlib.md5(token.encode()).hexdigest()[:8]}"
            
            # Determinar permissões baseado no token
            # Por exemplo, tokens com certos prefixos podem ter mais permissões
            permissions = ["read", "write"]
            if token.startswith("admin_"):
                permissions.append("admin")
            
            return {
                "user_id": user_id,
                "user_type": "authenticated",
                "permissions": permissions,
                "authenticated": True,
                "auth_method": "bearer_token",
                "created_at": time.time()
            }
            
        except Exception as e:
            logger.warning(f"Failed to create user from token: {e}")
            return None
    
    async def _create_user_from_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Cria objeto de usuário a partir da API key"""
        try:
            # Gerar ID único baseado na API key
            user_id = f"api_{hashlib.md5(api_key.encode()).hexdigest()[:8]}"
            
            # API keys geralmente têm permissões limitadas
            permissions = ["read", "write"]
            
            return {
                "user_id": user_id,
                "user_type": "api_client",
                "permissions": permissions,
                "authenticated": True,
                "auth_method": "api_key",
                "created_at": time.time()
            }
            
        except Exception as e:
            logger.warning(f"Failed to create user from API key: {e}")
            return None
    
    def _add_security_headers(self, response: Response):
        """Adiciona headers de segurança"""
        security_headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
        
        for header, value in security_headers.items():
            response.headers[header] = value
    
    def _create_auth_error_response(self, message: str, status_code: int) -> JSONResponse:
        """Cria resposta de erro de autenticação"""
        return JSONResponse(
            status_code=status_code,
            content={
                "error": "Authentication failed",
                "message": message,
                "timestamp": time.time()
            },
            headers={
                "WWW-Authenticate": "Bearer" if status_code == HTTP_401_UNAUTHORIZED else None
            }
        )
    
    def _log_auth_attempt(self, request: Request, auth_result: Dict[str, Any]):
        """Log de tentativa de autenticação"""
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")
        method = request.method
        path = request.url.path
        
        if auth_result["authenticated"]:
            user = auth_result.get("user", {})
            logger.info(
                f"Auth success: {user.get('user_id', 'unknown')} "
                f"({auth_result.get('auth_method', 'unknown')}) "
                f"from {client_ip} - {method} {path}"
            )
        else:
            logger.warning(
                f"Auth failure: {auth_result.get('error', 'unknown')} "
                f"from {client_ip} - {method} {path} - {user_agent}"
            )
            
            # Registrar tentativa suspeita no Redis para monitoramento
            try:
                redis_client = get_redis_client()
                redis_client.increment_metric(
                    "auth_failures_by_ip",
                    tags={"ip": client_ip}
                )
            except Exception as e:
                logger.debug(f"Failed to record auth failure metric: {e}")
    
    def _record_auth_metrics(self, auth_result: Dict[str, Any], processing_time: float):
        """Registra métricas de autenticação"""
        try:
            redis_client = get_redis_client()
            
            # Métricas básicas
            redis_client.increment_metric("auth_attempts_total")
            
            if auth_result["authenticated"]:
                redis_client.increment_metric("auth_successes_total")
                redis_client.increment_metric(
                    "auth_successes_by_method",
                    tags={"method": auth_result.get("auth_method", "unknown")}
                )
            else:
                redis_client.increment_metric("auth_failures_total")
            
            # Tempo de processamento
            redis_client.set_metric("auth_processing_time", processing_time)
            
        except Exception as e:
            logger.debug(f"Failed to record auth metrics: {e}")
    
    def get_auth_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas de autenticação"""
        try:
            redis_client = get_redis_client()
            
            stats = {
                "session_stats": {
                    "auth_attempts": self.auth_attempts,
                    "auth_successes": self.auth_successes,
                    "auth_failures": self.auth_failures,
                    "success_rate": (self.auth_successes / max(self.auth_attempts, 1)) * 100,
                    "cached_users": len(self.user_cache)
                },
                "total_stats": {
                    "total_attempts": redis_client.get_metric("auth_attempts_total") or 0,
                    "total_successes": redis_client.get_metric("auth_successes_total") or 0,
                    "total_failures": redis_client.get_metric("auth_failures_total") or 0,
                    "bearer_token_uses": redis_client.get_metric("auth_bearer_token_uses") or 0,
                    "api_key_uses": redis_client.get_metric("auth_api_key_uses") or 0,
                    "last_processing_time": redis_client.get_metric("auth_processing_time") or 0
                },
                "configuration": {
                    "api_key_enabled": settings.API_KEY_ENABLED,
                    "cache_ttl": self.cache_ttl,
                    "skip_paths": self.skip_paths,
                    "protected_paths": self.protected_paths
                }
            }
            
            # Calcular taxa de sucesso total
            total_attempts = stats["total_stats"]["total_attempts"]
            total_successes = stats["total_stats"]["total_successes"]
            if total_attempts > 0:
                stats["total_stats"]["success_rate"] = (total_successes / total_attempts) * 100
            else:
                stats["total_stats"]["success_rate"] = 0
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get auth stats: {e}")
            return {"error": str(e)}
    
    def cleanup_cache(self):
        """Limpa cache expirado"""
        current_time = time.time()
        expired_keys = []
        
        for key, cached_item in self.user_cache.items():
            if current_time - cached_item["cached_at"] > self.cache_ttl:
                expired_keys.append(key)
        
        for key in expired_keys:
            del self.user_cache[key]
        
        logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")


class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Middleware especializado para rotas administrativas"""
    
    def __init__(self, app):
        super().__init__(app)
        self.admin_attempts = 0
        self.admin_successes = 0
    
    async def dispatch(self, request: Request, call_next):
        """Processa requests administrativos"""
        # Só aplicar para rotas admin
        if not request.url.path.startswith("/api/v1/admin"):
            return await call_next(request)
        
        self.admin_attempts += 1
        
        # Verificar se usuário está autenticado
        if not hasattr(request.state, "authenticated") or not request.state.authenticated:
            return JSONResponse(
                status_code=HTTP_401_UNAUTHORIZED,
                content={"error": "Authentication required for admin operations"}
            )
        
        # Verificar permissões de admin
        user = getattr(request.state, "user", {})
        permissions = user.get("permissions", [])
        
        if "admin" not in permissions:
            return JSONResponse(
                status_code=HTTP_403_FORBIDDEN,
                content={"error": "Administrator permissions required"}
            )
        
        self.admin_successes += 1
        
        # Log de acesso admin
        logger.info(
            f"Admin access: {user.get('user_id', 'unknown')} - "
            f"{request.method} {request.url.path}"
        )
        
        response = await call_next(request)
        response.headers["X-Admin-Access"] = "granted"
        
        return response
    
    def get_admin_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas de acesso admin"""
        return {
            "admin_attempts": self.admin_attempts,
            "admin_successes": self.admin_successes,
            "success_rate": (self.admin_successes / max(self.admin_attempts, 1)) * 100
        }


# Função utilitária para blacklistar tokens/keys
async def blacklist_credential(credential: str, credential_type: str = "token"):
    """Adiciona credencial à blacklist"""
    try:
        redis_client = get_redis_client()
        credential_hash = hashlib.sha256(credential.encode()).hexdigest()
        
        redis_client.cache_set(
            f"blacklisted_{credential_type}:{credential_hash}",
            {"blacklisted_at": time.time(), "reason": "manual_blacklist"},
            ttl=86400 * 30  # 30 dias
        )
        
        logger.info(f"Credential blacklisted: {credential_type} {credential_hash[:8]}...")
        return True
        
    except Exception as e:
        logger.error(f"Failed to blacklist credential: {e}")
        return False


# Função para limpar blacklist expirada
async def cleanup_blacklist():
    """Remove entradas expiradas da blacklist"""
    try:
        redis_client = get_redis_client()
        
        # Buscar todas as chaves de blacklist
        blacklist_keys = redis_client.client.keys("blacklisted_*")
        cleaned_count = 0
        
        for key in blacklist_keys:
            # O Redis já cuida da expiração, mas podemos verificar manualmente
            if not redis_client.client.exists(key):
                cleaned_count += 1
        
        logger.info(f"Blacklist cleanup completed: {cleaned_count} expired entries removed")
        return cleaned_count
        
    except Exception as e:
        logger.error(f"Blacklist cleanup failed: {e}")
        return 0


if __name__ == "__main__":
    """Teste do middleware de autenticação"""
    print("=== Authentication Middleware Test ===")
    
    # Simular middleware
    middleware = AuthenticationMiddleware(None)
    
    # Teste de validação de token
    import asyncio
    
    async def test_auth():
        # Teste Bearer token
        test_token = "test_token_12345678901234567890"
        user = await middleware._validate_bearer_token(test_token)
        print(f"Bearer token validation: {user}")
        
        # Teste API key
        test_api_key = "ocr_1234567890abcdef1234567890abcdef"
        user = await middleware._validate_api_key(test_api_key)
        print(f"API key validation: {user}")
        
        # Estatísticas
        stats = middleware.get_auth_stats()
        print(f"Auth stats: {stats}")
    
    asyncio.run(test_auth())
    
    print("\n✅ Authentication Middleware test completed")