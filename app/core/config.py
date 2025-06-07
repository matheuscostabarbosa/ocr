#!/usr/bin/env python3
"""
Configuração Central do Sistema OCR
===================================

Gerencia todas as configurações do sistema incluindo:
- Configurações de Redis e Celery
- Configurações de workers
- Configurações de storage
- Configurações de segurança
"""

import os
from typing import Dict, List, Optional
from pydantic import BaseSettings, validator
from pathlib import Path


class Settings(BaseSettings):
    """Configurações principais do sistema"""
    
    # === CONFIGURAÇÕES BÁSICAS ===
    PROJECT_NAME: str = "OCR Platform"
    VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development, staging, production
    
    # === API CONFIGURATION ===
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    API_WORKERS: int = 4
    API_PREFIX: str = "/api/v1"
    
    # === REDIS CONFIGURATION ===
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    REDIS_URL: Optional[str] = None
    
    @validator('REDIS_URL', pre=True, always=True)
    def build_redis_url(cls, v, values):
        if v:
            return v
        
        password_part = f":{values['REDIS_PASSWORD']}@" if values.get('REDIS_PASSWORD') else ""
        return f"redis://{password_part}{values['REDIS_HOST']}:{values['REDIS_PORT']}/{values['REDIS_DB']}"
    
    # === CELERY CONFIGURATION ===
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: List[str] = ["json"]
    CELERY_TIMEZONE: str = "UTC"
    CELERY_ENABLE_UTC: bool = True
    
    @validator('CELERY_BROKER_URL', pre=True, always=True)
    def build_celery_broker_url(cls, v, values):
        return v or values.get('REDIS_URL')
    
    @validator('CELERY_RESULT_BACKEND', pre=True, always=True)
    def build_celery_result_backend(cls, v, values):
        return v or values.get('REDIS_URL')
    
    # === QUEUE CONFIGURATION ===
    QUEUE_CONFIG: Dict[str, Dict] = {
        "trocr_queue": {
            "name": "trocr_queue",
            "routing_key": "trocr",
            "priority": 8,  # Alta prioridade para manuscritos
            "max_workers": 2,  # GPU intensive
            "gpu_required": True,
            "description": "TrOCR worker para manuscritos e textos complexos"
        },
        "surya_queue": {
            "name": "surya_queue", 
            "routing_key": "surya",
            "priority": 7,
            "max_workers": 3,
            "gpu_required": True,
            "description": "Surya OCR para layout complexo e análise estrutural"
        },
        "paddleocr_queue": {
            "name": "paddleocr_queue",
            "routing_key": "paddleocr", 
            "priority": 6,
            "max_workers": 8,  # Rápido, pode ter mais workers
            "gpu_required": False,
            "description": "PaddleOCR para processamento rápido em produção"
        },
        "easyocr_queue": {
            "name": "easyocr_queue",
            "routing_key": "easyocr",
            "priority": 5,
            "max_workers": 6,
            "gpu_required": False, 
            "description": "EasyOCR para uso geral e múltiplos idiomas"
        },
        "tesseract_queue": {
            "name": "tesseract_queue",
            "routing_key": "tesseract",
            "priority": 4,
            "max_workers": 10,  # CPU only, muito rápido
            "gpu_required": False,
            "description": "Tesseract para texto simples e fallback"
        },
        "marker_queue": {
            "name": "marker_queue",
            "routing_key": "marker", 
            "priority": 7,
            "max_workers": 4,
            "gpu_required": True,
            "description": "Marker para conversão PDF→Markdown"
        },
        "orchestrator_queue": {
            "name": "orchestrator_queue",
            "routing_key": "orchestrator",
            "priority": 9,  # Máxima prioridade
            "max_workers": 4,
            "gpu_required": False,
            "description": "Orquestração e roteamento de tasks"
        },
        "postprocess_queue": {
            "name": "postprocess_queue",
            "routing_key": "postprocess", 
            "priority": 3,
            "max_workers": 6,
            "gpu_required": False,
            "description": "Pós-processamento e agregação de resultados"
        }
    }
    
    # === ENGINE CONFIGURATION ===
    ENGINES_CONFIG: Dict[str, Dict] = {
        "trocr": {
            "enabled": True,
            "model_name": "microsoft/trocr-large-handwritten",
            "use_cases": ["handwritten", "complex_text", "poor_quality"],
            "gpu_memory_required": 4,  # GB
            "avg_processing_time": 3.0,  # seconds
            "accuracy_rating": 9.5
        },
        "surya": {
            "enabled": True,
            "models": {
                "detection": "surya_det",
                "recognition": "surya_rec", 
                "layout": "surya_layout"
            },
            "use_cases": ["layout_analysis", "structured_documents", "tables"],
            "gpu_memory_required": 6,  # GB
            "avg_processing_time": 0.13,
            "accuracy_rating": 9.7
        },
        "paddleocr": {
            "enabled": True,
            "lang": "pt",
            "use_angle_cls": True,
            "use_cases": ["production", "fast_processing", "general"],
            "gpu_memory_required": 2,  # GB (optional)
            "avg_processing_time": 0.5,
            "accuracy_rating": 8.5
        },
        "easyocr": {
            "enabled": True,
            "languages": ["pt", "en"],
            "use_cases": ["general", "multilingual", "simple"],
            "gpu_memory_required": 2,  # GB (optional)
            "avg_processing_time": 1.0,
            "accuracy_rating": 8.0
        },
        "tesseract": {
            "enabled": True,
            "lang": "por+eng",
            "config": "--oem 3 --psm 6",
            "use_cases": ["fallback", "simple_text", "digital_documents"],
            "gpu_memory_required": 0,  # CPU only
            "avg_processing_time": 0.2,
            "accuracy_rating": 7.5
        },
        "marker": {
            "enabled": True,
            "use_cases": ["pdf_to_markdown", "academic_papers", "structured_pdf"],
            "gpu_memory_required": 3,  # GB
            "avg_processing_time": 2.0,
            "accuracy_rating": 9.0
        }
    }
    
    # === STORAGE CONFIGURATION ===
    STORAGE_TYPE: str = "local"  # local, s3, gcs
    UPLOAD_DIR: str = "uploads"
    RESULT_DIR: str = "results" 
    TEMP_DIR: str = "temp"
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS: List[str] = [
        ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp",
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".txt", ".html", ".htm", ".xml", ".zip"
    ]
    
    # === SECURITY CONFIGURATION ===
    SECRET_KEY: str = "your-secret-key-change-in-production"
    API_KEY_ENABLED: bool = False
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_CALLS: int = 100
    RATE_LIMIT_PERIOD: int = 3600  # 1 hour
    
    # === MONITORING CONFIGURATION ===
    FLOWER_ENABLED: bool = True
    FLOWER_PORT: int = 5555
    PROMETHEUS_ENABLED: bool = True
    PROMETHEUS_PORT: int = 9090
    LOG_LEVEL: str = "INFO"
    
    # === WORKER CONFIGURATION ===
    WORKER_PREFETCH_MULTIPLIER: int = 1
    WORKER_MAX_TASKS_PER_CHILD: int = 100
    WORKER_TASK_TIME_LIMIT: int = 300  # 5 minutes
    WORKER_TASK_SOFT_TIME_LIMIT: int = 240  # 4 minutes
    
    # === GPU CONFIGURATION ===
    GPU_ENABLED: bool = True
    GPU_MEMORY_FRACTION: float = 0.8
    CUDA_VISIBLE_DEVICES: Optional[str] = None
    
    # === DATABASE CONFIGURATION (opcional) ===
    DATABASE_ENABLED: bool = False
    DATABASE_URL: Optional[str] = None
    
    class Config:
        env_file = ".env"
        case_sensitive = True


