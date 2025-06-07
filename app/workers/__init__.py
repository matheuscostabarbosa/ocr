#!/usr/bin/env python3
"""
Módulo de Workers OCR
====================

Workers especializados para processamento OCR distribuído:
- Base worker com funcionalidades comuns
- TrOCR worker para manuscritos
- Surya worker para layout complexo
- PaddleOCR worker para produção rápida
- EasyOCR worker para uso geral
- Tesseract worker para fallback
- Marker worker para PDF→Markdown
- Orchestrator worker para coordenação
"""

import logging
from typing import Dict, Any, List, Optional

# Versão dos workers
__version__ = "2.0.0"

logger = logging.getLogger(__name__)

# Importar classe base
from .base_worker import BaseOCRWorker

# Importar workers específicos (com tratamento de dependências)
try:
    from .trocr_worker import TrOCRWorker, trocr_process_image, trocr_health_check
    TROCR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"TrOCR worker not available: {e}")
    TROCR_AVAILABLE = False
    TrOCRWorker = None
    trocr_process_image = None
    trocr_health_check = None

try:
    from .surya_worker import SuryaWorker, surya_process_image, surya_health_check
    SURYA_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Surya worker not available: {e}")
    SURYA_AVAILABLE = False
    SuryaWorker = None
    surya_process_image = None
    surya_health_check = None

try:
    from .paddleocr_worker import PaddleOCRWorker, paddleocr_process_image, paddleocr_health_check
    PADDLEOCR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"PaddleOCR worker not available: {e}")
    PADDLEOCR_AVAILABLE = False
    PaddleOCRWorker = None
    paddleocr_process_image = None
    paddleocr_health_check = None

try:
    from .easyocr_worker import EasyOCRWorker, easyocr_process_image, easyocr_health_check
    EASYOCR_AVAILABLE = True
except ImportError as e:
    logger.warning(f"EasyOCR worker not available: {e}")
    EASYOCR_AVAILABLE = False
    EasyOCRWorker = None
    easyocr_process_image = None
    easyocr_health_check = None

try:
    from .tesseract_worker import TesseractWorker, tesseract_process_image, tesseract_health_check
    TESSERACT_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Tesseract worker not available: {e}")
    TESSERACT_AVAILABLE = False
    TesseractWorker = None
    tesseract_process_image = None
    tesseract_health_check = None

try:
    from .marker_worker import MarkerWorker, marker_process_pdf, marker_health_check
    MARKER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Marker worker not available: {e}")
    MARKER_AVAILABLE = False
    MarkerWorker = None
    marker_process_pdf = None
    marker_health_check = None

# Orchestrator worker (sempre disponível)
from .orchestrator_worker import OrchestratorWorker, orchestrate_ocr_task, orchestrator_health_check

# Exportar classes e funções principais
__all__ = [
    # Classe base
    'BaseOCRWorker',
    
    # Classes de workers
    'TrOCRWorker',
    'SuryaWorker', 
    'PaddleOCRWorker',
    'EasyOCRWorker',
    'TesseractWorker',
    'MarkerWorker',
    'OrchestratorWorker',
    
    # Tasks Celery
    'trocr_process_image',
    'surya_process_image',
    'paddleocr_process_image',
    'easyocr_process_image',
    'tesseract_process_image',
    'marker_process_pdf',
    'orchestrate_ocr_task',
    
    # Health checks
    'trocr_health_check',
    'surya_health_check',
    'paddleocr_health_check',
    'easyocr_health_check',
    'tesseract_health_check',
    'marker_health_check',
    'orchestrator_health_check',
    
    # Flags de disponibilidade
    'TROCR_AVAILABLE',
    'SURYA_AVAILABLE',
    'PADDLEOCR_AVAILABLE',
    'EASYOCR_AVAILABLE',
    'TESSERACT_AVAILABLE',
    'MARKER_AVAILABLE',
    
    # Funções utilitárias
    'get_available_workers',
    'get_worker_info',
    'test_worker_availability',
    'get_worker_class',
    'get_worker_task'
]


def get_available_workers() -> List[str]:
    """
    Retorna lista de workers disponíveis
    
    Returns:
        Lista de nomes de workers disponíveis
    """
    available = []
    
    if TROCR_AVAILABLE:
        available.append("trocr")
    if SURYA_AVAILABLE:
        available.append("surya")
    if PADDLEOCR_AVAILABLE:
        available.append("paddleocr")
    if EASYOCR_AVAILABLE:
        available.append("easyocr")
    if TESSERACT_AVAILABLE:
        available.append("tesseract")
    if MARKER_AVAILABLE:
        available.append("marker")
    
    # Orchestrator sempre disponível
    available.append("orchestrator")
    
    return available


