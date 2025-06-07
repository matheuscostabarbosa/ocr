#!/usr/bin/env python3
"""
Modelos de Tasks OCR
===================

Modelos Pydantic específicos para tasks de processamento OCR:
- Estados e ciclo de vida de tasks
- Configurações de processamento
- Metadados de execução
- Filas e distribuição
- Monitoramento e métricas
"""

from typing import Dict, Any, List, Optional, Union
from datetime import datetime, timedelta
from enum import Enum
from pydantic import BaseModel, Field, validator, root_validator
import uuid

from .schemas import TaskStatus, OCREngine, OCRParameters


class TaskPriority(str, Enum):
    """Níveis de prioridade de tasks"""
    CRITICAL = "critical"    # 10
    HIGH = "high"           # 8-9
    NORMAL = "normal"       # 5-7
    LOW = "low"             # 3-4
    BACKGROUND = "background"  # 1-2


class TaskCategory(str, Enum):
    """Categorias de tasks"""
    SINGLE_DOCUMENT = "single_document"
    BATCH_PROCESSING = "batch_processing"
    PIPELINE_STAGE = "pipeline_stage"
    AGGREGATION = "aggregation"
    HEALTH_CHECK = "health_check"
    MAINTENANCE = "maintenance"


class ExecutionMode(str, Enum):
    """Modos de execução"""
    SYNCHRONOUS = "synchronous"
    ASYNCHRONOUS = "asynchronous"
    SCHEDULED = "scheduled"
    TRIGGERED = "triggered"


class RetryStrategy(str, Enum):
    """Estratégias de retry"""
    NONE = "none"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    CUSTOM = "custom"


# === MODELOS DE CONFIGURAÇÃO ===

class TaskConfiguration(BaseModel):
    """Configuração de uma task"""
    # Configurações básicas
    timeout: int = Field(300, gt=0, description="Timeout em segundos")
    max_retries: int = Field(3, ge=0, description="Número máximo de tentativas")
    retry_strategy: RetryStrategy = Field(RetryStrategy.EXPONENTIAL, description="Estratégia de retry")
    retry_delay: float = Field(5.0, ge=0.0, description="Delay inicial entre retries")
    
    # Recursos necessários
    memory_limit_mb: Optional[int] = Field(None, gt=0, description="Limite de memória em MB")
    cpu_limit: Optional[float] = Field(None, gt=0.0, description="Limite de CPU")
    gpu_required: bool = Field(False, description="Se requer GPU")
    gpu_memory_mb: Optional[int] = Field(None, gt=0, description="Memória GPU necessária em MB")
    
    # Configurações de execução
    execution_mode: ExecutionMode = Field(ExecutionMode.ASYNCHRONOUS, description="Modo de execução")
    queue_affinity: Optional[str] = Field(None, description="Afinidade de fila")
    worker_affinity: Optional[str] = Field(None, description="Afinidade de worker")
    
    # Configurações de cache
    cache_enabled: bool = Field(True, description="Se deve usar cache")
    cache_ttl: int = Field(3600, gt=0, description="TTL do cache em segundos")
    cache_key_prefix: Optional[str] = Field(None, description="Prefixo da chave de cache")
    
    # Configurações de monitoramento
    monitoring_enabled: bool = Field(True, description="Se deve monitorar")
    metrics_collection: bool = Field(True, description="Se deve coletar métricas")
    detailed_logging: bool = Field(False, description="Se deve fazer log detalhado")
    
    # Configurações de fallback
    fallback_enabled: bool = Field(True, description="Se deve usar fallback")
    fallback_engines: List[str] = Field(default_factory=list, description="Engines de fallback")
    
    def get_retry_delay(self, attempt: int) -> float:
        """Calcula delay para tentativa específica"""
        if self.retry_strategy == RetryStrategy.NONE:
            return 0.0
        elif self.retry_strategy == RetryStrategy.LINEAR:
            return self.retry_delay * attempt
        elif self.retry_strategy == RetryStrategy.EXPONENTIAL:
            return self.retry_delay * (2 ** (attempt - 1))
        else:
            return self.retry_delay