class WorkerSettings(BaseSettings):
    """Configurações específicas para workers"""
    
    WORKER_TYPE: str = "base"
    WORKER_NAME: Optional[str] = None
    WORKER_CONCURRENCY: int = 1
    WORKER_LOGLEVEL: str = "INFO"
    WORKER_POOL: str = "prefork"  # prefork, eventlet, gevent
    WORKER_QUEUES: List[str] = []
    
    # Auto-scaling
    AUTOSCALE_MIN: int = 1
    AUTOSCALE_MAX: int = 4
    
    # Health check
    HEALTH_CHECK_INTERVAL: int = 30
    
    class Config:
        env_file = ".env"


class RedisSettings(BaseSettings):
    """Configurações específicas do Redis"""
    
    REDIS_MAX_CONNECTIONS: int = 100
    REDIS_RETRY_ON_TIMEOUT: bool = True
    REDIS_SOCKET_TIMEOUT: int = 5
    REDIS_SOCKET_CONNECT_TIMEOUT: int = 5
    REDIS_CONNECTION_POOL_KWARGS: Dict = {}
    
    # Key expiration
    TASK_RESULT_EXPIRES: int = 3600  # 1 hour
    CACHE_EXPIRES: int = 1800  # 30 minutes
    
    class Config:
        env_file = ".env"


