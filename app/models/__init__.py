#!/usr/bin/env python3
"""
Inicialização dos Modelos
=========================

Módulo de modelos da OCR Platform que exporta:
- Schemas Pydantic para validação
- Modelos de dados principais
- Enums e tipos customizados
- Factories para criação de objetos
"""

# Importar todos os schemas e modelos principais
from .schemas import (
    # Enums
    TaskStatus,
    OCREngine,
    OutputFormat,
    FileCategory,
    
    # Modelos base
    BoundingBox,
    TextBlock,
    LayoutElement,
    OCRStatistics,
    FileInfo,
    
    # Modelos de request
    OCRParameters,
    OCRRequest,
    BatchOCRRequest,
    
    # Modelos de response
    OCRResponse,
    BatchOCRResponse,
    
    # Modelos de task
    TaskInfo,
    QueueStatus,
    SystemHealth,
    
    # Modelos de configuração
    EngineConfig,
    QueueConfig,
    
    # Modelos de saúde e erro
    HealthCheckResponse,
    ErrorResponse,
    
    # Factories
    create_ocr_request,
    create_error_response,
    
    # Validadores
    validate_language_list,
    validate_page_range
)

# Versão dos modelos
__version__ = "2.0.0"

# Exportar tudo
__all__ = [
    # Enums
    'TaskStatus',
    'OCREngine', 
    'OutputFormat',
    'FileCategory',
    
    # Modelos base
    'BoundingBox',
    'TextBlock',
    'LayoutElement', 
    'OCRStatistics',
    'FileInfo',
    
    # Modelos de request
    'OCRParameters',
    'OCRRequest',
    'BatchOCRRequest',
    
    # Modelos de response
    'OCRResponse',
    'BatchOCRResponse',
    
    # Modelos de task
    'TaskInfo',
    'QueueStatus',
    'SystemHealth',
    
    # Modelos de configuração
    'EngineConfig',
    'QueueConfig',
    
    # Modelos de saúde e erro
    'HealthCheckResponse',
    'ErrorResponse',
    
    # Factories
    'create_ocr_request',
    'create_error_response',
    
    # Validadores
    'validate_language_list',
    'validate_page_range',
    
    # Constantes úteis
    'DEFAULT_OCR_PARAMETERS',
    'SUPPORTED_FILE_EXTENSIONS',
    'ENGINE_PRIORITY_MAP'
]

# Constantes úteis
DEFAULT_OCR_PARAMETERS = {
    "languages": ["pt", "en"],
    "output_format": OutputFormat.TEXT,
    "min_confidence": 0.0,
    "enhance_contrast": False,
    "use_cache": True,
    "timeout": 300
}

SUPPORTED_FILE_EXTENSIONS = [
    # Imagens
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp",
    # PDFs
    ".pdf",
    # Office
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Texto
    ".txt", ".html", ".htm", ".xml",
    # Arquivos
    ".zip"
]

ENGINE_PRIORITY_MAP = {
    "handwritten": ["trocr", "surya", "easyocr"],
    "printed": ["paddleocr", "tesseract", "easyocr"],
    "complex_layout": ["surya", "paddleocr", "easyocr"],
    "pdf_to_markdown": ["marker", "surya"],
    "fast_processing": ["paddleocr", "easyocr", "tesseract"],
    "high_accuracy": ["trocr", "surya", "paddleocr"],
    "general": ["easyocr", "paddleocr", "tesseract"]
}

# Funções utilitárias
def get_recommended_engine(text_type: str, priority: str = "accuracy") -> str:
    """
    Retorna engine recomendado baseado no tipo de texto e prioridade
    
    Args:
        text_type: Tipo de texto (handwritten, printed, complex_layout, etc.)
        priority: Prioridade (accuracy, speed, general)
        
    Returns:
        Nome do engine recomendado
    """
    if text_type in ENGINE_PRIORITY_MAP:
        engines = ENGINE_PRIORITY_MAP[text_type]
        
        if priority == "speed" and "paddleocr" in engines:
            return "paddleocr"
        elif priority == "accuracy" and engines:
            return engines[0]
        elif engines:
            return engines[0]
    
    return OCREngine.AUTO


def validate_ocr_request(request_dict: dict) -> tuple[bool, str]:
    """
    Valida dados de request OCR
    
    Args:
        request_dict: Dicionário com dados da request
        
    Returns:
        Tuple (is_valid, error_message)
    """
    try:
        # Validar campos obrigatórios
        if "file_path" not in request_dict:
            return False, "file_path is required"
        
        if not request_dict["file_path"]:
            return False, "file_path cannot be empty"
        
        # Validar engine
        engine = request_dict.get("engine", OCREngine.AUTO)
        if engine not in [e.value for e in OCREngine]:
            return False, f"Invalid engine: {engine}"
        
        # Validar parâmetros se presentes
        if "parameters" in request_dict:
            params = request_dict["parameters"]
            
            # Validar idiomas
            if "languages" in params and params["languages"]:
                validated_langs = validate_language_list(params["languages"])
                if not validated_langs:
                    return False, "No valid languages provided"
            
            # Validar confiança mínima
            if "min_confidence" in params:
                conf = params["min_confidence"]
                if not isinstance(conf, (int, float)) or conf < 0 or conf > 1:
                    return False, "min_confidence must be between 0 and 1"
            
            # Validar timeout
            if "timeout" in params:
                timeout = params["timeout"]
                if not isinstance(timeout, int) or timeout < 1:
                    return False, "timeout must be a positive integer"
        
        return True, ""
        
    except Exception as e:
        return False, f"Validation error: {str(e)}"