class ResourceUsage(BaseModel):
    """Uso de recursos de uma task"""
    # CPU
    cpu_usage_percent: Optional[float] = Field(None, ge=0.0, le=100.0, description="Uso de CPU em %")
    cpu_time_seconds: Optional[float] = Field(None, ge=0.0, description="Tempo de CPU em segundos")
    
    # Memória
    memory_usage_mb: Optional[float] = Field(None, ge=0.0, description="Uso de memória em MB")
    memory_peak_mb: Optional[float] = Field(None, ge=0.0, description="Pico de memória em MB")
    
    # GPU
    gpu_usage_percent: Optional[float] = Field(None, ge=0.0, le=100.0, description="Uso de GPU em %")
    gpu_memory_mb: Optional[float] = Field(None, ge=0.0, description="Memória GPU em MB")
    
    # I/O
    disk_read_mb: Optional[float] = Field(None, ge=0.0, description="Leitura de disco em MB")
    disk_write_mb: Optional[float] = Field(None, ge=0.0, description="Escrita de disco em MB")
    network_in_mb: Optional[float] = Field(None, ge=0.0, description="Tráfego de rede entrada em MB")
    network_out_mb: Optional[float] = Field(None, ge=0.0, description="Tráfego de rede saída em MB")
    
    # Tempos
    wall_time_seconds: Optional[float] = Field(None, ge=0.0, description="Tempo de parede em segundos")
    queue_time_seconds: Optional[float] = Field(None, ge=0.0, description="Tempo na fila em segundos")


class TaskMetrics(BaseModel):
    """Métricas de uma task"""
    # Timestamps
    created_at: datetime = Field(..., description="Timestamp de criação")
    queued_at: Optional[datetime] = Field(None, description="Timestamp de entrada na fila")
    started_at: Optional[datetime] = Field(None, description="Timestamp de início")
    completed_at: Optional[datetime] = Field(None, description="Timestamp de conclusão")
    
    # Durações
    queue_duration: Optional[float] = Field(None, ge=0.0, description="Tempo na fila em segundos")
    execution_duration: Optional[float] = Field(None, ge=0.0, description="Tempo de execução em segundos")
    total_duration: Optional[float] = Field(None, ge=0.0, description="Tempo total em segundos")
    
    # Tentativas
    attempt_number: int = Field(1, ge=1, description="Número da tentativa atual")
    retry_count: int = Field(0, ge=0, description="Número de retries executados")
    
    # Worker info
    worker_id: Optional[str] = Field(None, description="ID do worker")
    worker_hostname: Optional[str] = Field(None, description="Hostname do worker")
    worker_version: Optional[str] = Field(None, description="Versão do worker")
    
    # Recursos
    resource_usage: Optional[ResourceUsage] = Field(None, description="Uso de recursos")
    
    # Performance
    throughput: Optional[float] = Field(None, ge=0.0, description="Throughput (items/segundo)")
    efficiency_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Score de eficiência")
    
    @validator('queue_duration', pre=True, always=True)
    def calculate_queue_duration(cls, v, values):
        if v is not None:
            return v
        if 'queued_at' in values and 'started_at' in values and values['started_at'] and values['queued_at']:
            return (values['started_at'] - values['queued_at']).total_seconds()
        return None
    
    @validator('execution_duration', pre=True, always=True)
    def calculate_execution_duration(cls, v, values):
        if v is not None:
            return v
        if 'started_at' in values and 'completed_at' in values and values['completed_at'] and values['started_at']:
            return (values['completed_at'] - values['started_at']).total_seconds()
        return None
    
    @validator('total_duration', pre=True, always=True)
    def calculate_total_duration(cls, v, values):
        if v is not None:
            return v
        if 'created_at' in values and 'completed_at' in values and values['completed_at']:
            return (values['completed_at'] - values['created_at']).total_seconds()
        return None


# === MODELOS DE TASK ===

class BaseTask(BaseModel):
    """Modelo base para tasks"""
    # Identificação
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="ID único da task")
    parent_task_id: Optional[str] = Field(None, description="ID da task pai")
    batch_id: Optional[str] = Field(None, description="ID do lote")
    
    # Classificação
    category: TaskCategory = Field(..., description="Categoria da task")
    priority: int = Field(5, ge=1, le=10, description="Prioridade numérica")
    priority_level: TaskPriority = Field(TaskPriority.NORMAL, description="Nível de prioridade")
    
    # Estado
    status: TaskStatus = Field(TaskStatus.PENDING, description="Status atual")
    
    # Configuração
    configuration: TaskConfiguration = Field(default_factory=TaskConfiguration, description="Configuração da task")
    
    # Tags e metadados
    tags: List[str] = Field(default_factory=list, description="Tags da task")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados customizados")
    
    # Dependências
    dependencies: List[str] = Field(default_factory=list, description="IDs de tasks dependentes")
    dependent_tasks: List[str] = Field(default_factory=list, description="IDs de tasks que dependem desta")
    
    # Agendamento
    scheduled_at: Optional[datetime] = Field(None, description="Timestamp de agendamento")
    expires_at: Optional[datetime] = Field(None, description="Timestamp de expiração")
    
    @validator('priority_level', pre=True, always=True)
    def set_priority_level(cls, v, values):
        if v is not None:
            return v
        
        priority = values.get('priority', 5)
        if priority >= 10:
            return TaskPriority.CRITICAL
        elif priority >= 8:
            return TaskPriority.HIGH
        elif priority >= 5:
            return TaskPriority.NORMAL
        elif priority >= 3:
            return TaskPriority.LOW
        else:
            return TaskPriority.BACKGROUND


