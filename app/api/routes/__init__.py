#!/usr/bin/env python3
"""
Inicialização das Rotas
=======================

Módulo de rotas da OCR Platform que fornece:
- Rotas de OCR (processamento de documentos)
- Rotas de health check e monitoramento
- Rotas administrativas
- Configuração e setup de rotas
"""

import logging
from typing import Dict, Any, List
from fastapi import APIRouter, FastAPI

# Importar todos os roteadores
from . import ocr
from . import health
from . import admin

logger = logging.getLogger(__name__)

# Versão das rotas
__version__ = "2.0.0"

# Exportar roteadores
__all__ = [
    'ocr_router',
    'health_router', 
    'admin_router',
    'setup_routes',
    'get_routes_info',
    'create_api_router'
]

# Roteadores disponíveis
ocr_router = ocr.router
health_router = health.router
admin_router = admin.router


def setup_routes(app: FastAPI, api_prefix: str = "/api/v1", config: Dict[str, Any] = None) -> None:
    """
    Configura todas as rotas na aplicação FastAPI
    
    Args:
        app: Instância do FastAPI
        api_prefix: Prefixo para as rotas da API
        config: Configurações customizadas das rotas
    """
    config = config or {}
    
    logger.info(f"Setting up routes with prefix: {api_prefix}")
    
    # Configurar rota raiz (fora do prefixo da API)
    setup_root_routes(app, config)
    
    # Rotas principais de OCR
    if config.get("enable_ocr_routes", True):
        app.include_router(
            ocr_router,
            prefix=api_prefix,
            tags=["OCR"],
            responses={
                404: {"description": "Not found"},
                422: {"description": "Validation error"},
                500: {"description": "Internal server error"}
            }
        )
        logger.info("✅ OCR routes configured")
    
    # Rotas de health check
    if config.get("enable_health_routes", True):
        app.include_router(
            health_router,
            prefix=api_prefix,
            tags=["Health"],
            responses={
                503: {"description": "Service unavailable"}
            }
        )
        logger.info("✅ Health routes configured")
    
    # Rotas administrativas
    if config.get("enable_admin_routes", True):
        app.include_router(
            admin_router,
            prefix=f"{api_prefix}/admin",
            tags=["Admin"],
            responses={
                401: {"description": "Unauthorized"},
                403: {"description": "Forbidden"}
            }
        )
        logger.info("✅ Admin routes configured")
    
    # Rotas customizadas se especificadas
    if "custom_routers" in config:
        for router_config in config["custom_routers"]:
            app.include_router(
                router_config["router"],
                prefix=router_config.get("prefix", api_prefix),
                tags=router_config.get("tags", ["Custom"])
            )
        logger.info(f"✅ {len(config['custom_routers'])} custom routers configured")
    
    logger.info("🌟 All routes configured successfully")


