#!/usr/bin/env python3
"""
Inicialização dos Middlewares
=============================

Módulo de middlewares da OCR Platform que fornece:
- Middleware de logging de requests
- Middleware de rate limiting
- Middleware de autenticação
- Middleware de métricas
- Middleware de tratamento de erros
"""

import logging
import time
from typing import Dict, Any, Callable, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from fastapi import HTTPException
import json

from app.core.config import settings
from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Versão dos middlewares
__version__ = "2.0.0"

# Exportar middlewares
__all__ = [
    'LoggingMiddleware',
    'RateLimitMiddleware', 
    'AuthMiddleware',
    'MetricsMiddleware',
    'ErrorHandlingMiddleware',
    'setup_middlewares'
]


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware para logging de requests"""
    
    def __init__(self, app, logger_name: str = "api.requests"):
        super().__init__(app)
        self.logger = logging.getLogger(logger_name)
        self.exclude_paths = {"/health", "/ping", "/favicon.ico"}
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Processa request com logging"""
        start_time = time.time()
        
        # Informações do request
        method = request.method
        url = str(request.url)
        path = request.url.path
        client_ip = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent", "")
        
        # Skip logging para paths excluídos
        should_log = path not in self.exclude_paths
        
        if should_log:
            self.logger.info(f"REQUEST: {method} {path} from {client_ip}")
        
        try:
            # Processar request
            response = await call_next(request)
            
            # Calcular tempo de processamento
            process_time = time.time() - start_time
            
            if should_log:
                self.logger.info(
                    f"RESPONSE: {method} {path} -> {response.status_code} "
                    f"({process_time:.3f}s) [{client_ip}]"
                )
            
            # Adicionar headers de timing
            response.headers["X-Process-Time"] = f"{process_time:.3f}"
            
            return response
            
        except Exception as e:
            process_time = time.time() - start_time
            
            if should_log:
                self.logger.error(
                    f"ERROR: {method} {path} -> {type(e).__name__}: {str(e)} "
                    f"({process_time:.3f}s) [{client_ip}]"
                )
            
            raise
    
    def _get_client_ip(self, request: Request) -> str:
        """Obtém IP do cliente considerando proxies"""
        # Verificar headers de proxy
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # Fallback para IP direto
        return getattr(request.client, "host", "unknown")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware para rate limiting"""
    
    def __init__(self, app, 
                 calls_per_hour: int = None,
                 burst_limit: int = None,
                 identifier_func: Callable = None):
        super().__init__(app)
        self.calls_per_hour = calls_per_hour or settings.RATE_LIMIT_CALLS
        self.period = settings.RATE_LIMIT_PERIOD  # Em segundos
        self.burst_limit = burst_limit or (self.calls_per_hour // 10)  # 10% para burst
        self.redis_client = get_redis_client()
        self.identifier_func = identifier_func or self._default_identifier
        
        # Paths excluídos do rate limiting
        self.exclude_paths = {"/health", "/ping", "/favicon.ico", "/docs", "/redoc"}
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Aplica rate limiting"""
        path = request.url.path
        
        # Skip rate limiting para paths excluídos
        if path in self.exclude_paths:
            return await call_next(request)
        
        # Identificar cliente
        client_id = self.identifier_func(request)
        
        # Verificar rate limit
        if not self._check_rate_limit(client_id):
            # Rate limit exceeded
            retry_after = self._get_retry_after(client_id)
            
            logger.warning(f"Rate limit exceeded for {client_id} on {path}")
            
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(retry_after)}
            )
        
        # Incrementar contador
        self._increment_counter(client_id)
        
        return await call_next(request)
    
    def _default_identifier(self, request: Request) -> str:
        """Identificador padrão baseado no IP"""
        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.headers.get("x-real-ip", "")
        if not client_ip:
            client_ip = getattr(request.client, "host", "unknown")
        
        return f"ip:{client_ip}"
    
    def _check_rate_limit(self, client_id: str) -> bool:
        """Verifica se cliente está dentro do rate limit"""
        try:
            return self.redis_client.check_rate_limit(
                client_id, 
                self.calls_per_hour, 
                self.period
            )
        except Exception as e:
            logger.warning(f"Rate limit check failed: {e}")
            return True  # Permitir em caso de erro
    
    def _increment_counter(self, client_id: str):
        """Incrementa contador do cliente"""
        try:
            # Implementação básica - em produção seria mais sofisticada
            self.redis_client.increment_metric("rate_limit_requests", tags={"client": client_id})
        except Exception as e:
            logger.warning(f"Counter increment failed: {e}")
    
    def _get_retry_after(self, client_id: str) -> int:
        """Calcula tempo de retry"""
        # Implementação simples - retornar 60 segundos
        return 60


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware para autenticação (opcional)"""
    
    def __init__(self, app, require_auth: bool = None):
        super().__init__(app)
        self.require_auth = require_auth if require_auth is not None else settings.API_KEY_ENABLED
        self.protected_paths = {"/admin", "/api/v1/admin"}
        self.exclude_paths = {"/health", "/ping", "/docs", "/redoc", "/openapi.json"}
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Verifica autenticação se necessária"""
        path = request.url.path
        
        # Skip autenticação para paths excluídos
        if path in self.exclude_paths or not self.require_auth:
            return await call_next(request)
        
        # Verificar se path requer autenticação
        needs_auth = any(path.startswith(protected) for protected in self.protected_paths)
        
        if needs_auth:
            api_key = request.headers.get("X-API-Key") or request.headers.get("Authorization")
            
            if not api_key:
                raise HTTPException(
                    status_code=401,
                    detail="API key required",
                    headers={"WWW-Authenticate": "ApiKey"}
                )
            
            # Validar API key (implementação básica)
            if not self._validate_api_key(api_key):
                raise HTTPException(
                    status_code=403,
                    detail="Invalid API key"
                )
        
        return await call_next(request)
    
    def _validate_api_key(self, api_key: str) -> bool:
        """Valida API key"""
        # Implementação básica - em produção seria mais robusta
        valid_keys = {
            settings.SECRET_KEY,
            "dev-api-key-123",  # Para desenvolvimento
        }
        
        # Remover prefixo Bearer se presente
        if api_key.startswith("Bearer "):
            api_key = api_key[7:]
        
        return api_key in valid_keys


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware para coleta de métricas"""
    
    def __init__(self, app):
        super().__init__(app)
        self.redis_client = get_redis_client()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Coleta métricas do request"""
        start_time = time.time()
        
        method = request.method
        path = request.url.path
        
        try:
            response = await call_next(request)
            
            # Métricas de sucesso
            duration = time.time() - start_time
            status_code = response.status_code
            
            self._record_metrics(method, path, status_code, duration, None)
            
            return response
            
        except Exception as e:
            # Métricas de erro
            duration = time.time() - start_time
            self._record_metrics(method, path, 500, duration, type(e).__name__)
            raise
    
    def _record_metrics(self, method: str, path: str, status_code: int, 
                       duration: float, error_type: Optional[str]):
        """Registra métricas no Redis"""
        try:
            # Métricas básicas
            self.redis_client.increment_metric("http_requests_total", 
                                             tags={"method": method, "status": str(status_code)})
            
            self.redis_client.set_metric("http_request_duration_seconds", duration)
            
            # Métricas por endpoint
            endpoint = self._normalize_path(path)
            self.redis_client.increment_metric("http_requests_by_endpoint",
                                             tags={"endpoint": endpoint, "method": method})
            
            # Métricas de erro
            if error_type:
                self.redis_client.increment_metric("http_errors_total",
                                                 tags={"error_type": error_type})
            
        except Exception as e:
            logger.warning(f"Metrics recording failed: {e}")
    
    def _normalize_path(self, path: str) -> str:
        """Normaliza path para métricas (remove IDs específicos)"""
        import re
        
        # Substituir UUIDs
        path = re.sub(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', 
                     '/{uuid}', path, flags=re.IGNORECASE)
        
        # Substituir IDs numéricos
        path = re.sub(r'/\d+', '/{id}', path)
        
        # Substituir task IDs
        path = re.sub(r'/task_[a-zA-Z0-9]+', '/task_{id}', path)
        
        return path


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Middleware para tratamento centralizado de erros"""
    
    def __init__(self, app):
        super().__init__(app)
        self.redis_client = get_redis_client()
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Trata erros de forma centralizada"""
        try:
            return await call_next(request)
            
        except HTTPException:
            # HTTPException já é tratada pelo FastAPI
            raise
            
        except Exception as e:
            # Log do erro
            logger.error(f"Unhandled error in {request.method} {request.url.path}: {e}", 
                        exc_info=True)
            
            # Registrar métricas de erro
            try:
                self.redis_client.increment_metric("unhandled_errors_total",
                                                 tags={"error_type": type(e).__name__})
            except Exception:
                pass
            
            # Retornar erro padronizado
            from app.models.schemas import ErrorResponse
            from fastapi.responses import JSONResponse
            
            error_response = ErrorResponse(
                message="Internal server error",
                error_code="INTERNAL_ERROR",
                details={"type": type(e).__name__} if settings.DEBUG else None
            )
            
            return JSONResponse(
                status_code=500,
                content=error_response.dict()
            )