class OCRTask(BaseTask):
    """Task específica para processamento OCR"""
    category: TaskCategory = Field(TaskCategory.SINGLE_DOCUMENT, description="Categoria da task")
    
    # Entrada
    file_path: str = Field(..., description="Caminho do arquivo a processar")
    file_metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados do arquivo")
    
    # Configuração OCR
    engine: OCREngine = Field(..., description="Engine OCR a usar")
    parameters: OCRParameters = Field(default_factory=OCRParameters, description="Parâmetros OCR")
    
    # Fallback
    fallback_engines: List[OCREngine] = Field(default_factory=list, description="Engines de fallback")
    
    # Resultado
    result_path: Optional[str] = Field(None, description="Caminho do resultado")
    result_metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados do resultado")
    
    # Métricas específicas
    input_file_size: Optional[int] = Field(None, ge=0, description="Tamanho do arquivo de entrada")
    output_text_length: Optional[int] = Field(None, ge=0, description="Comprimento do texto extraído")
    confidence_score: Optional[float] = Field(None, ge=0.0, le=1.0, description="Score de confiança")
    quality_score: Optional[float] = Field(None, ge=0.0, le=10.0, description="Score de qualidade")


class BatchTask(BaseTask):
    """Task para processamento em lote"""
    category: TaskCategory = Field(TaskCategory.BATCH_PROCESSING, description="Categoria da task")
    
    # Entrada
    file_paths: List[str] = Field(..., min_items=1, description="Caminhos dos arquivos")
    batch_metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados do lote")
    
    # Configuração
    engine: OCREngine = Field(..., description="Engine OCR a usar")
    parameters: OCRParameters = Field(default_factory=OCRParameters, description="Parâmetros OCR")
    
    # Processamento
    parallel: bool = Field(True, description="Se deve processar em paralelo")
    max_concurrent: int = Field(5, ge=1, description="Máximo de processamentos simultâneos")
    
    # Sub-tasks
    subtask_ids: List[str] = Field(default_factory=list, description="IDs das sub-tasks")
    
    # Resultados
    completed_files: int = Field(0, ge=0, description="Arquivos completados")
    failed_files: int = Field(0, ge=0, description="Arquivos que falharam")
    
    @property
    def total_files(self) -> int:
        return len(self.file_paths)
    
    @property
    def completion_rate(self) -> float:
        if self.total_files == 0:
            return 0.0
        return (self.completed_files / self.total_files) * 100
    
    @property
    def success_rate(self) -> float:
        completed = self.completed_files + self.failed_files
        if completed == 0:
            return 0.0
        return (self.completed_files / completed) * 100


class PipelineTask(BaseTask):
    """Task para pipeline de processamento"""
    category: TaskCategory = Field(TaskCategory.PIPELINE_STAGE, description="Categoria da task")
    
    # Pipeline
    pipeline_id: str = Field(..., description="ID do pipeline")
    stage_name: str = Field(..., description="Nome do estágio")
    stage_order: int = Field(..., ge=0, description="Ordem do estágio")
    
    # Entrada/Saída
    input_data: Dict[str, Any] = Field(..., description="Dados de entrada")
    output_data: Dict[str, Any] = Field(default_factory=dict, description="Dados de saída")
    
    # Configuração do estágio
    stage_config: Dict[str, Any] = Field(default_factory=dict, description="Configuração do estágio")
    
    # Controle de fluxo
    skip_on_error: bool = Field(False, description="Se deve pular em caso de erro")
    continue_pipeline: bool = Field(True, description="Se deve continuar pipeline")


