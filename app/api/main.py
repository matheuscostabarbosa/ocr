#!/usr/bin/env python3
"""
API Principal FastAPI - OCR Platform
====================================

API REST principal que:
- Recebe requests de OCR
- Distribui para workers especializados
- Gerencia filas e prioridades
- Monitora progresso das tasks
- Retorna resultados
"""

import time
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.models.schemas import ErrorResponse, HealthCheckResponse
from app.api.middleware.logging import LoggingMiddleware
from app.api.middleware.rate_limit import RateLimitMiddleware
from app.api.routes import ocr, health, admin

# Configurar logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Variáveis globais para tracking
start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerenciamento do ciclo de vida da aplicação"""
    # Startup
    logger.info("🚀 Starting OCR Platform API...")
    
    try:
        # Verificar conexões essenciais
        redis_client = get_redis_client()
        if not redis_client.ping():
            logger.error("❌ Redis connection failed")
            raise RuntimeError("Redis connection failed")
        
        logger.info("✅ Redis connection established")
        
        # Verificar workers disponíveis
        from app.core.celery_app import celery_app
        inspector = celery_app.control.inspect()
        
        try:
            active_workers = inspector.active()
            if active_workers:
                worker_count = len(active_workers)
                logger.info(f"✅ Found {worker_count} active workers")
            else:
                logger.warning("⚠️  No active workers found")
        except Exception as e:
            logger.warning(f"⚠️  Could not check workers: {e}")
        
        # Criar diretórios necessários
        from app.core.config import create_directories
        create_directories()
        logger.info("✅ Directories created")
        
        # Inicializar métricas
        redis_client.set_metric("api_starts", 1)
        redis_client.set_metric("api_start_time", start_time)
        
        logger.info(f"🌟 OCR Platform API started successfully on {settings.API_HOST}:{settings.API_PORT}")
        
        yield
        
    except Exception as e:
        logger.error(f"❌ Startup failed: {e}")
        raise
    
    # Shutdown
    logger.info("🛑 Shutting down OCR Platform API...")
    
    try:
        # Atualizar métricas de shutdown
        redis_client = get_redis_client()
        uptime = time.time() - start_time
        redis_client.set_metric("api_uptime", uptime)
        redis_client.set_metric("api_shutdowns", 1)
        
        # Fechar conexões
        redis_client.close()
        
        logger.info("✅ Graceful shutdown completed")
        
    except Exception as e:
        logger.error(f"❌ Shutdown error: {e}")


def create_application() -> FastAPI:
    """Cria e configura aplicação FastAPI"""
    
    app = FastAPI(
        title="OCR Platform API",
        description="""
        **Plataforma OCR On-Premise Escalável**
        
        Sistema distribuído para OCR de alta qualidade com:
        
        ## ✨ Características
        
        - **Multiple Engines**: TrOCR, Surya, PaddleOCR, EasyOCR, Tesseract, Marker
        - **Orquestração Inteligente**: Escolha automática do melhor engine
        - **Processamento Distribuído**: Workers especializados com Celery
        - **Cache Inteligente**: Redis para cache de resultados
        - **Monitoramento**: Métricas em tempo real e health checks
        - **Fallback Automático**: Tolerância a falhas
        
        ## 🎯 Engines Especializados
        
        - **TrOCR**: Melhor para manuscritos e textos degradados
        - **Surya**: Análise de layout e documentos estruturados
        - **PaddleOCR**: Processamento rápido para produção
        - **EasyOCR**: Uso geral e múltiplos idiomas
        - **Tesseract**: Fallback confiável para textos simples
        - **Marker**: Conversão PDF→Markdown de alta qualidade
        
        ## 📁 Formatos Suportados
        
        - **Imagens**: JPG, PNG, BMP, TIFF, WebP
        - **PDFs**: Processamento página por página ou conversão para Markdown
        - **Office**: DOC, DOCX, XLS, XLSX, PPT, PPTX
        - **Texto**: TXT, HTML, XML, CSV
        - **Arquivos**: ZIP (processamento recursivo)
        """,
        version=settings.VERSION,
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
        lifespan=lifespan
    )
    
    # Configurar CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.DEBUG else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Middleware de compressão
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    
    # Middleware customizado
    app.add_middleware(LoggingMiddleware)
    
    if settings.RATE_LIMIT_ENABLED:
        app.add_middleware(RateLimitMiddleware)
    
    # Incluir rotas
    app.include_router(
        ocr.router,
        prefix=settings.API_PREFIX,
        tags=["OCR"]
    )
    
    app.include_router(
        health.router,
        prefix=settings.API_PREFIX,
        tags=["Health"]
    )
    
    app.include_router(
        admin.router,
        prefix=f"{settings.API_PREFIX}/admin",
        tags=["Admin"]
    )
    
    # Handlers de erro globais
    setup_error_handlers(app)
    
    # Customizar OpenAPI
    setup_custom_openapi(app)
    
    return app


def setup_error_handlers(app: FastAPI):
    """Configura handlers de erro globais"""
    
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handler global para exceções não tratadas"""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        
        # Incrementar contador de erros
        try:
            redis_client = get_redis_client()
            redis_client.increment_metric("api_errors", tags={"type": type(exc).__name__})
        except Exception:
            pass
        
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                message="Internal server error",
                error_code="INTERNAL_ERROR",
                details={"type": type(exc).__name__} if settings.DEBUG else None
            ).dict()
        )
    
    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        """Handler para 404"""
        return JSONResponse(
            status_code=404,
            content=ErrorResponse(
                message="Endpoint not found",
                error_code="NOT_FOUND",
                details={"path": str(request.url.path)}
            ).dict()
        )
    
    @app.exception_handler(422)
    async def validation_error_handler(request: Request, exc):
        """Handler para erros de validação"""
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                message="Validation error",
                error_code="VALIDATION_ERROR",
                details=exc.errors() if hasattr(exc, 'errors') else None
            ).dict()
        )