def get_worker_info() -> Dict[str, Any]:
    """
    Retorna informações detalhadas sobre todos os workers
    
    Returns:
        Dict com informações dos workers
    """
    info = {
        "version": __version__,
        "available_workers": get_available_workers(),
        "worker_details": {},
        "total_available": 0,
        "total_possible": 7  # Total de workers implementados
    }
    
    # Detalhes de cada worker
    worker_configs = {
        "trocr": {
            "name": "TrOCR",
            "description": "Specialized for handwritten and degraded text",
            "use_cases": ["handwritten", "poor_quality", "complex_text"],
            "gpu_required": True,
            "available": TROCR_AVAILABLE
        },
        "surya": {
            "name": "Surya OCR",
            "description": "Advanced layout analysis and structured documents",
            "use_cases": ["layout_analysis", "structured_documents", "tables"],
            "gpu_required": True,
            "available": SURYA_AVAILABLE
        },
        "paddleocr": {
            "name": "PaddleOCR",
            "description": "Fast production OCR processing",
            "use_cases": ["production", "fast_processing", "general"],
            "gpu_required": False,
            "available": PADDLEOCR_AVAILABLE
        },
        "easyocr": {
            "name": "EasyOCR",
            "description": "General purpose and multilingual OCR",
            "use_cases": ["general", "multilingual", "simple"],
            "gpu_required": False,
            "available": EASYOCR_AVAILABLE
        },
        "tesseract": {
            "name": "Tesseract",
            "description": "Reliable fallback for simple text",
            "use_cases": ["fallback", "simple_text", "digital_documents"],
            "gpu_required": False,
            "available": TESSERACT_AVAILABLE
        },
        "marker": {
            "name": "Marker",
            "description": "PDF to Markdown conversion",
            "use_cases": ["pdf_to_markdown", "academic_papers", "structured_pdf"],
            "gpu_required": True,
            "available": MARKER_AVAILABLE
        },
        "orchestrator": {
            "name": "Orchestrator",
            "description": "Intelligent coordination and routing",
            "use_cases": ["coordination", "routing", "fallback_management"],
            "gpu_required": False,
            "available": True
        }
    }
    
    info["worker_details"] = worker_configs
    info["total_available"] = len(get_available_workers())
    
    # Estatísticas
    gpu_workers = sum(1 for w in worker_configs.values() if w["gpu_required"] and w["available"])
    cpu_workers = sum(1 for w in worker_configs.values() if not w["gpu_required"] and w["available"])
    
    info["statistics"] = {
        "gpu_workers_available": gpu_workers,
        "cpu_workers_available": cpu_workers,
        "availability_rate": (info["total_available"] / info["total_possible"]) * 100
    }
    
    return info


def test_worker_availability() -> Dict[str, Any]:
    """
    Testa disponibilidade de todos os workers
    
    Returns:
        Dict com resultados dos testes
    """
    results = {
        "timestamp": None,
        "worker_tests": {},
        "summary": {
            "total_workers": 0,
            "available_workers": 0,
            "failed_workers": 0
        }
    }
    
    try:
        import time
        results["timestamp"] = time.time()
        
        # Testar cada worker
        workers_to_test = [
            ("trocr", TROCR_AVAILABLE, TrOCRWorker),
            ("surya", SURYA_AVAILABLE, SuryaWorker),
            ("paddleocr", PADDLEOCR_AVAILABLE, PaddleOCRWorker),
            ("easyocr", EASYOCR_AVAILABLE, EasyOCRWorker),
            ("tesseract", TESSERACT_AVAILABLE, TesseractWorker),
            ("marker", MARKER_AVAILABLE, MarkerWorker),
            ("orchestrator", True, OrchestratorWorker)
        ]
        
        for worker_name, available, worker_class in workers_to_test:
            results["summary"]["total_workers"] += 1
            
            test_result = {
                "available": available,
                "class_loadable": worker_class is not None,
                "instantiation_test": False,
                "error": None
            }
            
            if available and worker_class:
                try:
                    # Tentar instanciar worker
                    worker_instance = worker_class()
                    test_result["instantiation_test"] = True
                    results["summary"]["available_workers"] += 1
                    
                    # Tentar obter informações do engine
                    if hasattr(worker_instance, 'get_engine_info'):
                        engine_info = worker_instance.get_engine_info()
                        test_result["engine_info"] = engine_info
                    
                except Exception as e:
                    test_result["error"] = str(e)
                    results["summary"]["failed_workers"] += 1
            else:
                results["summary"]["failed_workers"] += 1
                if not available:
                    test_result["error"] = "Dependencies not available"
                elif not worker_class:
                    test_result["error"] = "Class could not be loaded"
            
            results["worker_tests"][worker_name] = test_result
        
        # Calcular estatísticas finais
        total = results["summary"]["total_workers"]
        available = results["summary"]["available_workers"]
        
        results["summary"]["success_rate"] = (available / total) * 100 if total > 0 else 0
        results["summary"]["status"] = "good" if available >= total * 0.8 else "degraded" if available > 0 else "critical"
        
    except Exception as e:
        logger.error(f"Worker availability testing failed: {e}")
        results["error"] = str(e)
        results["summary"]["status"] = "error"
    
    return results


