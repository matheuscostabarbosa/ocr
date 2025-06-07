#!/usr/bin/env python3
"""
OCR Platform - Módulo Principal
===============================

Plataforma OCR On-Premise Escalável

Sistema distribuído para OCR de alta qualidade com:
- Múltiplos engines especializados (TrOCR, Surya, PaddleOCR, EasyOCR, Tesseract, Marker)
- Orquestração inteligente de processamento
- Processamento distribuído com Celery
- Cache e métricas com Redis
- API REST com FastAPI
- Monitoramento em tempo real

Arquitetura:
- API Gateway: Recebe requests e distribui tasks
- Orchestrator: Escolhe melhor engine baseado no documento
- Workers: Executam OCR específico para cada engine
- Queue Manager: Gerencia filas e balanceamento de carga
- Result Processor: Agrega e pós-processa resultados
- Storage Service: Gerencia arquivos e resultados

Engines Disponíveis:
- TrOCR: Manuscritos e textos degradados
- Surya: Análise de layout e documentos estruturados
- PaddleOCR: Processamento rápido para produção
- EasyOCR: Uso geral e múltiplos idiomas
- Tesseract: Fallback confiável para textos simples
- Marker: Conversão PDF→Markdown de alta qualidade
"""

import logging
import sys
from pathlib import Path

# Informações da aplicação
__title__ = "OCR Platform"
__description__ = "Plataforma OCR On-Premise Escalável"
__version__ = "2.0.0"
__author__ = "OCR Platform Team"
__license__ = "MIT"

# Configurar logging básico
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Verificar versão do Python
if sys.version_info < (3, 8):
    raise RuntimeError("OCR Platform requires Python 3.8 or higher")

# Adicionar diretório raiz ao path se necessário
app_root = Path(__file__).parent.parent
if str(app_root) not in sys.path:
    sys.path.insert(0, str(app_root))

# Importações principais (lazy loading para evitar problemas de dependências circulares)
def get_app_info():
    """Retorna informações da aplicação"""
    return {
        "title": __title__,
        "description": __description__,
        "version": __version__,
        "author": __author__,
        "license": __license__
    }

def get_available_components():
    """Retorna componentes disponíveis da aplicação"""
    components = {
        "api": "FastAPI REST API",
        "workers": "Celery workers para processamento OCR",
        "orchestrator": "Orquestração inteligente de engines",
        "queue_manager": "Gerenciamento de filas e balanceamento",
        "result_processor": "Processamento e agregação de resultados",
        "storage_service": "Armazenamento de arquivos e resultados",
        "core": "Configuração, Redis e Celery"
    }
    
    # Verificar quais componentes estão disponíveis
    available = {}
    
    try:
        from . import api
        available["api"] = components["api"]
    except ImportError as e:
        logger.warning(f"API component not available: {e}")
    
    try:
        from . import workers
        available["workers"] = components["workers"]
    except ImportError as e:
        logger.warning(f"Workers component not available: {e}")
    
    try:
        from . import services
        available["orchestrator"] = components["orchestrator"]
        available["queue_manager"] = components["queue_manager"]
        available["result_processor"] = components["result_processor"]
        available["storage_service"] = components["storage_service"]
    except ImportError as e:
        logger.warning(f"Services component not available: {e}")
    
    try:
        from . import core
        available["core"] = components["core"]
    except ImportError as e:
        logger.warning(f"Core component not available: {e}")
    
    return available

def check_dependencies():
    """Verifica dependências essenciais"""
    dependencies_status = {}
    
    # Dependências obrigatórias
    required_deps = {
        "fastapi": "FastAPI web framework",
        "celery": "Distributed task queue",
        "redis": "Redis client",
        "pydantic": "Data validation",
        "uvicorn": "ASGI server",
        "pathlib": "Path handling",
        "PIL": "Image processing"
    }
    
    for dep, description in required_deps.items():
        try:
            __import__(dep)
            dependencies_status[dep] = {"status": "available", "description": description}
        except ImportError:
            dependencies_status[dep] = {"status": "missing", "description": description}
            logger.error(f"Required dependency missing: {dep} - {description}")
    
    # Dependências opcionais dos engines
    optional_deps = {
        "transformers": "TrOCR engine support",
        "torch": "PyTorch for deep learning engines",
        "paddleocr": "PaddleOCR engine",
        "easyocr": "EasyOCR engine", 
        "pytesseract": "Tesseract engine",
        "surya": "Surya OCR engine",
        "marker": "Marker PDF processing",
        "fitz": "PyMuPDF for PDF processing",
        "cv2": "OpenCV for image processing"
    }
    
    for dep, description in optional_deps.items():
        try:
            if dep == "fitz":
                import fitz
            elif dep == "cv2":
                import cv2
            else:
                __import__(dep)
            dependencies_status[dep] = {"status": "available", "description": description}
        except ImportError:
            dependencies_status[dep] = {"status": "optional_missing", "description": description}
            logger.info(f"Optional dependency missing: {dep} - {description}")
    
    return dependencies_status