def setup_middlewares(app, config: Dict[str, Any] = None) -> None:
    """
    Configura middlewares na aplicação FastAPI
    
    Args:
        app: Instância do FastAPI
        config: Configurações customizadas
    """
    config = config or {}
    
    # Middleware de tratamento de erros (primeiro - outer layer)
    if config.get("enable_error_handling", True):
        app.add_middleware(ErrorHandlingMiddleware)
        logger.info("✅ Error handling middleware enabled")
    
    # Middleware de métricas
    if config.get("enable_metrics", True):
        app.add_middleware(MetricsMiddleware)
        logger.info("✅ Metrics middleware enabled")
    
    # Middleware de autenticação
    if config.get("enable_auth", settings.API_KEY_ENABLED):
        app.add_middleware(AuthMiddleware, require_auth=True)
        logger.info("✅ Auth middleware enabled")
    
    # Middleware de rate limiting
    if config.get("enable_rate_limit", settings.RATE_LIMIT_ENABLED):
        app.add_middleware(
            RateLimitMiddleware,
            calls_per_hour=config.get("rate_limit_calls", settings.RATE_LIMIT_CALLS)
        )
        logger.info("✅ Rate limiting middleware enabled")
    
    # Middleware de logging (último - inner layer)
    if config.get("enable_logging", True):
        app.add_middleware(LoggingMiddleware)
        logger.info("✅ Logging middleware enabled")


