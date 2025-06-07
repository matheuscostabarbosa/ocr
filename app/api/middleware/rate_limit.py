#!/usr/bin/env python3
"""
Rate Limiting Middleware
========================

Middleware para rate limiting da API:
- Limitação por IP
- Limitação por API key
- Diferentes limites por endpoint
- Whitelist de IPs
- Headers informativos
- Integração com Redis
"""

import time
import logging
from typing import Dict, Any, Optional, List
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import hashlib

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.models.schemas import ErrorResponse

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware de rate limiting"""
    
    def __init__(self, app):
        super().__init__(app)
        self.redis_client = get_redis_client()
        
        # Configurações padrão
        self.default_calls = settings.RATE_LIMIT_CALLS
        self.default_period = settings.RATE_LIMIT_PERIOD
        
        # Configurações específicas por endpoint
        self.endpoint_limits = {
            "/api/v1/ocr": {"calls": 50, "period": 3600},  # 50/hora para OCR
            "/api/v1/batch": {"calls": 10, "period": 3600},  # 10/hora para batch
            "/api/v1/health": {"calls": 1000, "period": 3600},  # 1000/hora para health
        }
        
        # IPs em whitelist (sem limitação)
        self.whitelist_ips = {
            "127.0.0.1",
            "::1",
            "localhost"
        }
        
        # Endpoints excluídos do rate limiting
        self.excluded_paths = {
            "/docs",
            "/redoc", 
            "/openapi.json",
            "/favicon.ico",
            "/"
        }
        
        # Métricas
        self.requests_limited = 0
        self.requests_processed = 0
    
    async def dispatch(self, request: Request, call_next):
        """Processa request com rate limiting"""
        try:
            self.requests_processed += 1
            
            # Verificar se path deve ser limitado
            if not self._should_apply_rate_limit(request):
                return await call_next(request)
            
            # Obter identificador do cliente
            client_id = self._get_client_identifier(request)
            
            # Verificar whitelist
            if self._is_whitelisted(request, client_id):
                return await call_next(request)
            
            # Obter limites para este endpoint
            limits = self._get_endpoint_limits(request.url.path)
            
            # Verificar rate limit
            allowed, remaining, reset_time = await self._check_rate_limit(
                client_id, 
                request.url.path,
                limits["calls"],
                limits["period"]
            )
            
            if not allowed:
                self.requests_limited += 1
                return await self._create_rate_limit_response(remaining, reset_time)
            
            # Processar request
            response = await call_next(request)
            
            # Adicionar headers informativos
            self._add_rate_limit_headers(response, remaining, reset_time)
            
            return response
            
        except Exception as e:
            logger.error(f"Rate limiting middleware error: {e}")
            # Em caso de erro, permitir request (fail-open)
            return await call_next(request)
    
    def _should_apply_rate_limit(self, request: Request) -> bool:
        """Verifica se deve aplicar rate limiting"""
        path = request.url.path
        
        # Excluir paths específicos
        if path in self.excluded_paths:
            return False
        
        # Excluir arquivos estáticos
        if path.startswith("/static/") or path.endswith((".css", ".js", ".ico", ".png", ".jpg")):
            return False
        
        return True
    
    def _get_client_identifier(self, request: Request) -> str:
        """Obtém identificador único do cliente"""
        # Tentar API key primeiro
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"api_key:{hashlib.md5(api_key.encode()).hexdigest()}"
        
        # Usar IP como fallback
        # Verificar headers de proxy
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        
        return f"ip:{client_ip}"
    
    def _is_whitelisted(self, request: Request, client_id: str) -> bool:
        """Verifica se cliente está em whitelist"""
        # Verificar IP
        if client_id.startswith("ip:"):
            ip = client_id[3:]  # Remove "ip:" prefix
            if ip in self.whitelist_ips:
                return True
        
        # Verificar user agent específicos (ex: health checkers)
        user_agent = request.headers.get("User-Agent", "").lower()
        health_check_agents = ["kube-probe", "health-check", "monitoring"]
        
        if any(agent in user_agent for agent in health_check_agents):
            return True
        
        return False
    
    def _get_endpoint_limits(self, path: str) -> Dict[str, int]:
        """Obtém limites específicos para endpoint"""
        # Verificar configurações específicas
        for endpoint_path, limits in self.endpoint_limits.items():
            if path.startswith(endpoint_path):
                return limits
        
        # Usar limites padrão
        return {
            "calls": self.default_calls,
            "period": self.default_period
        }
    
    async def _check_rate_limit(self, client_id: str, endpoint: str, 
                              max_calls: int, period: int) -> tuple[bool, int, int]:
        """
        Verifica rate limit usando sliding window
        
        Returns:
            (allowed, remaining_calls, reset_time)
        """
        try:
            current_time = int(time.time())
            window_start = current_time - period
            
            # Chave do Redis
            key = f"rate_limit:{client_id}:{endpoint}"
            
            # Usar pipeline para operações atômicas
            pipe = self.redis_client.client.pipeline()
            
            # Remover entradas antigas
            pipe.zremrangebyscore(key, 0, window_start)
            
            # Contar requests no período atual
            pipe.zcard(key)
            
            # Executar pipeline
            results = pipe.execute()
            current_requests = results[1]
            
            if current_requests >= max_calls:
                # Limite excedido
                # Calcular quando o limite será resetado
                oldest_request = self.redis_client.client.zrange(key, 0, 0, withscores=True)
                if oldest_request:
                    reset_time = int(oldest_request[0][1]) + period
                else:
                    reset_time = current_time + period
                
                return False, 0, reset_time
            
            # Adicionar request atual
            self.redis_client.client.zadd(key, {str(current_time): current_time})
            
            # Definir TTL para limpeza automática
            self.redis_client.client.expire(key, period + 60)
            
            # Calcular calls restantes e reset time
            remaining = max_calls - current_requests - 1
            reset_time = current_time + period
            
            return True, remaining, reset_time
            
        except Exception as e:
            logger.error(f"Rate limit check failed: {e}")
            # Em caso de erro, permitir (fail-open)
            return True, max_calls, int(time.time()) + period
    
    async def _create_rate_limit_response(self, remaining: int, reset_time: int) -> JSONResponse:
        """Cria resposta de rate limit excedido"""
        retry_after = max(1, reset_time - int(time.time()))
        
        error_response = ErrorResponse(
            message="Rate limit exceeded",
            error_code="RATE_LIMIT_EXCEEDED",
            details={
                "retry_after_seconds": retry_after,
                "reset_time": reset_time
            }
        )
        
        headers = {
            "X-RateLimit-Limit": str(self.default_calls),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Reset": str(reset_time),
            "Retry-After": str(retry_after)
        }
        
        return JSONResponse(
            status_code=429,
            content=error_response.dict(),
            headers=headers
        )
    
    def _add_rate_limit_headers(self, response: Response, remaining: int, reset_time: int):
        """Adiciona headers informativos de rate limit"""
        try:
            response.headers["X-RateLimit-Limit"] = str(self.default_calls)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(reset_time)
            
        except Exception as e:
            logger.warning(f"Failed to add rate limit headers: {e}")
    
    def get_rate_limit_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas de rate limiting"""
        try:
            stats = {
                "requests_processed": self.requests_processed,
                "requests_limited": self.requests_limited,
                "limit_rate": (self.requests_limited / max(self.requests_processed, 1)) * 100,
                "default_limits": {
                    "calls": self.default_calls,
                    "period_seconds": self.default_period
                },
                "endpoint_limits": self.endpoint_limits,
                "whitelist_ips": len(self.whitelist_ips)
            }
            
            # Estatísticas do Redis
            try:
                # Contar chaves de rate limit ativas
                rate_limit_keys = self.redis_client.client.keys("rate_limit:*")
                stats["active_rate_limits"] = len(rate_limit_keys)
                
                # Top clients por número de requests
                client_stats = {}
                for key in rate_limit_keys[:50]:  # Limite para performance
                    try:
                        key_str = key.decode()
                        parts = key_str.split(":")
                        if len(parts) >= 3:
                            client_id = ":".join(parts[1:3])  # client_type:identifier
                            request_count = self.redis_client.client.zcard(key)
                            
                            if client_id not in client_stats:
                                client_stats[client_id] = 0
                            client_stats[client_id] += request_count
                    except Exception:
                        continue
                
                # Top 10 clients
                top_clients = sorted(client_stats.items(), key=lambda x: x[1], reverse=True)[:10]
                stats["top_clients"] = [{"client": client, "requests": count} for client, count in top_clients]
                
            except Exception as e:
                logger.warning(f"Failed to get Redis rate limit stats: {e}")
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get rate limit stats: {e}")
            return {"error": str(e)}
    
    def reset_client_limit(self, client_id: str, endpoint: str = "*") -> bool:
        """
        Reseta limite para um cliente específico
        
        Args:
            client_id: Identificador do cliente
            endpoint: Endpoint específico ou "*" para todos
            
        Returns:
            True se resetado com sucesso
        """
        try:
            if endpoint == "*":
                # Resetar todos os endpoints para este cliente
                pattern = f"rate_limit:{client_id}:*"
                keys = self.redis_client.client.keys(pattern)
            else:
                # Resetar endpoint específico
                keys = [f"rate_limit:{client_id}:{endpoint}"]
            
            if keys:
                self.redis_client.client.delete(*keys)
                logger.info(f"Rate limit reset for client {client_id}, endpoint {endpoint}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to reset rate limit for {client_id}: {e}")
            return False
    
    def add_to_whitelist(self, ip_address: str) -> bool:
        """Adiciona IP à whitelist"""
        try:
            self.whitelist_ips.add(ip_address)
            logger.info(f"IP {ip_address} added to whitelist")
            return True
        except Exception as e:
            logger.error(f"Failed to add {ip_address} to whitelist: {e}")
            return False
    
    def remove_from_whitelist(self, ip_address: str) -> bool:
        """Remove IP da whitelist"""
        try:
            self.whitelist_ips.discard(ip_address)
            logger.info(f"IP {ip_address} removed from whitelist")
            return True
        except Exception as e:
            logger.error(f"Failed to remove {ip_address} from whitelist: {e}")
            return False
    
    def update_endpoint_limit(self, endpoint: str, calls: int, period: int) -> bool:
        """Atualiza limite para endpoint específico"""
        try:
            self.endpoint_limits[endpoint] = {
                "calls": calls,
                "period": period
            }
            logger.info(f"Updated rate limit for {endpoint}: {calls} calls per {period} seconds")
            return True
        except Exception as e:
            logger.error(f"Failed to update endpoint limit: {e}")
            return False