def initialize_application():
    """Inicializa a aplicação"""
    try:
        logger.info(f"🚀 Initializing {__title__} v{__version__}")
        
        # Verificar dependências
        deps = check_dependencies()
        missing_required = [
            name for name, info in deps.items() 
            if info["status"] == "missing"
        ]
        
        if missing_required:
            logger.error(f"❌ Missing required dependencies: {', '.join(missing_required)}")
            return False
        
        # Verificar componentes
        components = get_available_components()
        logger.info(f"📦 Available components: {', '.join(components.keys())}")
        
        # Inicializar configuração se disponível
        try:
            from .core.config import settings
            logger.info(f"⚙️  Configuration loaded: {settings.ENVIRONMENT} environment")
        except ImportError:
            logger.warning("⚠️  Configuration not available")
        
        # Inicializar serviços se disponível
        try:
            from .services import initialize_services
            service_status = initialize_services()
            successful_services = sum(service_status.values())
            total_services = len(service_status)
            logger.info(f"🔧 Services initialized: {successful_services}/{total_services}")
        except ImportError:
            logger.warning("⚠️  Services not available")
        
        logger.info(f"✅ {__title__} initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize application: {e}")
        return False

def get_system_status():
    """Retorna status do sistema"""
    status = {
        "application": get_app_info(),
        "components": get_available_components(),
        "dependencies": check_dependencies(),
        "initialization_status": "not_initialized"
    }
    
    try:
        # Verificar se serviços estão rodando
        from .services import get_services_health
        services_health = get_services_health()
        status["services_health"] = services_health
        status["initialization_status"] = "initialized"
    except ImportError:
        logger.debug("Services module not available for status check")
    except Exception as e:
        logger.warning(f"Failed to get services health: {e}")
        status["services_error"] = str(e)
    
    try:
        # Verificar configuração
        from .core.config import settings
        status["configuration"] = {
            "environment": settings.ENVIRONMENT,
            "debug": settings.DEBUG,
            "version": settings.VERSION,
            "api_host": settings.API_HOST,
            "api_port": settings.API_PORT
        }
    except ImportError:
        logger.debug("Configuration not available for status check")
    
    return status

# Exportar elementos principais
__all__ = [
    # Informações da aplicação
    "__version__",
    "__title__", 
    "__description__",
    "__author__",
    "__license__",
    
    # Funções utilitárias
    "get_app_info",
    "get_available_components", 
    "check_dependencies",
    "initialize_application",
    "get_system_status"
]

# Inicialização automática quando importado
if __name__ != "__main__":
    logger.info(f"📚 {__title__} v{__version__} module loaded")
else:
    # Quando executado diretamente, mostrar informações do sistema
    print(f"\n🔍 {__title__} v{__version__} - System Information")
    print("=" * 60)
    
    # Informações da aplicação
    app_info = get_app_info()
    print(f"Title: {app_info['title']}")
    print(f"Version: {app_info['version']}")
    print(f"Description: {app_info['description']}")
    
    # Componentes disponíveis
    print(f"\n📦 Available Components:")
    components = get_available_components()
    for name, desc in components.items():
        print(f"  ✅ {name}: {desc}")
    
    # Status das dependências
    print(f"\n🔗 Dependencies Status:")
    deps = check_dependencies()
    for name, info in deps.items():
        status_icon = "✅" if info["status"] == "available" else "❌" if info["status"] == "missing" else "⚠️"
        print(f"  {status_icon} {name}: {info['description']} ({info['status']})")
    
    # Tentar inicializar
    print(f"\n🚀 Initializing Application:")
    success = initialize_application()
    
    if success:
        print(f"\n🎉 System Status: READY")
        
        # Mostrar status detalhado se disponível
        try:
            status = get_system_status()
            if "services_health" in status:
                health = status["services_health"]
                print(f"Services Health: {health.get('overall_status', 'unknown').upper()}")
        except Exception as e:
            print(f"Could not get detailed status: {e}")
    else:
        print(f"\n❌ System Status: FAILED TO INITIALIZE")
    
    print("=" * 60)