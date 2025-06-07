#!/usr/bin/env python3
"""
Modelos Pydantic para OCR Platform
==================================

Define estruturas de dados para:
- Requests e responses da API
- Modelos de tasks
- Validação de dados
- Serialização/deserialização
"""

from typing import Dict, Any, List, Optional, Union
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field, validator, root_validator
import uuid


class TaskStatus(str, Enum):
    """Status possíveis de uma task"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class OCREngine(str, Enum):
    """Engines OCR disponíveis"""
    AUTO = "auto"
    TROCR = "trocr"
    SURYA = "surya"
    PADDLEOCR = "paddleocr"
    EASYOCR = "easyocr"
    TESSERACT = "tesseract"
    MARKER = "marker"


class OutputFormat(str, Enum):
    """Formatos de saída suportados"""
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    HTML = "html"


class FileCategory(str, Enum):
    """Categorias de arquivo suportadas"""
    IMAGE = "image"
    PDF = "pdf"
    OFFICE = "office"
    TEXT = "text"
    ARCHIVE = "archive"
    UNKNOWN = "unknown"


# === MODELOS BASE ===

class BoundingBox(BaseModel):
    """Modelo para bounding box"""
    x0: float = Field(..., description="Coordenada X inicial")
    y0: float = Field(..., description="Coordenada Y inicial")
    x1: float = Field(..., description="Coordenada X final")
    y1: float = Field(..., description="Coordenada Y final")
    
    @validator('x1')
    def x1_must_be_greater_than_x0(cls, v, values):
        if 'x0' in values and v <= values['x0']:
            raise ValueError('x1 must be greater than x0')
        return v
    
    @validator('y1')
    def y1_must_be_greater_than_y0(cls, v, values):
        if 'y0' in values and v <= values['y0']:
            raise ValueError('y1 must be greater than y0')
        return v
    
    @property
    def width(self) -> float:
        return self.x1 - self.x0
    
    @property
    def height(self) -> float:
        return self.y1 - self.y0
    
    @property
    def area(self) -> float:
        return self.width * self.height
    
    @property
    def center(self) -> tuple:
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)


class TextBlock(BaseModel):
    """Modelo para bloco de texto detectado"""
    text: str = Field(..., description="Texto detectado")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confiança da detecção")
    bbox: Optional[Union[BoundingBox, List[float]]] = Field(None, description="Bounding box do texto")
    bbox_points: Optional[List[List[float]]] = Field(None, description="Pontos da bounding box")
    type: Optional[str] = Field("text", description="Tipo do bloco")
    language: Optional[str] = Field(None, description="Idioma detectado")
    
    @validator('bbox', pre=True)
    def validate_bbox(cls, v):
        if isinstance(v, list) and len(v) == 4:
            return BoundingBox(x0=v[0], y0=v[1], x1=v[2], y1=v[3])
        return v


class LayoutElement(BaseModel):
    """Modelo para elemento de layout"""
    type: str = Field(..., description="Tipo do elemento (header, paragraph, table, etc.)")
    bbox: Union[BoundingBox, List[float]] = Field(..., description="Bounding box do elemento")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confiança da detecção")
    order: Optional[int] = Field(None, description="Ordem de leitura")
    
    @validator('bbox', pre=True)
    def validate_bbox(cls, v):
        if isinstance(v, list) and len(v) == 4:
            return BoundingBox(x0=v[0], y0=v[1], x1=v[2], y1=v[3])
        return v


class OCRStatistics(BaseModel):
    """Estatísticas do processamento OCR"""
    total_blocks: int = Field(0, ge=0, description="Total de blocos detectados")
    avg_confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confiança média")
    min_confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confiança mínima")
    max_confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confiança máxima")
    char_count: int = Field(0, ge=0, description="Número de caracteres")
    word_count: int = Field(0, ge=0, description="Número de palavras")
    line_count: Optional[int] = Field(None, ge=0, description="Número de linhas")
    processing_time: Optional[float] = Field(None, ge=0.0, description="Tempo de processamento")


class FileInfo(BaseModel):
    """Informações do arquivo"""
    filename: str = Field(..., description="Nome do arquivo")
    file_size: int = Field(..., ge=0, description="Tamanho do arquivo em bytes")
    mime_type: Optional[str] = Field(None, description="MIME type do arquivo")
    extension: Optional[str] = Field(None, description="Extensão do arquivo")
    category: FileCategory = Field(FileCategory.UNKNOWN, description="Categoria do arquivo")
    supported: bool = Field(True, description="Se o arquivo é suportado")


# === MODELOS DE REQUEST ===

class OCRParameters(BaseModel):
    """Parâmetros para processamento OCR"""
    # Parâmetros gerais
    languages: Optional[List[str]] = Field(None, description="Lista de idiomas")
    output_format: OutputFormat = Field(OutputFormat.TEXT, description="Formato de saída")
    min_confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confiança mínima")
    
    # Parâmetros de pré-processamento
    enhance_contrast: bool = Field(False, description="Melhorar contraste")
    enhance_brightness: bool = Field(False, description="Melhorar brilho")
    denoise: bool = Field(False, description="Remover ruído")
    deskew: bool = Field(False, description="Corrigir inclinação")
    target_height: Optional[int] = Field(None, gt=0, description="Altura alvo")
    max_size: int = Field(2048, gt=0, description="Tamanho máximo")
    
    # Parâmetros específicos por engine
    # TrOCR
    segment_lines: bool = Field(True, description="Segmentar linhas (TrOCR)")
    max_length: int = Field(384, gt=0, description="Tamanho máximo de tokens (TrOCR)")
    
    # Surya
    analyze_layout: bool = Field(True, description="Analisar layout (Surya)")
    reading_order: bool = Field(True, description="Detectar ordem de leitura (Surya)")
    organize_by_layout: bool = Field(True, description="Organizar por layout (Surya)")
    
    # PaddleOCR
    detect_structure: bool = Field(True, description="Detectar estrutura (PaddleOCR)")
    detect_columns: bool = Field(True, description="Detectar colunas (PaddleOCR)")
    
    # EasyOCR
    detail_mode: bool = Field(True, description="Modo detalhado (EasyOCR)")
    width_threshold: float = Field(0.7, ge=0.0, le=1.0, description="Threshold largura (EasyOCR)")
    height_threshold: float = Field(0.7, ge=0.0, le=1.0, description="Threshold altura (EasyOCR)")
    
    # Tesseract
    psm: int = Field(6, ge=0, le=13, description="Page segmentation mode (Tesseract)")
    oem: int = Field(3, ge=0, le=3, description="OCR engine mode (Tesseract)")
    
    # Marker
    extract_images: bool = Field(True, description="Extrair imagens (Marker)")
    use_llm: bool = Field(False, description="Usar LLM (Marker)")
    max_pages: Optional[int] = Field(None, gt=0, description="Número máximo de páginas")
    page_range: Optional[str] = Field(None, description="Range de páginas (ex: '1,3-5,10')")
    
    # Cache e performance
    use_cache: bool = Field(True, description="Usar cache")
    timeout: int = Field(300, gt=0, description="Timeout em segundos")


class OCRRequest(BaseModel):
    """Request para processamento OCR"""
    file_path: str = Field(..., description="Caminho do arquivo")
    engine: OCREngine = Field(OCREngine.AUTO, description="Engine OCR a usar")
    parameters: OCRParameters = Field(default_factory=OCRParameters, description="Parâmetros")
    task_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), description="ID da task")
    priority: int = Field(5, ge=1, le=10, description="Prioridade da task")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados adicionais")
    
    @validator('file_path')
    def validate_file_path(cls, v):
        if not v.strip():
            raise ValueError('file_path cannot be empty')
        return v


class BatchOCRRequest(BaseModel):
    """Request para processamento em lote"""
    file_paths: List[str] = Field(..., min_items=1, description="Lista de caminhos de arquivo")
    engine: OCREngine = Field(OCREngine.AUTO, description="Engine OCR a usar")
    parameters: OCRParameters = Field(default_factory=OCRParameters, description="Parâmetros")
    batch_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()), description="ID do lote")
    priority: int = Field(5, ge=1, le=10, description="Prioridade das tasks")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados adicionais")


# === MODELOS DE RESPONSE ===

class OCRResponse(BaseModel):
    """Response do processamento OCR"""
    # Resultados principais
    text: str = Field("", description="Texto extraído")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confiança geral")
    blocks: List[TextBlock] = Field(default_factory=list, description="Blocos de texto")
    
    # Resultados específicos
    markdown: Optional[str] = Field(None, description="Texto em formato Markdown")
    html: Optional[str] = Field(None, description="Texto em formato HTML")
    json_data: Optional[Dict[str, Any]] = Field(None, description="Dados estruturados")
    
    # Layout e estrutura
    layout: Optional[List[LayoutElement]] = Field(None, description="Elementos de layout")
    reading_order: Optional[List[Dict[str, Any]]] = Field(None, description="Ordem de leitura")
    structure: Optional[Dict[str, Any]] = Field(None, description="Estrutura do documento")
    
    # Metadados
    engine: str = Field("", description="Engine usado")
    processing_time: float = Field(0.0, ge=0.0, description="Tempo de processamento")
    statistics: OCRStatistics = Field(default_factory=OCRStatistics, description="Estatísticas")
    file_info: Optional[FileInfo] = Field(None, description="Informações do arquivo")
    
    # Informações técnicas
    strategy: Optional[str] = Field(None, description="Estratégia usada")
    quality_score: Optional[float] = Field(None, ge=0.0, le=10.0, description="Score de qualidade")
    warnings: List[str] = Field(default_factory=list, description="Avisos")
    
    # Timestamp
    timestamp: datetime = Field(default_factory=datetime.now, description="Timestamp do processamento")


class BatchOCRResponse(BaseModel):
    """Response do processamento em lote"""
    batch_id: str = Field(..., description="ID do lote")
    total_files: int = Field(..., ge=0, description="Total de arquivos")
    processed_files: int = Field(..., ge=0, description="Arquivos processados")
    failed_files: int = Field(..., ge=0, description="Arquivos que falharam")
    results: List[OCRResponse] = Field(..., description="Resultados individuais")
    summary: Dict[str, Any] = Field(..., description="Resumo do lote")
    total_processing_time: float = Field(..., ge=0.0, description="Tempo total de processamento")


# === MODELOS DE TASK ===

class TaskInfo(BaseModel):
    """Informações de uma task"""
    task_id: str = Field(..., description="ID da task")
    status: TaskStatus = Field(..., description="Status da task")
    engine: str = Field(..., description="Engine usado")
    queue: str = Field(..., description="Fila da task")
    priority: int = Field(..., ge=1, le=10, description="Prioridade")
    
    # Timestamps
    created_at: datetime = Field(..., description="Timestamp de criação")
    started_at: Optional[datetime] = Field(None, description="Timestamp de início")
    completed_at: Optional[datetime] = Field(None, description="Timestamp de conclusão")
    
    # Informações de progresso
    progress: float = Field(0.0, ge=0.0, le=1.0, description="Progresso da task")
    estimated_time: Optional[float] = Field(None, ge=0.0, description="Tempo estimado")
    
    # Resultado ou erro
    result: Optional[OCRResponse] = Field(None, description="Resultado da task")
    error: Optional[str] = Field(None, description="Mensagem de erro")
    
    # Worker info
    worker_name: Optional[str] = Field(None, description="Nome do worker")
    retries: int = Field(0, ge=0, description="Número de tentativas")


class QueueStatus(BaseModel):
    """Status de uma fila"""
    queue_name: str = Field(..., description="Nome da fila")
    pending_tasks: int = Field(..., ge=0, description="Tasks pendentes")
    active_tasks: int = Field(..., ge=0, description="Tasks ativas")
    completed_tasks: int = Field(..., ge=0, description="Tasks completadas")
    failed_tasks: int = Field(..., ge=0, description="Tasks falhadas")
    
    # Performance
    avg_processing_time: float = Field(0.0, ge=0.0, description="Tempo médio de processamento")
    throughput: float = Field(0.0, ge=0.0, description="Tasks por minuto")
    
    # Workers
    active_workers: int = Field(0, ge=0, description="Workers ativos")
    max_workers: int = Field(1, ge=1, description="Máximo de workers")


class SystemHealth(BaseModel):
    """Saúde do sistema"""
    status: str = Field(..., description="Status geral")
    timestamp: datetime = Field(default_factory=datetime.now, description="Timestamp")
    
    # Services
    api_status: str = Field("unknown", description="Status da API")
    redis_status: str = Field("unknown", description="Status do Redis")
    celery_status: str = Field("unknown", description="Status do Celery")
    
    # Engines
    available_engines: List[str] = Field(default_factory=list, description="Engines disponíveis")
    engine_health: Dict[str, str] = Field(default_factory=dict, description="Saúde dos engines")
    
    # Queues
    queue_status: List[QueueStatus] = Field(default_factory=list, description="Status das filas")
    
    # Performance
    total_tasks_today: int = Field(0, ge=0, description="Total de tasks hoje")
    avg_response_time: float = Field(0.0, ge=0.0, description="Tempo médio de resposta")
    error_rate: float = Field(0.0, ge=0.0, le=1.0, description="Taxa de erro")


# === MODELOS DE CONFIGURAÇÃO ===

class EngineConfig(BaseModel):
    """Configuração de um engine"""
    name: str = Field(..., description="Nome do engine")
    enabled: bool = Field(True, description="Se está habilitado")
    max_workers: int = Field(1, ge=1, description="Máximo de workers")
    gpu_required: bool = Field(False, description="Se requer GPU")
    memory_required: float = Field(0.0, ge=0.0, description="Memória requerida (GB)")
    use_cases: List[str] = Field(default_factory=list, description="Casos de uso")
    accuracy_rating: float = Field(0.0, ge=0.0, le=10.0, description="Rating de precisão")


class QueueConfig(BaseModel):
    """Configuração de uma fila"""
    name: str = Field(..., description="Nome da fila")
    routing_key: str = Field(..., description="Chave de roteamento")
    priority: int = Field(5, ge=1, le=10, description="Prioridade da fila")
    max_workers: int = Field(1, ge=1, description="Máximo de workers")
    description: str = Field("", description="Descrição da fila")


# === VALIDAÇÕES CUSTOMIZADAS ===

class HealthCheckResponse(BaseModel):
    """Response do health check"""
    status: str = Field(..., description="Status da saúde")
    timestamp: datetime = Field(default_factory=datetime.now, description="Timestamp")
    version: str = Field(..., description="Versão do sistema")
    uptime: float = Field(..., ge=0.0, description="Tempo de execução")
    checks: Dict[str, bool] = Field(..., description="Resultados dos checks")
    details: Dict[str, Any] = Field(default_factory=dict, description="Detalhes adicionais")


class ErrorResponse(BaseModel):
    """Response de erro padronizado"""
    error: bool = Field(True, description="Indica que é um erro")
    message: str = Field(..., description="Mensagem de erro")
    error_code: Optional[str] = Field(None, description="Código de erro")
    details: Optional[Dict[str, Any]] = Field(None, description="Detalhes do erro")
    timestamp: datetime = Field(default_factory=datetime.now, description="Timestamp")
    request_id: Optional[str] = Field(None, description="ID da requisição")


# === VALIDADORES ESPECÍFICOS ===

def validate_language_list(languages: List[str]) -> List[str]:
    """Valida lista de idiomas"""
    valid_languages = {
        'pt', 'en', 'es', 'fr', 'de', 'it', 'ru', 'ja', 'ko', 'zh', 
        'ar', 'hi', 'th', 'vi', 'tr', 'pl', 'nl', 'sv', 'da', 'no'
    }
    
    validated = []
    for lang in languages:
        if lang.lower() in valid_languages:
            validated.append(lang.lower())
    
    return validated if validated else ['en']  # Default to English


def validate_page_range(page_range: str) -> bool:
    """Valida formato de range de páginas"""
    import re
    pattern = r'^(\d+(-\d+)?)(,\d+(-\d+)?)*$'
    return bool(re.match(pattern, page_range.replace(' ', '')))


# === FACTORY FUNCTIONS ===

def create_ocr_request(file_path: str, **kwargs) -> OCRRequest:
    """Factory para criar OCRRequest"""
    parameters = OCRParameters(**{k: v for k, v in kwargs.items() if k in OCRParameters.__fields__})
    
    request_kwargs = {k: v for k, v in kwargs.items() if k in OCRRequest.__fields__}
    request_kwargs['file_path'] = file_path
    request_kwargs['parameters'] = parameters
    
    return OCRRequest(**request_kwargs)


def create_error_response(message: str, error_code: str = None, **kwargs) -> ErrorResponse:
    """Factory para criar ErrorResponse"""
    return ErrorResponse(
        message=message,
        error_code=error_code,
        details=kwargs.get('details'),
        request_id=kwargs.get('request_id')
    )


if __name__ == "__main__":
    """Teste dos modelos"""
    print("=== OCR Platform Models Test ===")
    
    # Teste OCRRequest
    request = create_ocr_request(
        "test.jpg",
        engine="trocr",
        languages=["pt", "en"],
        enhance_contrast=True,
        min_confidence=0.5
    )
    print(f"Request created: {request.engine} with {len(request.parameters.languages or [])} languages")
    
    # Teste OCRResponse
    response = OCRResponse(
        text="Texto de exemplo",
        confidence=0.95,
        engine="trocr",
        processing_time=2.5
    )
    print(f"Response created: {len(response.text)} chars, confidence {response.confidence}")
    
    # Teste validação
    try:
        # Teste com confidence inválida
        invalid_response = OCRResponse(
            text="Test",
            confidence=1.5,  # Inválido
            engine="test"
        )
    except Exception as e:
        print(f"✅ Validation working: {type(e).__name__}")
    
    # Teste BoundingBox
    bbox = BoundingBox(x0=10, y0=20, x1=100, y1=80)
    print(f"BoundingBox: {bbox.width}x{bbox.height}, area={bbox.area}")
    
    print("\n✅ Models test completed")