def setup_root_routes(app: FastAPI, config: Dict[str, Any]) -> None:
    """Configura rotas na raiz da aplicação"""
    from fastapi import Request
    from fastapi.responses import JSONResponse, RedirectResponse
    
    @app.get("/", 
             summary="API Root",
             description="Informações básicas da API OCR Platform",
             tags=["Root"])
    async def api_root():
        """Endpoint raiz com informações da API"""
        from app.core.config import settings
        from app.core.config import get_available_engines
        import time
        
        # Obter estatísticas básicas
        try:
            from app.core.redis_client import get_redis_client
            redis_client = get_redis_client()
            
            total_requests = redis_client.get_metric("api_total_requests") or 0
            total_errors = redis_client.get_metric("api_errors") or 0
            
            # Status dos workers
            from app.core.celery_app import celery_app
            try:
                inspector = celery_app.control.inspect()
                active_workers = inspector.active() or {}
                worker_count = len(active_workers)
            except Exception:
                worker_count = 0
            
            available_engines = get_available_engines()
            
        except Exception:
            total_requests = total_errors = worker_count = 0
            available_engines = []
        
        return {
            "service": "OCR Platform API",
            "version": settings.VERSION,
            "environment": settings.ENVIRONMENT,
            "status": "running",
            "timestamp": time.time(),
            "statistics": {
                "total_requests": total_requests,
                "total_errors": total_errors,
                "error_rate": (total_errors / max(total_requests, 1)) * 100,
                "active_workers": worker_count
            },
            "capabilities": {
                "available_engines": available_engines,
                "supported_formats": [
                    "Images: JPG, PNG, BMP, TIFF, WebP",
                    "PDFs: Direct processing or Markdown conversion", 
                    "Office: DOC, DOCX, XLS, XLSX, PPT, PPTX",
                    "Text: TXT, HTML, XML, CSV",
                    "Archives: ZIP (recursive processing)"
                ]
            },
            "endpoints": {
                "ocr": f"{settings.API_PREFIX}/ocr",
                "batch": f"{settings.API_PREFIX}/batch", 
                "status": f"{settings.API_PREFIX}/status",
                "health": f"{settings.API_PREFIX}/health",
                "docs": "/docs" if settings.DEBUG else None,
                "admin": f"{settings.API_PREFIX}/admin"
            },
            "features": [
                "Intelligent engine orchestration",
                "Distributed processing with Celery",
                "Redis caching and metrics",
                "Automatic fallback mechanisms", 
                "Real-time monitoring",
                "Multiple output formats (text, markdown, JSON)"
            ]
        }
    
    # Redirecionamento para documentação
    if config.get("enable_docs_redirect", True):
        @app.get("/docs-redirect", include_in_schema=False)
        async def docs_redirect():
            return RedirectResponse(url="/docs")
    
    # Endpoint de status simples
    @app.get("/status", 
             summary="Simple Status",
             description="Status simples da API",
             tags=["Root"])
    async def simple_status():
        """Status simples para load balancers"""
        return {"status": "ok", "timestamp": time.time()}
    
    # Favicon
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        """Favicon placeholder"""
        from fastapi.responses import Response
        return Response(content="", media_type="image/x-icon")


def create_api_router(include_routers: List[str] = None, 
                     exclude_routers: List[str] = None) -> APIRouter:
    """
    Cria um roteador da API com subconjunto de rotas
    
    Args:
        include_routers: Lista de roteadores para incluir
        exclude_routers: Lista de roteadores para excluir
        
    Returns:
        APIRouter configurado
    """
    api_router = APIRouter()
    
    # Roteadores disponíveis
    available_routers = {
        "ocr": ocr_router,
        "health": health_router,
        "admin": admin_router
    }
    
    # Determinar quais roteadores incluir
    if include_routers:
        routers_to_add = {k: v for k, v in available_routers.items() if k in include_routers}
    else:
        routers_to_add = available_routers.copy()
    
    # Remover roteadores excluídos
    if exclude_routers:
        for router_name in exclude_routers:
            routers_to_add.pop(router_name, None)
    
    # Adicionar roteadores
    for router_name, router in routers_to_add.items():
        if router_name == "admin":
            api_router.include_router(router, prefix="/admin", tags=["Admin"])
        else:
            api_router.include_router(router, tags=[router_name.upper()])
    
    return api_router


def get_routes_info() -> Dict[str, Any]:
    """Retorna informações sobre as rotas disponíveis"""
    
    def get_router_info(router: APIRouter) -> Dict[str, Any]:
        """Extrai informações de um roteador"""
        routes_info = []
        
        for route in router.routes:
            if hasattr(route, 'methods') and hasattr(route, 'path'):
                routes_info.append({
                    "path": route.path,
                    "methods": list(route.methods),
                    "name": getattr(route, 'name', None),
                    "summary": getattr(route, 'summary', None)
                })
        
        return {
            "route_count": len(routes_info),
            "routes": routes_info
        }
    
    return {
        "version": __version__,
        "routers": {
            "ocr": get_router_info(ocr_router),
            "health": get_router_info(health_router), 
            "admin": get_router_info(admin_router)
        },
        "total_routes": sum(
            get_router_info(router)["route_count"] 
            for router in [ocr_router, health_router, admin_router]
        )
    }


