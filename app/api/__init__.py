#!/usr/bin/env python3
"""
API Module - OCR Platform
=========================

Módulo da API REST da plataforma OCR que inclui:
- Endpoints para processamento OCR
- Middleware de autenticação, logging e rate limiting
- Dependências reutilizáveis
- Documentação automática
- Monitoramento e health checks

Componentes:
- main.py: Aplicação FastAPI principal
- routes/: Endpoints organizados por funcionalidade
- middleware/: Middleware customizado
- dependencies.py: Dependências injetáveis

Endpoints Principais:
- POST /api/v1/ocr: Processamento de documento único
- POST /api/v1/batch: Processamento em lote  
- GET /api/v1/status/{task_id}: Status de task
- GET /api/v1/result/{task_id}: Resultado de task
- GET /api/v1/health: Health checks
- GET /api/v1/admin/*: Endpoints administrativos
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Informações do módulo
__version__ = "2.0.0"
__description__ = "OCR Platform REST API"

# Configurações da API
API_SETTINGS = {
    "title": "OCR Platform API",
    "description": "Sistema distribuído para OCR de alta qualidade",
    "version": __version__,
    "docs_url": "/docs",
    "redoc_url": "/redoc"
}

# Endpoints disponíveis
AVAILABLE_ENDPOINTS = {
    "ocr": {
        "path": "/api/v1/ocr",
        "methods": ["POST"],
        "description": "Processar documento único",
        "auth_required": False
    },
    "batch_ocr": {
        "path": "/api/v1/batch", 
        "methods": ["POST"],
        "description": "Processar múltiplos documentos",
        "auth_required": False
    },
    "task_status": {
        "path": "/api/v1/status/{task_id}",
        "methods": ["GET"],
        "description": "Consultar status de task",
        "auth_required": False
    },
    "task_result": {
        "path": "/api/v1/result/{task_id}",
        "methods": ["GET"],
        "description": "Obter resultado de task",
        "auth_required": False
    },
    "cancel_task": {
        "path": "/api/v1/task/{task_id}",
        "methods": ["DELETE"],
        "description": "Cancelar task",
        "auth_required": False
    },
    "batch_status": {
        "path": "/api/v1/batch/{batch_id}",
        "methods": ["GET"],
        "description": "Status de lote",
        "auth_required": False
    },
    "engines": {
        "path": "/api/v1/engines",
        "methods": ["GET"],
        "description": "Listar engines disponíveis",
        "auth_required": False
    },
    "health": {
        "path": "/api/v1/health",
        "methods": ["GET"],
        "description": "Health check básico",
        "auth_required": False
    },
    "health_detailed": {
        "path": "/api/v1/health/detailed",
        "methods": ["GET"],
        "description": "Health check detalhado",
        "auth_required": False
    },
    "ping": {
        "path": "/api/v1/ping",
        "methods": ["GET"],
        "description": "Ping simples",
        "auth_required": False
    },
    "admin_stats": {
        "path": "/api/v1/admin/stats",
        "methods": ["GET"],
        "description": "Estatísticas do sistema",
        "auth_required": True
    },
    "admin_queues": {
        "path": "/api/v1/admin/queues",
        "methods": ["GET"],
        "description": "Status das filas",
        "auth_required": True
    },
    "admin_workers": {
        "path": "/api/v1/admin/workers",
        "methods": ["GET"],
        "description": "Status dos workers",
        "auth_required": True
    }
}

# Middleware configurado
MIDDLEWARE_COMPONENTS = [
    "CORSMiddleware",
    "GZipMiddleware", 
    "LoggingMiddleware",
    "RateLimitMiddleware"
]

# Tags para documentação
API_TAGS = [
    {
        "name": "OCR",
        "description": "Operações de OCR e processamento de documentos"
    },
    {
        "name": "Health",
        "description": "Health checks e status do sistema"
    },
    {
        "name": "Admin", 
        "description": "Operações administrativas e monitoramento"
    }
]


def get_api_info() -> Dict[str, Any]:
    """Retorna informações da API"""
    return {
        "module": __name__,
        "version": __version__,
        "description": __description__,
        "settings": API_SETTINGS,
        "middleware": MIDDLEWARE_COMPONENTS,
        "tags": API_TAGS
    }


def get_endpoints_info() -> Dict[str, Any]:
    """Retorna informações dos endpoints"""
    return {
        "total_endpoints": len(AVAILABLE_ENDPOINTS),
        "endpoints": AVAILABLE_ENDPOINTS,
        "public_endpoints": [
            name for name, info in AVAILABLE_ENDPOINTS.items()
            if not info.get("auth_required", False)
        ],
        "protected_endpoints": [
            name for name, info in AVAILABLE_ENDPOINTS.items()
            if info.get("auth_required", False)
        ]
    }


def check_api_dependencies() -> Dict[str, Any]:
    """Verifica dependências da API"""
    dependencies_status = {}
    
    # FastAPI e dependências essenciais
    required_deps = {
        "fastapi": "Web framework",
        "uvicorn": "ASGI server",
        "pydantic": "Data validation",
        "starlette": "ASGI toolkit"
    }
    
    for dep, description in required_deps.items():
        try:
            __import__(dep)
            dependencies_status[dep] = {"status": "available", "description": description}
        except ImportError:
            dependencies_status[dep] = {"status": "missing", "description": description}
    
    # Dependências opcionais
    optional_deps = {
        "python-multipart": "File upload support",
        "aiofiles": "Async file operations",
        "jinja2": "Template engine",
        "python-jose": "JWT support"
    }
    
    for dep, description in optional_deps.items():
        try:
            if dep == "python-multipart":
                import multipart
            elif dep == "python-jose":
                import jose
            else:
                __import__(dep.replace("-", "_"))
            dependencies_status[dep] = {"status": "available", "description": description}
        except ImportError:
            dependencies_status[dep] = {"status": "optional_missing", "description": description}
    
    return dependencies_status


def validate_api_configuration() -> Dict[str, Any]:
    """Valida configuração da API"""
    validation_results = {
        "configuration_valid": True,
        "issues": [],
        "warnings": []
    }
    
    try:
        # Verificar se configuração está disponível
        from app.core.config import settings
        
        # Validar configurações essenciais
        if not settings.API_HOST:
            validation_results["issues"].append("API_HOST not configured")
            validation_results["configuration_valid"] = False
        
        if not settings.API_PORT:
            validation_results["issues"].append("API_PORT not configured")
            validation_results["configuration_valid"] = False
        
        if settings.API_PORT < 1024 and settings.API_HOST == "0.0.0.0":
            validation_results["warnings"].append("Using privileged port with all interfaces")
        
        # Verificar Redis
        if not settings.REDIS_HOST:
            validation_results["issues"].append("REDIS_HOST not configured")
            validation_results["configuration_valid"] = False
        
        # Verificar Celery
        if not settings.CELERY_BROKER_URL:
            validation_results["issues"].append("CELERY_BROKER_URL not configured")
            validation_results["configuration_valid"] = False
        
        # Warnings para desenvolvimento
        if settings.DEBUG and settings.ENVIRONMENT == "production":
            validation_results["warnings"].append("DEBUG enabled in production environment")
        
        if not settings.SECRET_KEY or settings.SECRET_KEY == "your-secret-key-change-in-production":
            validation_results["warnings"].append("Default SECRET_KEY being used")
        
    except ImportError:
        validation_results["issues"].append("Configuration module not available")
        validation_results["configuration_valid"] = False
    except Exception as e:
        validation_results["issues"].append(f"Configuration validation failed: {e}")
        validation_results["configuration_valid"] = False
    
    return validation_results


def check_routes_availability() -> Dict[str, Any]:
    """Verifica disponibilidade das rotas"""
    routes_status = {}
    
    try:
        # Verificar módulos de rotas
        route_modules = ["ocr", "health", "admin"]
        
        for module_name in route_modules:
            try:
                module_path = f"app.api.routes.{module_name}"
                __import__(module_path)
                routes_status[module_name] = {"status": "available", "module": module_path}
            except ImportError as e:
                routes_status[module_name] = {"status": "missing", "error": str(e)}
        
        # Verificar middleware
        middleware_modules = ["auth", "logging", "rate_limit"]
        middleware_status = {}
        
        for middleware_name in middleware_modules:
            try:
                middleware_path = f"app.api.middleware.{middleware_name}"
                __import__(middleware_path)
                middleware_status[middleware_name] = {"status": "available", "module": middleware_path}
            except ImportError as e:
                middleware_status[middleware_name] = {"status": "missing", "error": str(e)}
        
        routes_status["middleware"] = middleware_status
        
    except Exception as e:
        routes_status["error"] = str(e)
    
    return routes_status


def get_api_health() -> Dict[str, Any]:
    """Retorna status de saúde da API"""
    health_status = {
        "api_module": "healthy",
        "timestamp": None,
        "components": {}
    }
    
    try:
        import time
        health_status["timestamp"] = time.time()
        
        # Verificar dependências
        deps = check_api_dependencies()
        missing_required = [
            name for name, info in deps.items()
            if info["status"] == "missing" and name in ["fastapi", "uvicorn", "pydantic"]
        ]
        
        if missing_required:
            health_status["api_module"] = "unhealthy"
            health_status["missing_dependencies"] = missing_required
        
        health_status["components"]["dependencies"] = deps
        
        # Verificar configuração
        config_validation = validate_api_configuration()
        if not config_validation["configuration_valid"]:
            health_status["api_module"] = "degraded"
        
        health_status["components"]["configuration"] = config_validation
        
        # Verificar rotas
        routes_status = check_routes_availability()
        health_status["components"]["routes"] = routes_status
        
        # Verificar se aplicação FastAPI pode ser criada
        try:
            from app.api.main import create_application
            app = create_application()
            health_status["components"]["fastapi_app"] = {"status": "can_create"}
        except Exception as e:
            health_status["components"]["fastapi_app"] = {"status": "creation_failed", "error": str(e)}
            health_status["api_module"] = "degraded"
        
    except Exception as e:
        health_status["api_module"] = "unhealthy"
        health_status["error"] = str(e)
    
    return health_status


def get_api_stats() -> Dict[str, Any]:
    """Retorna estatísticas da API"""
    stats = {
        "module_info": get_api_info(),
        "endpoints_info": get_endpoints_info(),
        "dependencies": check_api_dependencies(),
        "configuration": validate_api_configuration(),
        "routes": check_routes_availability(),
        "health": get_api_health()
    }
    
    # Calcular métricas sumárias
    deps = stats["dependencies"]
    total_deps = len(deps)
    available_deps = sum(1 for info in deps.values() if info["status"] == "available")
    
    routes = stats["routes"]
    if isinstance(routes, dict) and "middleware" in routes:
        total_routes = len([k for k, v in routes.items() if k != "middleware"])
        available_routes = sum(1 for k, v in routes.items() 
                             if k != "middleware" and v.get("status") == "available")
        
        middleware = routes.get("middleware", {})
        total_middleware = len(middleware)
        available_middleware = sum(1 for info in middleware.values() 
                                 if info.get("status") == "available")
    else:
        total_routes = available_routes = 0
        total_middleware = available_middleware = 0
    
    stats["summary"] = {
        "dependencies_ratio": f"{available_deps}/{total_deps}",
        "routes_ratio": f"{available_routes}/{total_routes}",
        "middleware_ratio": f"{available_middleware}/{total_middleware}",
        "overall_health": stats["health"]["api_module"]
    }
    
    return stats


# Exportar elementos principais
__all__ = [
    # Informações do módulo
    "__version__",
    "__description__",
    "API_SETTINGS",
    "AVAILABLE_ENDPOINTS",
    "MIDDLEWARE_COMPONENTS",
    "API_TAGS",
    
    # Funções de informação
    "get_api_info",
    "get_endpoints_info",
    "check_api_dependencies",
    "validate_api_configuration",
    "check_routes_availability",
    "get_api_health",
    "get_api_stats"
]

# Log de inicialização
logger.info(f"📡 OCR Platform API Module v{__version__} initialized")

# Verificação automática de saúde
try:
    health = get_api_health()
    if health["api_module"] == "healthy":
        logger.info("✅ API module health check: HEALTHY")
    elif health["api_module"] == "degraded":
        logger.warning("⚠️  API module health check: DEGRADED")
        if "components" in health:
            config = health["components"].get("configuration", {})
            if config.get("warnings"):
                for warning in config["warnings"]:
                    logger.warning(f"Configuration warning: {warning}")
    else:
        logger.error("❌ API module health check: UNHEALTHY")
        if health.get("error"):
            logger.error(f"Health check error: {health['error']}")

except Exception as e:
    logger.error(f"Failed to perform API module health check: {e}")

if __name__ == "__main__":
    # Quando executado diretamente, mostrar informações detalhadas
    print(f"\n📡 OCR Platform API Module v{__version__}")
    print("=" * 60)
    
    # Informações gerais
    api_info = get_api_info()
    print(f"Description: {api_info['description']}")
    print(f"Version: {api_info['version']}")
    
    # Endpoints
    endpoints_info = get_endpoints_info()
    print(f"\n📍 Endpoints ({endpoints_info['total_endpoints']} total):")
    print(f"  Public: {len(endpoints_info['public_endpoints'])}")
    print(f"  Protected: {len(endpoints_info['protected_endpoints'])}")
    
    # Dependencies
    print(f"\n🔗 Dependencies:")
    deps = check_api_dependencies()
    for name, info in deps.items():
        status_icon = "✅" if info["status"] == "available" else "❌" if info["status"] == "missing" else "⚠️"
        print(f"  {status_icon} {name}: {info['description']}")
    
    # Configuration
    print(f"\n⚙️  Configuration:")
    config = validate_api_configuration()
    if config["configuration_valid"]:
        print("  ✅ Configuration valid")
    else:
        print("  ❌ Configuration has issues:")
        for issue in config["issues"]:
            print(f"    - {issue}")
    
    if config["warnings"]:
        print("  ⚠️  Warnings:")
        for warning in config["warnings"]:
            print(f"    - {warning}")
    
    # Health
    print(f"\n🏥 Health Status:")
    health = get_api_health()
    health_icon = "✅" if health["api_module"] == "healthy" else "⚠️" if health["api_module"] == "degraded" else "❌"
    print(f"  {health_icon} API Module: {health['api_module'].upper()}")
    
    print("=" * 60)