def create_default_ocr_request(file_path: str, **overrides) -> OCRRequest:
    """
    Cria request OCR com parâmetros padrão
    
    Args:
        file_path: Caminho do arquivo
        **overrides: Parâmetros para sobrescrever padrões
        
    Returns:
        OCRRequest configurado
    """
    params = DEFAULT_OCR_PARAMETERS.copy()
    params.update(overrides)
    
    return create_ocr_request(file_path, **params)


def get_file_category_from_extension(filename: str) -> FileCategory:
    """
    Determina categoria do arquivo baseado na extensão
    
    Args:
        filename: Nome do arquivo
        
    Returns:
        FileCategory correspondente
    """
    from pathlib import Path
    
    ext = Path(filename).suffix.lower()
    
    if ext in [".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"]:
        return FileCategory.IMAGE
    elif ext == ".pdf":
        return FileCategory.PDF
    elif ext in [".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"]:
        return FileCategory.OFFICE
    elif ext in [".txt", ".html", ".htm", ".xml", ".csv"]:
        return FileCategory.TEXT
    elif ext in [".zip", ".rar", ".7z"]:
        return FileCategory.ARCHIVE
    else:
        return FileCategory.UNKNOWN


def estimate_processing_time(file_size: int, engine: str, complexity: str = "medium") -> float:
    """
    Estima tempo de processamento baseado no arquivo e engine
    
    Args:
        file_size: Tamanho do arquivo em bytes
        engine: Engine OCR
        complexity: Complexidade do documento (low, medium, high)
        
    Returns:
        Tempo estimado em segundos
    """
    # Tempos base por engine (segundos por MB)
    engine_speeds = {
        "tesseract": 2.0,
        "paddleocr": 3.0,
        "easyocr": 5.0,
        "surya": 8.0,
        "trocr": 15.0,
        "marker": 10.0
    }
    
    # Multiplicadores por complexidade
    complexity_multipliers = {
        "low": 0.7,
        "medium": 1.0,
        "high": 1.5
    }
    
    # Calcular tempo base
    file_size_mb = file_size / (1024 * 1024)
    base_speed = engine_speeds.get(engine, 5.0)
    complexity_mult = complexity_multipliers.get(complexity, 1.0)
    
    estimated_time = file_size_mb * base_speed * complexity_mult
    
    # Tempo mínimo e máximo
    return max(5.0, min(300.0, estimated_time))


# Informações do módulo
def get_models_info() -> dict:
    """Retorna informações sobre os modelos disponíveis"""
    return {
        "version": __version__,
        "total_models": len(__all__),
        "enums": [
            "TaskStatus", "OCREngine", "OutputFormat", "FileCategory"
        ],
        "base_models": [
            "BoundingBox", "TextBlock", "LayoutElement", "OCRStatistics", "FileInfo"
        ],
        "request_models": [
            "OCRParameters", "OCRRequest", "BatchOCRRequest"
        ],
        "response_models": [
            "OCRResponse", "BatchOCRResponse"
        ],
        "utility_functions": [
            "get_recommended_engine", "validate_ocr_request", 
            "create_default_ocr_request", "estimate_processing_time"
        ],
        "supported_engines": [e.value for e in OCREngine],
        "supported_formats": [f.value for f in OutputFormat],
        "file_categories": [c.value for c in FileCategory]
    }


if __name__ == "__main__":
    """Teste do módulo de modelos"""
    print("=== OCR Models Module Test ===")
    
    # Informações do módulo
    info = get_models_info()
    print(f"Models version: {info['version']}")
    print(f"Total models: {info['total_models']}")
    print(f"Supported engines: {info['supported_engines']}")
    
    # Teste de validação
    valid_request = {
        "file_path": "/test/file.jpg",
        "engine": "paddleocr",
        "parameters": {
            "languages": ["pt", "en"],
            "min_confidence": 0.5
        }
    }
    
    is_valid, error = validate_ocr_request(valid_request)
    print(f"Request validation: {'✅ Valid' if is_valid else f'❌ Invalid: {error}'}")
    
    # Teste de recomendação de engine
    recommended = get_recommended_engine("handwritten", "accuracy")
    print(f"Recommended engine for handwritten text: {recommended}")
    
    # Teste de estimativa de tempo
    estimated_time = estimate_processing_time(1024*1024, "paddleocr", "medium")  # 1MB
    print(f"Estimated processing time: {estimated_time:.1f}s")
    
    print("\n✅ Models module test completed")