# Função utilitária para criar middleware configurado
def create_rate_limit_middleware(
    default_calls: int = None,
    default_period: int = None,
    endpoint_limits: Dict[str, Dict[str, int]] = None,
    whitelist_ips: List[str] = None
) -> RateLimitMiddleware:
    """
    Cria middleware de rate limiting com configuração customizada
    
    Args:
        default_calls: Número padrão de calls
        default_period: Período padrão em segundos
        endpoint_limits: Limites específicos por endpoint
        whitelist_ips: IPs em whitelist
        
    Returns:
        Instância configurada do middleware
    """
    
    def middleware_factory(app):
        middleware = RateLimitMiddleware(app)
        
        if default_calls is not None:
            middleware.default_calls = default_calls
        
        if default_period is not None:
            middleware.default_period = default_period
        
        if endpoint_limits:
            middleware.endpoint_limits.update(endpoint_limits)
        
        if whitelist_ips:
            middleware.whitelist_ips.update(whitelist_ips)
        
        return middleware
    
    return middleware_factory


if __name__ == "__main__":
    """Teste do middleware de rate limiting"""
    print("=== Rate Limit Middleware Test ===")
    
    # Teste básico das funções
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)
    
    @app.get("/test")
    async def test_endpoint():
        return {"message": "success"}
    
    client = TestClient(app)
    
    # Teste múltiplas requests
    print("Testing rate limiting...")
    
    success_count = 0
    limited_count = 0
    
    for i in range(10):
        response = client.get("/test")
        if response.status_code == 200:
            success_count += 1
        elif response.status_code == 429:
            limited_count += 1
    
    print(f"Successful requests: {success_count}")
    print(f"Rate limited requests: {limited_count}")
    
    print("\n✅ Rate Limit Middleware test completed")