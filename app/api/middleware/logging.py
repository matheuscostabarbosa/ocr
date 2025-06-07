#!/usr/bin/env python3
"""
Middleware de Logging
====================

Middleware customizado para logging detalhado de requests:
- Logging estruturado de requests e responses
- Métricas de performance
- Tracking de usuários e sessões
- Logging de erros e exceções
- Correlação de logs com request IDs
- Sanitização de dados sensíveis
"""

import time
import json
import uuid
import logging
import traceback
from typing import Dict, Any, Optional, List
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from app.core.config import settings
from app.core.redis_client import get_redis_client

# Configurar logger específico para requests
request_logger = logging.getLogger("api.requests")
error_logger = logging.getLogger("api.errors")
performance_logger = logging.getLogger("api.performance")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware de logging customizado"""
    
    def __init__(self, app, log_level: str = "INFO"):
        super().__init__(app)
        
        # Configurações
        self.log_level = getattr(logging, log_level.upper(), logging.INFO)
        self.log_request_body = settings.DEBUG  # Só logar body em debug
        self.log_response_body = False  # Geralmente não logamos response body
        self.max_body_size = 1024 * 10  # 10KB máximo para log
        
        # Campos sensíveis para sanitizar
        self.sensitive_fields = {
            "password", "passwd", "secret", "token", "key", "auth",
            "authorization", "x-api-key", "cookie", "session"
        }
        
        # Paths a ignorar no logging detalhado
        self.skip_detailed_logging = {
            "/health", "/ping", "/favicon.ico", "/docs", "/redoc", "/openapi.json"
        }
        
        # Contadores
        self.requests_logged = 0
        self.errors_logged = 0
        self.slow_requests = 0
        
        # Threshold para requests lentos
        self.slow_request_threshold = 5.0  # 5 segundos
        
        # Buffer para logs em lote (opcional)
        self.log_buffer = []
        self.buffer_size = 100
        self.last_flush = time.time()
        self.flush_interval = 60  # 1 minuto
    
    async def dispatch(self, request: Request, call_next):
        """Processa request com logging completo"""
        # Gerar ID único para correlação
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        # Timestamp de início
        start_time = time.time()
        
        # Log de início do request
        await self._log_request_start(request, request_id, start_time)
        
        response = None
        error = None
        
        try:
            # Processar request
            response = await call_next(request)
            
        except Exception as e:
            # Capturar e logar erro
            error = e
            error_logger.error(
                f"Request {request_id} failed with exception: {str(e)}",
                extra={
                    "request_id": request_id,
                    "exception_type": type(e).__name__,
                    "traceback": traceback.format_exc(),
                    "request_method": request.method,
                    "request_path": request.url.path
                }
            )
            self.errors_logged += 1
            
            # Criar response de erro
            response = Response(
                content=json.dumps({
                    "error": "Internal server error",
                    "request_id": request_id,
                    "timestamp": time.time()
                }),
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                media_type="application/json"
            )
        
        finally:
            # Calcular tempo de processamento
            processing_time = time.time() - start_time
            
            # Log de fim do request
            await self._log_request_end(
                request, response, request_id, start_time, processing_time, error
            )
            
            # Adicionar headers de logging
            if response:
                response.headers["X-Request-ID"] = request_id
                response.headers["X-Processing-Time"] = f"{processing_time:.4f}"
        
        return response
    
    async def _log_request_start(self, request: Request, request_id: str, start_time: float):
        """Log do início do request"""
        try:
            # Extrair informações básicas
            client_info = self._extract_client_info(request)
            
            # Verificar se deve fazer logging detalhado
            detailed_logging = request.url.path not in self.skip_detailed_logging
            
            # Log básico sempre
            request_logger.info(
                f"Request started: {request.method} {request.url.path}",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "query_params": dict(request.query_params),
                    "client_ip": client_info["ip"],
                    "user_agent": client_info["user_agent"],
                    "timestamp": start_time,
                    "detailed": detailed_logging
                }
            )
            
            # Log detalhado se necessário
            if detailed_logging and self.log_level <= logging.DEBUG:
                await self._log_detailed_request(request, request_id)
            
            # Salvar contexto no Redis para correlação
            await self._save_request_context(request, request_id, start_time)
            
            self.requests_logged += 1
            
        except Exception as e:
            error_logger.warning(f"Failed to log request start: {e}")
    
    async def _log_request_end(self, request: Request, response: Response, 
                             request_id: str, start_time: float, 
                             processing_time: float, error: Optional[Exception]):
        """Log do fim do request"""
        try:
            # Status do response
            status_code = response.status_code if response else 500
            status_category = self._get_status_category(status_code)
            
            # Informações do usuário se disponível
            user_info = self._extract_user_info(request)
            
            # Log básico
            request_logger.info(
                f"Request completed: {request.method} {request.url.path} - "
                f"{status_code} ({processing_time:.4f}s)",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "status_category": status_category,
                    "processing_time": processing_time,
                    "user_id": user_info.get("user_id"),
                    "user_type": user_info.get("user_type"),
                    "timestamp": time.time(),
                    "error": str(error) if error else None
                }
            )
            
            # Log de performance para requests lentos
            if processing_time > self.slow_request_threshold:
                self.slow_requests += 1
                performance_logger.warning(
                    f"Slow request detected: {request.method} {request.url.path} "
                    f"took {processing_time:.4f}s",
                    extra={
                        "request_id": request_id,
                        "processing_time": processing_time,
                        "threshold": self.slow_request_threshold,
                        "slow_request": True
                    }
                )
            
            # Log detalhado para erros
            if error or (response and status_code >= 400):
                await self._log_error_details(request, response, request_id, error)
            
            # Registrar métricas
            await self._record_request_metrics(
                request, response, processing_time, status_category, user_info
            )
            
            # Atualizar contexto no Redis
            await self._update_request_context(request_id, {
                "status_code": status_code,
                "processing_time": processing_time,
                "completed_at": time.time(),
                "error": str(error) if error else None
            })
            
        except Exception as e:
            error_logger.warning(f"Failed to log request end: {e}")
    
    async def _log_detailed_request(self, request: Request, request_id: str):
        """Log detalhado do request"""
        try:
            details = {
                "request_id": request_id,
                "url": str(request.url),
                "headers": self._sanitize_headers(dict(request.headers)),
                "cookies": self._sanitize_data(dict(request.cookies)),
                "content_type": request.headers.get("content-type"),
                "content_length": request.headers.get("content-length")
            }
            
            # Log do body se habilitado e não muito grande
            if self.log_request_body:
                body = await self._get_request_body(request)
                if body and len(body) < self.max_body_size:
                    try:
                        # Tentar parsear como JSON
                        if request.headers.get("content-type", "").startswith("application/json"):
                            body_data = json.loads(body)
                            details["body"] = self._sanitize_data(body_data)
                        else:
                            details["body"] = body[:self.max_body_size]
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        details["body"] = "<binary or invalid data>"
            
            request_logger.debug(
                f"Detailed request info for {request_id}",
                extra=details
            )
            
        except Exception as e:
            error_logger.debug(f"Failed to log detailed request: {e}")
    
    async def _log_error_details(self, request: Request, response: Optional[Response], 
                                request_id: str, error: Optional[Exception]):
        """Log detalhado de erros"""
        try:
            error_details = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query_params": dict(request.query_params),
                "status_code": response.status_code if response else 500,
                "error_type": type(error).__name__ if error else "HTTP_ERROR",
                "error_message": str(error) if error else "HTTP error response"
            }
            
            # Adicionar informações do usuário
            user_info = self._extract_user_info(request)
            if user_info:
                error_details["user_id"] = user_info.get("user_id")
                error_details["user_type"] = user_info.get("user_type")
            
            # Adicionar stacktrace se for exceção
            if error:
                error_details["traceback"] = traceback.format_exc()
            
            # Adicionar headers importantes (sanitizados)
            important_headers = ["user-agent", "referer", "x-forwarded-for"]
            error_details["headers"] = {
                key: request.headers.get(key)
                for key in important_headers
                if request.headers.get(key)
            }
            
            error_logger.error(
                f"Request error: {error_details['error_type']} in {request.method} {request.url.path}",
                extra=error_details
            )
            
        except Exception as e:
            error_logger.warning(f"Failed to log error details: {e}")
    
    def _extract_client_info(self, request: Request) -> Dict[str, Any]:
        """Extrai informações do cliente"""
        return {
            "ip": request.client.host if request.client else "unknown",
            "user_agent": request.headers.get("user-agent", "unknown"),
            "referer": request.headers.get("referer"),
            "x_forwarded_for": request.headers.get("x-forwarded-for"),
            "x_real_ip": request.headers.get("x-real-ip")
        }
    
    def _extract_user_info(self, request: Request) -> Dict[str, Any]:
        """Extrai informações do usuário autenticado"""
        user_info = {}
        
        if hasattr(request.state, "user") and request.state.user:
            user = request.state.user
            user_info.update({
                "user_id": user.get("user_id"),
                "user_type": user.get("user_type"),
                "authenticated": getattr(request.state, "authenticated", False),
                "auth_method": getattr(request.state, "auth_method")
            })
        
        return user_info
    
    def _sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Sanitiza headers removendo informações sensíveis"""
        sanitized = {}
        
        for key, value in headers.items():
            key_lower = key.lower()
            
            if any(sensitive in key_lower for sensitive in self.sensitive_fields):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = value
        
        return sanitized
    
    def _sanitize_data(self, data: Any) -> Any:
        """Sanitiza dados recursivamente"""
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                key_lower = str(key).lower()
                
                if any(sensitive in key_lower for sensitive in self.sensitive_fields):
                    sanitized[key] = "[REDACTED]"
                else:
                    sanitized[key] = self._sanitize_data(value)
            
            return sanitized
        
        elif isinstance(data, list):
            return [self._sanitize_data(item) for item in data]
        
        else:
            return data
    
    async def _get_request_body(self, request: Request) -> Optional[bytes]:
        """Obtém body do request de forma segura"""
        try:
            # Verificar se body já foi lido
            if hasattr(request.state, "_body"):
                return request.state._body
            
            # Ler body
            body = await request.body()
            request.state._body = body
            
            return body
            
        except Exception as e:
            error_logger.debug(f"Failed to read request body: {e}")
            return None
    
    def _get_status_category(self, status_code: int) -> str:
        """Categoriza status code"""
        if 200 <= status_code < 300:
            return "success"
        elif 300 <= status_code < 400:
            return "redirect"
        elif 400 <= status_code < 500:
            return "client_error"
        elif 500 <= status_code < 600:
            return "server_error"
        else:
            return "unknown"
    
    async def _save_request_context(self, request: Request, request_id: str, start_time: float):
        """Salva contexto do request no Redis"""
        try:
            redis_client = get_redis_client()
            
            context = {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query_params": dict(request.query_params),
                "client_ip": request.client.host if request.client else "unknown",
                "user_agent": request.headers.get("user-agent"),
                "start_time": start_time,
                "status": "in_progress"
            }
            
            # Adicionar info do usuário se disponível
            user_info = self._extract_user_info(request)
            if user_info:
                context["user"] = user_info
            
            redis_client.cache_set(
                f"request_context:{request_id}",
                context,
                ttl=3600  # 1 hora
            )
            
        except Exception as e:
            error_logger.debug(f"Failed to save request context: {e}")
    
    async def _update_request_context(self, request_id: str, updates: Dict[str, Any]):
        """Atualiza contexto do request no Redis"""
        try:
            redis_client = get_redis_client()
            
            context = redis_client.cache_get(f"request_context:{request_id}")
            if context:
                context.update(updates)
                context["status"] = "completed"
                
                redis_client.cache_set(
                    f"request_context:{request_id}",
                    context,
                    ttl=3600  # 1 hora
                )
            
        except Exception as e:
            error_logger.debug(f"Failed to update request context: {e}")
    
    async def _record_request_metrics(self, request: Request, response: Optional[Response],
                                    processing_time: float, status_category: str,
                                    user_info: Dict[str, Any]):
        """Registra métricas do request"""
        try:
            redis_client = get_redis_client()
            
            # Métricas básicas
            redis_client.increment_metric("api_requests_total")
            redis_client.increment_metric(
                "api_requests_by_method",
                tags={"method": request.method}
            )
            redis_client.increment_metric(
                "api_requests_by_status",
                tags={"status": status_category}
            )
            
            # Métricas por endpoint
            endpoint = self._normalize_endpoint(request.url.path)
            redis_client.increment_metric(
                "api_requests_by_endpoint",
                tags={"endpoint": endpoint}
            )
            
            # Métricas de performance
            redis_client.set_metric("api_request_duration", processing_time)
            
            if processing_time > self.slow_request_threshold:
                redis_client.increment_metric("api_slow_requests")
            
            # Métricas por usuário se disponível
            if user_info.get("user_type"):
                redis_client.increment_metric(
                    "api_requests_by_user_type",
                    tags={"user_type": user_info["user_type"]}
                )
            
            # Status code específico
            if response:
                redis_client.increment_metric(
                    "api_responses_by_code",
                    tags={"code": str(response.status_code)}
                )
            
        except Exception as e:
            error_logger.debug(f"Failed to record request metrics: {e}")
    
    def _normalize_endpoint(self, path: str) -> str:
        """Normaliza endpoint para métricas (remove IDs dinâmicos)"""
        import re
        
        # Substituir UUIDs e IDs numéricos por placeholders
        path = re.sub(
            r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            '/{uuid}',
            path
        )
        path = re.sub(r'/\d+', '/{id}', path)
        
        return path
    
    def get_logging_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas de logging"""
        try:
            redis_client = get_redis_client()
            
            stats = {
                "session_stats": {
                    "requests_logged": self.requests_logged,
                    "errors_logged": self.errors_logged,
                    "slow_requests": self.slow_requests,
                    "log_buffer_size": len(self.log_buffer),
                    "last_flush": self.last_flush
                },
                "configuration": {
                    "log_level": logging.getLevelName(self.log_level),
                    "log_request_body": self.log_request_body,
                    "log_response_body": self.log_response_body,
                    "max_body_size": self.max_body_size,
                    "slow_request_threshold": self.slow_request_threshold
                },
                "total_metrics": {
                    "total_requests": redis_client.get_metric("api_requests_total") or 0,
                    "total_slow_requests": redis_client.get_metric("api_slow_requests") or 0,
                    "last_request_duration": redis_client.get_metric("api_request_duration") or 0
                }
            }
            
            # Calcular taxa de requests lentos
            total_requests = stats["total_metrics"]["total_requests"]
            slow_requests = stats["total_metrics"]["total_slow_requests"]
            if total_requests > 0:
                stats["total_metrics"]["slow_request_rate"] = (slow_requests / total_requests) * 100
            else:
                stats["total_metrics"]["slow_request_rate"] = 0
            
            return stats
            
        except Exception as e:
            error_logger.warning(f"Failed to get logging stats: {e}")
            return {"error": str(e)}
    
    async def flush_log_buffer(self):
        """Força flush do buffer de logs"""
        if self.log_buffer:
            # Implementar flush em lote se necessário
            self.log_buffer.clear()
            self.last_flush = time.time()


class PerformanceLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware especializado para logging de performance"""
    
    def __init__(self, app, slow_threshold: float = 1.0):
        super().__init__(app)
        self.slow_threshold = slow_threshold
        self.performance_data = []
        self.max_samples = 1000  # Manter últimas 1000 amostras
    
    async def dispatch(self, request: Request, call_next):
        """Monitora performance detalhada"""
        start_time = time.time()
        start_cpu = time.process_time()
        
        response = await call_next(request)
        
        end_time = time.time()
        end_cpu = time.process_time()
        
        # Calcular métricas
        wall_time = end_time - start_time
        cpu_time = end_cpu - start_cpu
        
        # Armazenar dados de performance
        perf_data = {
            "timestamp": start_time,
            "method": request.method,
            "path": request.url.path,
            "wall_time": wall_time,
            "cpu_time": cpu_time,
            "status_code": response.status_code
        }
        
        self.performance_data.append(perf_data)
        
        # Manter só as últimas amostras
        if len(self.performance_data) > self.max_samples:
            self.performance_data = self.performance_data[-self.max_samples:]
        
        # Log de performance para requests lentos
        if wall_time > self.slow_threshold:
            performance_logger.warning(
                f"Slow performance: {request.method} {request.url.path} - "
                f"Wall: {wall_time:.4f}s, CPU: {cpu_time:.4f}s",
                extra={
                    "wall_time": wall_time,
                    "cpu_time": cpu_time,
                    "efficiency": cpu_time / wall_time if wall_time > 0 else 0
                }
            )
        
        # Adicionar headers de performance
        response.headers["X-Wall-Time"] = f"{wall_time:.4f}"
        response.headers["X-CPU-Time"] = f"{cpu_time:.4f}"
        
        return response
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Retorna resumo de performance"""
        if not self.performance_data:
            return {"error": "No performance data available"}
        
        wall_times = [d["wall_time"] for d in self.performance_data]
        cpu_times = [d["cpu_time"] for d in self.performance_data]
        
        return {
            "samples": len(self.performance_data),
            "wall_time": {
                "avg": sum(wall_times) / len(wall_times),
                "min": min(wall_times),
                "max": max(wall_times),
                "p95": sorted(wall_times)[int(len(wall_times) * 0.95)]
            },
            "cpu_time": {
                "avg": sum(cpu_times) / len(cpu_times),
                "min": min(cpu_times),
                "max": max(cpu_times),
                "p95": sorted(cpu_times)[int(len(cpu_times) * 0.95)]
            },
            "slow_requests": len([d for d in self.performance_data if d["wall_time"] > self.slow_threshold])
        }


if __name__ == "__main__":
    """Teste do middleware de logging"""
    print("=== Logging Middleware Test ===")
    
    # Teste de sanitização
    middleware = LoggingMiddleware(None)
    
    # Teste de sanitização de headers
    test_headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer secret_token",
        "X-API-Key": "api_key_secret",
        "User-Agent": "Test Agent"
    }
    
    sanitized = middleware._sanitize_headers(test_headers)
    print(f"Header sanitization:")
    for key, value in sanitized.items():
        print(f"  {key}: {value}")
    
    # Teste de sanitização de dados
    test_data = {
        "username": "testuser",
        "password": "secret123",
        "email": "test@example.com",
        "token": "abc123",
        "data": {
            "value": 42,
            "secret": "hidden"
        }
    }
    
    sanitized_data = middleware._sanitize_data(test_data)
    print(f"\nData sanitization:")
    print(json.dumps(sanitized_data, indent=2))
    
    # Teste de normalização de endpoint
    test_paths = [
        "/api/v1/users/123",
        "/api/v1/documents/uuid-1234-5678",
        "/api/v1/status/abc-def-ghi-jkl-mno",
        "/api/v1/health"
    ]
    
    print(f"\nEndpoint normalization:")
    for path in test_paths:
        normalized = middleware._normalize_endpoint(path)
        print(f"  {path} -> {normalized}")
    
    print("\n✅ Logging Middleware test completed")