def get_worker_class(worker_name: str) -> Optional[type]:
    """
    Retorna classe do worker pelo nome
    
    Args:
        worker_name: Nome do worker
        
    Returns:
        Classe do worker ou None se não disponível
    """
    worker_map = {
        "trocr": TrOCRWorker if TROCR_AVAILABLE else None,
        "surya": SuryaWorker if SURYA_AVAILABLE else None,
        "paddleocr": PaddleOCRWorker if PADDLEOCR_AVAILABLE else None,
        "easyocr": EasyOCRWorker if EASYOCR_AVAILABLE else None,
        "tesseract": TesseractWorker if TESSERACT_AVAILABLE else None,
        "marker": MarkerWorker if MARKER_AVAILABLE else None,
        "orchestrator": OrchestratorWorker
    }
    
    return worker_map.get(worker_name.lower())


def get_worker_task(worker_name: str):
    """
    Retorna task Celery do worker pelo nome
    
    Args:
        worker_name: Nome do worker
        
    Returns:
        Task Celery ou None se não disponível
    """
    task_map = {
        "trocr": trocr_process_image if TROCR_AVAILABLE else None,
        "surya": surya_process_image if SURYA_AVAILABLE else None,
        "paddleocr": paddleocr_process_image if PADDLEOCR_AVAILABLE else None,
        "easyocr": easyocr_process_image if EASYOCR_AVAILABLE else None,
        "tesseract": tesseract_process_image if TESSERACT_AVAILABLE else None,
        "marker": marker_process_pdf if MARKER_AVAILABLE else None,
        "orchestrator": orchestrate_ocr_task
    }
    
    return task_map.get(worker_name.lower())


def get_worker_health_check(worker_name: str):
    """
    Retorna função de health check do worker pelo nome
    
    Args:
        worker_name: Nome do worker
        
    Returns:
        Função de health check ou None se não disponível
    """
    health_check_map = {
        "trocr": trocr_health_check if TROCR_AVAILABLE else None,
        "surya": surya_health_check if SURYA_AVAILABLE else None,
        "paddleocr": paddleocr_health_check if PADDLEOCR_AVAILABLE else None,
        "easyocr": easyocr_health_check if EASYOCR_AVAILABLE else None,
        "tesseract": tesseract_health_check if TESSERACT_AVAILABLE else None,
        "marker": marker_health_check if MARKER_AVAILABLE else None,
        "orchestrator": orchestrator_health_check
    }
    
    return health_check_map.get(worker_name.lower())


# Inicialização do módulo
logger.info(f"OCR Platform Workers v{__version__} - Loading...")

try:
    # Verificar workers disponíveis
    available_workers = get_available_workers()
    total_workers = 7  # Total implementado
    
    logger.info(f"Workers loaded: {len(available_workers)}/{total_workers} available")
    
    for worker in available_workers:
        logger.info(f"✅ {worker.upper()} worker available")
    
    # Log de workers não disponíveis
    all_workers = ["trocr", "surya", "paddleocr", "easyocr", "tesseract", "marker", "orchestrator"]
    unavailable_workers = [w for w in all_workers if w not in available_workers]
    
    for worker in unavailable_workers:
        logger.warning(f"❌ {worker.upper()} worker not available")
    
    # Status geral
    if len(available_workers) == total_workers:
        logger.info("🌟 All workers loaded successfully")
    elif len(available_workers) >= total_workers * 0.5:
        logger.warning(f"⚠️  Partial worker availability ({len(available_workers)}/{total_workers})")
    else:
        logger.error(f"❌ Critical: Low worker availability ({len(available_workers)}/{total_workers})")
    
    # Verificar se pelo menos um worker de OCR está disponível
    ocr_workers = [w for w in available_workers if w != "orchestrator"]
    if len(ocr_workers) == 0:
        logger.error("❌ CRITICAL: No OCR workers available! System may not function properly.")
    else:
        logger.info(f"✅ {len(ocr_workers)} OCR workers available for processing")

except Exception as e:
    logger.error(f"❌ Critical error during workers initialization: {e}")
    # Não propagar a exceção para não quebrar a importação do módulo

# Log de configuração adicional
try:
    from app.core.config import settings
    
    # Verificar configuração de GPU
    gpu_workers = ["trocr", "surya", "marker"]
    gpu_available_workers = [w for w in gpu_workers if w in available_workers]
    
    if gpu_available_workers and not getattr(settings, 'GPU_ENABLED', True):
        logger.warning("⚠️  GPU workers available but GPU processing disabled in config")
    elif gpu_available_workers:
        logger.info(f"🎮 GPU workers available: {', '.join(gpu_available_workers)}")
    
except ImportError:
    logger.debug("Config not available during workers initialization")