# Instâncias globais
settings = Settings()
worker_settings = WorkerSettings()
redis_settings = RedisSettings()


def get_queue_config(queue_name: str) -> Dict:
    """Retorna configuração de uma fila específica"""
    return settings.QUEUE_CONFIG.get(queue_name, {})


def get_engine_config(engine_name: str) -> Dict:
    """Retorna configuração de um engine específico"""
    return settings.ENGINES_CONFIG.get(engine_name, {})


def is_engine_enabled(engine_name: str) -> bool:
    """Verifica se um engine está habilitado"""
    config = get_engine_config(engine_name)
    return config.get("enabled", False)


def get_available_engines() -> List[str]:
    """Retorna lista de engines disponíveis"""
    return [
        engine for engine, config in settings.ENGINES_CONFIG.items()
        if config.get("enabled", False)
    ]


def get_gpu_engines() -> List[str]:
    """Retorna engines que requerem GPU"""
    return [
        engine for engine, config in settings.ENGINES_CONFIG.items()
        if config.get("enabled", False) and config.get("gpu_memory_required", 0) > 0
    ]


def get_cpu_engines() -> List[str]:
    """Retorna engines que podem usar só CPU"""
    return [
        engine for engine, config in settings.ENGINES_CONFIG.items()
        if config.get("enabled", False) and config.get("gpu_memory_required", 0) == 0
    ]


def create_directories():
    """Cria diretórios necessários"""
    dirs = [
        settings.UPLOAD_DIR,
        settings.RESULT_DIR, 
        settings.TEMP_DIR
    ]
    
    for directory in dirs:
        Path(directory).mkdir(parents=True, exist_ok=True)


def validate_gpu_memory() -> Dict[str, bool]:
    """Valida se há memória GPU suficiente para os engines"""
    try:
        import torch
        if not torch.cuda.is_available():
            return {engine: False for engine in get_gpu_engines()}
        
        gpu_memory = torch.cuda.get_device_properties(0).total_memory / (1024**3)  # GB
        
        results = {}
        for engine in get_gpu_engines():
            config = get_engine_config(engine)
            required_memory = config.get("gpu_memory_required", 0)
            results[engine] = gpu_memory >= required_memory
            
        return results
        
    except ImportError:
        return {engine: False for engine in get_gpu_engines()}


if __name__ == "__main__":
    """Teste das configurações"""
    print("=== OCR Platform Configuration ===")
    print(f"Project: {settings.PROJECT_NAME} v{settings.VERSION}")
    print(f"Environment: {settings.ENVIRONMENT}")
    print(f"Redis URL: {settings.REDIS_URL}")
    print(f"Available Engines: {get_available_engines()}")
    print(f"GPU Engines: {get_gpu_engines()}")
    print(f"CPU Engines: {get_cpu_engines()}")
    
    # Teste de validação GPU
    gpu_status = validate_gpu_memory()
    print("GPU Status:")
    for engine, status in gpu_status.items():
        print(f"  {engine}: {'✅' if status else '❌'}")
        
    # Criar diretórios
    create_directories()
    print("✅ Directories created successfully")