def get_middleware_stats() -> Dict[str, Any]:
    """Retorna estatísticas dos middlewares"""
    try:
        redis_client = get_redis_client()
        
        stats = {
            "version": __version__,
            "http_requests": {
                "total": redis_client.get_metric("http_requests_total") or 0,
                "errors": redis_client.get_metric("http_errors_total") or 0,
                "unhandled_errors": redis_client.get_metric("unhandled_errors_total") or 0
            },
            "rate_limiting": {
                "requests_checked": redis_client.get_metric("rate_limit_requests") or 0
            },
            "last_request_duration": redis_client.get_metric("http_request_duration_seconds") or 0
        }
        
        return stats
        
    except Exception as e:
        logger.warning(f"Failed to get middleware stats: {e}")
        return {"error": str(e)}


# Utilitários para configuração
def create_custom_rate_limiter(calls_per_minute: int = 60, 
                              burst_multiplier: float = 2.0) -> RateLimitMiddleware:
    """Cria rate limiter customizado"""
    def custom_app_wrapper(app):
        return RateLimitMiddleware(
            app,
            calls_per_hour=calls_per_minute * 60,
            burst_limit=int(calls_per_minute * burst_multiplier)
        )
    return custom_app_wrapper


def create_api_key_auth(valid_keys: list) -> AuthMiddleware:
    """Cria middleware de autenticação customizado"""
    def custom_app_wrapper(app):
        middleware = AuthMiddleware(app, require_auth=True)
        # Override do método de validação
        def custom_validate(api_key: str) -> bool:
            if api_key.startswith("Bearer "):
                api_key = api_key[7:]
            return api_key in valid_keys
        
        middleware._validate_api_key = custom_validate
        return middleware
    
    return custom_app_wrapper


if __name__ == "__main__":
    """Teste dos middlewares"""
    print("=== Middleware Module Test ===")
    
    # Teste de configuração
    from fastapi import FastAPI
    
    app = FastAPI()
    
    # Setup dos middlewares
    setup_middlewares(app, {
        "enable_error_handling": True,
        "enable_metrics": True,
        "enable_auth": False,
        "enable_rate_limit": False,
        "enable_logging": True
    })
    
    print(f"Middlewares version: {__version__}")
    print("Middlewares configured successfully")
    
    # Estatísticas
    stats = get_middleware_stats()
    print(f"Middleware stats: {stats}")
    
    print("\n✅ Middleware module test completed")