def setup_custom_openapi(app: FastAPI):
    """Customiza documentação OpenAPI"""
    
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        
        # Adicionar informações customizadas
        openapi_schema["info"]["contact"] = {
            "name": "OCR Platform Support",
            "email": "support@ocrplatform.com"
        }
        
        openapi_schema["info"]["license"] = {
            "name": "MIT",
            "url": "https://opensource.org/licenses/MIT"
        }
        
        # Adicionar tags customizadas
        openapi_schema["tags"] = [
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
        
        # Adicionar exemplos de security schemes (se necessário)
        if settings.API_KEY_ENABLED:
            openapi_schema["components"]["securitySchemes"] = {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key"
                }
            }
        
        app.openapi_schema = openapi_schema
        return app.openapi_schema
    
    app.openapi = custom_openapi


# Criar aplicação
app = create_application()


# Endpoints raiz
@app.get(
    "/",
    summary="Root endpoint",
    description="Informações básicas da API",
    response_model=Dict[str, Any]
)
async def root():
    """Endpoint raiz com informações da API"""
    
    # Obter estatísticas básicas
    try:
        redis_client = get_redis_client()
        
        # Métricas básicas
        total_requests = redis_client.get_metric("api_total_requests") or 0
        total_errors = redis_client.get_metric("api_errors") or 0
        uptime = time.time() - start_time
        
        # Status dos workers
        from app.core.celery_app import celery_app
        try:
            inspector = celery_app.control.inspect()
            active_workers = inspector.active() or {}
            worker_count = len(active_workers)
        except Exception:
            worker_count = 0
        
        # Engines disponíveis
        from app.core.config import get_available_engines
        available_engines = get_available_engines()
        
    except Exception as e:
        logger.warning(f"Could not get statistics: {e}")
        total_requests = 0
        total_errors = 0
        uptime = time.time() - start_time
        worker_count = 0
        available_engines = []
    
    return {
        "service": "OCR Platform API",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "running",
        "uptime_seconds": round(uptime, 2),
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
            "docs": "/docs" if settings.DEBUG else None
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


@app.get("/favicon.ico")
async def favicon():
    """Favicon simples"""
    return Response(content="", media_type="image/x-icon")


# Middleware para tracking de requests
@app.middleware("http")
async def track_requests(request: Request, call_next):
    """Middleware para tracking de requests"""
    start_time_req = time.time()
    
    # Incrementar contador de requests
    try:
        redis_client = get_redis_client()
        redis_client.increment_metric("api_total_requests")
    except Exception:
        pass
    
    # Processar request
    response = await call_next(request)
    
    # Calcular tempo de resposta
    process_time = time.time() - start_time_req
    
    # Adicionar headers de resposta
    response.headers["X-Process-Time"] = str(round(process_time, 4))
    response.headers["X-API-Version"] = settings.VERSION
    
    # Registrar métricas de resposta
    try:
        redis_client = get_redis_client()
        redis_client.set_metric("api_last_response_time", process_time)
        
        # Métricas por status code
        status_group = f"{response.status_code // 100}xx"
        redis_client.increment_metric("api_responses", tags={"status": status_group})
        
    except Exception:
        pass
    
    return response


if __name__ == "__main__":
    """Executar API diretamente"""
    
    print("🚀 Starting OCR Platform API...")
    print(f"📍 Environment: {settings.ENVIRONMENT}")
    print(f"🔧 Debug mode: {settings.DEBUG}")
    print(f"📊 Redis: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
    print(f"🌐 API: http://{settings.API_HOST}:{settings.API_PORT}")
    print(f"📚 Docs: http://{settings.API_HOST}:{settings.API_PORT}/docs")
    
    # Configurar uvicorn
    uvicorn_config = {
        "app": "app.api.main:app",
        "host": settings.API_HOST,
        "port": settings.API_PORT,
        "reload": settings.DEBUG,
        "workers": 1 if settings.DEBUG else settings.API_WORKERS,
        "access_log": settings.DEBUG,
        "log_level": settings.LOG_LEVEL.lower()
    }
    
    # Executar
    uvicorn.run(**uvicorn_config)