def validate_routes_config(config: Dict[str, Any]) -> tuple[bool, str]:
    """
    Valida configuração das rotas
    
    Args:
        config: Configuração a validar
        
    Returns:
        Tuple (is_valid, error_message)
    """
    try:
        # Verificar chaves obrigatórias
        valid_keys = {
            "enable_ocr_routes", "enable_health_routes", "enable_admin_routes",
            "enable_docs_redirect", "custom_routers"
        }
        
        for key in config:
            if key not in valid_keys:
                return False, f"Invalid config key: {key}"
        
        # Validar custom_routers se presente
        if "custom_routers" in config:
            custom_routers = config["custom_routers"]
            if not isinstance(custom_routers, list):
                return False, "custom_routers must be a list"
            
            for router_config in custom_routers:
                if not isinstance(router_config, dict):
                    return False, "Each custom router config must be a dict"
                
                if "router" not in router_config:
                    return False, "Each custom router config must have 'router' key"
        
        return True, ""
        
    except Exception as e:
        return False, f"Config validation error: {str(e)}"


def get_endpoint_metrics() -> Dict[str, Any]:
    """Retorna métricas dos endpoints"""
    try:
        from app.core.redis_client import get_redis_client
        redis_client = get_redis_client()
        
        metrics = {
            "total_requests": redis_client.get_metric("http_requests_total") or 0,
            "total_errors": redis_client.get_metric("http_errors_total") or 0,
            "avg_response_time": redis_client.get_metric("http_request_duration_seconds") or 0,
            "endpoints": {}
        }
        
        # Métricas por endpoint (simplificado)
        common_endpoints = ["/ocr", "/batch", "/health", "/status", "/admin"]
        
        for endpoint in common_endpoints:
            endpoint_requests = redis_client.get_metric(
                "http_requests_by_endpoint", 
                tags={"endpoint": endpoint, "method": "POST"}
            ) or 0
            
            metrics["endpoints"][endpoint] = {
                "requests": endpoint_requests,
                "methods": ["GET", "POST"] if endpoint in ["/ocr", "/batch"] else ["GET"]
            }
        
        return metrics
        
    except Exception as e:
        logger.warning(f"Failed to get endpoint metrics: {e}")
        return {"error": str(e)}


# Configurações padrão para diferentes ambientes
DEVELOPMENT_CONFIG = {
    "enable_ocr_routes": True,
    "enable_health_routes": True,
    "enable_admin_routes": True,
    "enable_docs_redirect": True
}

PRODUCTION_CONFIG = {
    "enable_ocr_routes": True,
    "enable_health_routes": True,
    "enable_admin_routes": False,  # Desabilitar admin em produção por segurança
    "enable_docs_redirect": False
}

TESTING_CONFIG = {
    "enable_ocr_routes": True,
    "enable_health_routes": True,
    "enable_admin_routes": True,
    "enable_docs_redirect": False
}


def get_config_for_environment(environment: str) -> Dict[str, Any]:
    """Retorna configuração apropriada para o ambiente"""
    configs = {
        "development": DEVELOPMENT_CONFIG,
        "staging": DEVELOPMENT_CONFIG,
        "production": PRODUCTION_CONFIG,
        "testing": TESTING_CONFIG
    }
    
    return configs.get(environment, DEVELOPMENT_CONFIG)


if __name__ == "__main__":
    """Teste do módulo de rotas"""
    print("=== Routes Module Test ===")
    
    # Informações das rotas
    routes_info = get_routes_info()
    print(f"Routes version: {routes_info['version']}")
    print(f"Total routes: {routes_info['total_routes']}")
    
    for router_name, router_info in routes_info["routers"].items():
        print(f"  {router_name}: {router_info['route_count']} routes")
    
    # Teste de validação de configuração
    test_config = {
        "enable_ocr_routes": True,
        "enable_health_routes": True,
        "enable_admin_routes": False
    }
    
    is_valid, error = validate_routes_config(test_config)
    print(f"Config validation: {'✅ Valid' if is_valid else f'❌ Invalid: {error}'}")
    
    # Configuração por ambiente
    dev_config = get_config_for_environment("development")
    prod_config = get_config_for_environment("production")
    
    print(f"Development config: {dev_config}")
    print(f"Production config: {prod_config}")
    
    # Teste de criação de roteador customizado
    custom_router = create_api_router(include_routers=["ocr", "health"])
    print(f"Custom router created with routes: {len(custom_router.routes)}")
    
    print("\n✅ Routes module test completed")