class AggregationTask(BaseTask):
    """Task para agregação de resultados"""
    category: TaskCategory = Field(TaskCategory.AGGREGATION, description="Categoria da task")
    
    # Entrada
    source_task_ids: List[str] = Field(..., min_items=2, description="IDs das tasks fonte")
    aggregation_method: str = Field(..., description="Método de agregação")
    
    # Configuração
    aggregation_config: Dict[str, Any] = Field(default_factory=dict, description="Configuração da agregação")
    
    # Pesos para agregação
    source_weights: Dict[str, float] = Field(default_factory=dict, description="Pesos das fontes")
    
    # Resultado
    aggregated_result: Dict[str, Any] = Field(default_factory=dict, description="Resultado agregado")


class HealthCheckTask(BaseTask):
    """Task para health check"""
    category: TaskCategory = Field(TaskCategory.HEALTH_CHECK, description="Categoria da task")
    
    # Configuração
    check_type: str = Field(..., description="Tipo de health check")
    check_config: Dict[str, Any] = Field(default_factory=dict, description="Configuração do check")
    
    # Resultado
    health_status: Optional[str] = Field(None, description="Status de saúde")
    health_details: Dict[str, Any] = Field(default_factory=dict, description="Detalhes de saúde")


# === MODELOS DE EXECUÇÃO ===

class TaskExecution(BaseModel):
    """Execução de uma task"""
    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="ID da execução")
    task_id: str = Field(..., description="ID da task")
    
    # Estado da execução
    status: TaskStatus = Field(TaskStatus.PENDING, description="Status da execução")
    metrics: TaskMetrics = Field(..., description="Métricas da execução")
    
    # Resultado
    result: Optional[Dict[str, Any]] = Field(None, description="Resultado da execução")
    error: Optional[str] = Field(None, description="Erro da execução")
    traceback: Optional[str] = Field(None, description="Traceback do erro")
    
    # Logs
    logs: List[str] = Field(default_factory=list, description="Logs da execução")
    debug_info: Dict[str, Any] = Field(default_factory=dict, description="Informações de debug")
    
    # Checkpoints
    checkpoints: List[Dict[str, Any]] = Field(default_factory=list, description="Checkpoints da execução")
    
    def add_log(self, message: str, level: str = "INFO"):
        """Adiciona log à execução"""
        timestamp = datetime.now().isoformat()
        log_entry = f"[{timestamp}] {level}: {message}"
        self.logs.append(log_entry)
    
    def add_checkpoint(self, name: str, data: Dict[str, Any] = None):
        """Adiciona checkpoint à execução"""
        checkpoint = {
            "name": name,
            "timestamp": datetime.now().isoformat(),
            "data": data or {}
        }
        self.checkpoints.append(checkpoint)
    
    def get_duration(self) -> Optional[float]:
        """Retorna duração da execução"""
        return self.metrics.execution_duration


class TaskQueue(BaseModel):
    """Fila de tasks"""
    queue_name: str = Field(..., description="Nome da fila")
    queue_type: str = Field("standard", description="Tipo da fila")
    
    # Configuração
    max_size: int = Field(1000, gt=0, description="Tamanho máximo da fila")
    priority_enabled: bool = Field(True, description="Se prioridade está habilitada")
    
    # Estado atual
    current_size: int = Field(0, ge=0, description="Tamanho atual")
    pending_tasks: int = Field(0, ge=0, description="Tasks pendentes")
    processing_tasks: int = Field(0, ge=0, description="Tasks sendo processadas")
    
    # Workers
    active_workers: int = Field(0, ge=0, description="Workers ativos")
    max_workers: int = Field(1, ge=1, description="Máximo de workers")
    
    # Métricas
    throughput: float = Field(0.0, ge=0.0, description="Throughput (tasks/min)")
    avg_wait_time: float = Field(0.0, ge=0.0, description="Tempo médio de espera")
    avg_processing_time: float = Field(0.0, ge=0.0, description="Tempo médio de processamento")
    
    # Estado
    is_active: bool = Field(True, description="Se a fila está ativa")
    last_activity: Optional[datetime] = Field(None, description="Última atividade")
    
    @property
    def utilization_rate(self) -> float:
        """Taxa de utilização da fila"""
        if self.max_size == 0:
            return 0.0
        return (self.current_size / self.max_size) * 100
    
    @property
    def worker_utilization(self) -> float:
        """Taxa de utilização dos workers"""
        if self.max_workers == 0:
            return 0.0
        return (self.active_workers / self.max_workers) * 100


# === FUNÇÕES UTILITÁRIAS ===

def create_ocr_task(file_path: str, engine: OCREngine, **kwargs) -> OCRTask:
    """
    Factory para criar OCRTask
    
    Args:
        file_path: Caminho do arquivo
        engine: Engine OCR
        **kwargs: Outros parâmetros
        
    Returns:
        OCRTask instance
    """
    return OCRTask(
        file_path=file_path,
        engine=engine,
        priority=kwargs.get('priority', 5),
        parameters=OCRParameters(**{k: v for k, v in kwargs.items() if k in OCRParameters.__fields__}),
        metadata=kwargs.get('metadata', {}),
        tags=kwargs.get('tags', []),
        scheduled_at=kwargs.get('scheduled_at'),
        expires_at=kwargs.get('expires_at')
    )


def create_batch_task(file_paths: List[str], engine: OCREngine, **kwargs) -> BatchTask:
    """
    Factory para criar BatchTask
    
    Args:
        file_paths: Lista de caminhos de arquivo
        engine: Engine OCR
        **kwargs: Outros parâmetros
        
    Returns:
        BatchTask instance
    """
    return BatchTask(
        file_paths=file_paths,
        engine=engine,
        priority=kwargs.get('priority', 5),
        parameters=OCRParameters(**{k: v for k, v in kwargs.items() if k in OCRParameters.__fields__}),
        parallel=kwargs.get('parallel', True),
        max_concurrent=kwargs.get('max_concurrent', 5),
        metadata=kwargs.get('metadata', {}),
        tags=kwargs.get('tags', [])
    )


def calculate_task_priority(category: TaskCategory, file_size: int = 0, **kwargs) -> int:
    """
    Calcula prioridade de task baseada em vários fatores
    
    Args:
        category: Categoria da task
        file_size: Tamanho do arquivo
        **kwargs: Outros fatores
        
    Returns:
        Prioridade calculada (1-10)
    """
    priority = 5  # Base
    
    # Ajustar por categoria
    if category == TaskCategory.HEALTH_CHECK:
        priority += 3
    elif category == TaskCategory.SINGLE_DOCUMENT:
        priority += 0
    elif category == TaskCategory.BATCH_PROCESSING:
        priority -= 1
    elif category == TaskCategory.MAINTENANCE:
        priority -= 2
    
    # Ajustar por tamanho do arquivo (arquivos menores = maior prioridade)
    if file_size > 0:
        if file_size < 1024 * 1024:  # < 1MB
            priority += 1
        elif file_size > 10 * 1024 * 1024:  # > 10MB
            priority -= 1
    
    # Ajustar por urgência
    if kwargs.get('urgent', False):
        priority += 2
    
    # Ajustar por usuário VIP
    if kwargs.get('vip_user', False):
        priority += 1
    
    return max(1, min(10, priority))


if __name__ == "__main__":
    """Teste dos modelos de task"""
    print("=== Task Models Test ===")
    
    # Teste OCRTask
    ocr_task = create_ocr_task(
        "test.jpg",
        OCREngine.PADDLEOCR,
        priority=7,
        metadata={"user": "test_user"}
    )
    
    print(f"OCR Task: {ocr_task.task_id}")
    print(f"Priority level: {ocr_task.priority_level}")
    print(f"Engine: {ocr_task.engine}")
    
    # Teste BatchTask
    batch_task = create_batch_task(
        ["file1.jpg", "file2.jpg", "file3.jpg"],
        OCREngine.EASYOCR,
        parallel=True,
        max_concurrent=3
    )
    
    print(f"\nBatch Task: {batch_task.task_id}")
    print(f"Total files: {batch_task.total_files}")
    print(f"Completion rate: {batch_task.completion_rate:.1f}%")
    
    # Teste TaskMetrics
    metrics = TaskMetrics(
        created_at=datetime.now(),
        attempt_number=1,
        worker_id="worker-001"
    )
    
    print(f"\nTask Metrics:")
    print(f"Created at: {metrics.created_at}")
    print(f"Attempt: {metrics.attempt_number}")
    
    # Teste TaskConfiguration
    config = TaskConfiguration(
        timeout=600,
        max_retries=5,
        retry_strategy=RetryStrategy.EXPONENTIAL,
        gpu_required=True
    )
    
    print(f"\nTask Configuration:")
    print(f"Timeout: {config.timeout}s")
    print(f"Max retries: {config.max_retries}")
    print(f"Retry delay for attempt 3: {config.get_retry_delay(3):.1f}s")
    
    # Teste cálculo de prioridade
    priority = calculate_task_priority(
        TaskCategory.SINGLE_DOCUMENT,
        file_size=500*1024,  # 500KB
        urgent=True
    )
    print(f"\nCalculated priority: {priority}")
    
    print("\n✅ Task Models test completed")