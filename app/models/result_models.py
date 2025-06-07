#!/usr/bin/env python3
"""
Modelos de Resultados OCR
========================

Modelos Pydantic específicos para resultados de processamento OCR:
- Resultados de engines individuais
- Resultados agregados e combinados
- Métricas e estatísticas de qualidade
- Metadados de processamento
- Estruturas de layout e análise
"""

from typing import Dict, Any, List, Optional, Union, Tuple
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field, validator, root_validator
import uuid

from .schemas import BoundingBox, TextBlock, OCRStatistics, OutputFormat


class ProcessingStage(str, Enum):
    """Estágios de processamento"""
    PREPROCESSING = "preprocessing"
    OCR_EXTRACTION = "ocr_extraction"
    LAYOUT_ANALYSIS = "layout_analysis"
    POST_PROCESSING = "post_processing"
    AGGREGATION = "aggregation"
    FINALIZATION = "finalization"


class QualityLevel(str, Enum):
    """Níveis de qualidade"""
    EXCELLENT = "excellent"  # 9-10
    GOOD = "good"           # 7-8
    FAIR = "fair"           # 5-6
    POOR = "poor"           # 3-4
    VERY_POOR = "very_poor" # 0-2


class ConfidenceLevel(str, Enum):
    """Níveis de confiança"""
    HIGH = "high"       # > 0.8
    MEDIUM = "medium"   # 0.5-0.8
    LOW = "low"         # 0.3-0.5
    VERY_LOW = "very_low"  # < 0.3


# === MODELOS DE COMPONENTES ===

class ProcessingMetadata(BaseModel):
    """Metadados de processamento"""
    stage: ProcessingStage = Field(..., description="Estágio de processamento")
    start_time: float = Field(..., description="Timestamp de início")
    end_time: Optional[float] = Field(None, description="Timestamp de fim")
    duration: Optional[float] = Field(None, description="Duração em segundos")
    worker_name: Optional[str] = Field(None, description="Nome do worker")
    model_version: Optional[str] = Field(None, description="Versão do modelo")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parâmetros usados")
    memory_usage: Optional[float] = Field(None, description="Uso de memória em MB")
    gpu_usage: Optional[float] = Field(None, description="Uso de GPU em %")
    
    @validator('duration', pre=True, always=True)
    def calculate_duration(cls, v, values):
        if v is not None:
            return v
        if 'start_time' in values and 'end_time' in values and values['end_time']:
            return values['end_time'] - values['start_time']
        return None


class QualityMetrics(BaseModel):
    """Métricas de qualidade do resultado"""
    overall_score: float = Field(..., ge=0.0, le=10.0, description="Score geral de qualidade")
    text_quality: float = Field(..., ge=0.0, le=10.0, description="Qualidade do texto")
    layout_quality: float = Field(..., ge=0.0, le=10.0, description="Qualidade do layout")
    confidence_consistency: float = Field(..., ge=0.0, le=1.0, description="Consistência da confiança")
    
    # Scores específicos
    character_accuracy: Optional[float] = Field(None, ge=0.0, le=1.0, description="Precisão de caracteres")
    word_accuracy: Optional[float] = Field(None, ge=0.0, le=1.0, description="Precisão de palavras")
    line_accuracy: Optional[float] = Field(None, ge=0.0, le=1.0, description="Precisão de linhas")
    
    # Níveis categóricos
    quality_level: QualityLevel = Field(..., description="Nível de qualidade")
    confidence_level: ConfidenceLevel = Field(..., description="Nível de confiança")
    
    # Indicadores de problemas
    has_text_noise: bool = Field(False, description="Presença de ruído no texto")
    has_layout_issues: bool = Field(False, description="Problemas de layout")
    has_encoding_issues: bool = Field(False, description="Problemas de codificação")
    
    @validator('quality_level', pre=True, always=True)
    def set_quality_level(cls, v, values):
        if v is not None:
            return v
        
        score = values.get('overall_score', 0)
        if score >= 9:
            return QualityLevel.EXCELLENT
        elif score >= 7:
            return QualityLevel.GOOD
        elif score >= 5:
            return QualityLevel.FAIR
        elif score >= 3:
            return QualityLevel.POOR
        else:
            return QualityLevel.VERY_POOR
    
    @validator('confidence_level', pre=True, always=True)
    def set_confidence_level(cls, v, values):
        if v is not None:
            return v
        
        confidence = values.get('confidence_consistency', 0)
        if confidence > 0.8:
            return ConfidenceLevel.HIGH
        elif confidence > 0.5:
            return ConfidenceLevel.MEDIUM
        elif confidence > 0.3:
            return ConfidenceLevel.LOW
        else:
            return ConfidenceLevel.VERY_LOW


class LayoutElement(BaseModel):
    """Elemento de layout detectado"""
    element_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="ID único do elemento")
    type: str = Field(..., description="Tipo do elemento")
    bbox: BoundingBox = Field(..., description="Bounding box")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confiança da detecção")
    reading_order: Optional[int] = Field(None, description="Ordem de leitura")
    
    # Propriedades específicas
    text_content: Optional[str] = Field(None, description="Conteúdo de texto")
    children: List[str] = Field(default_factory=list, description="IDs de elementos filhos")
    parent: Optional[str] = Field(None, description="ID do elemento pai")
    
    # Atributos visuais
    font_size: Optional[float] = Field(None, description="Tamanho da fonte estimado")
    is_bold: Optional[bool] = Field(None, description="Se é negrito")
    is_italic: Optional[bool] = Field(None, description="Se é itálico")
    text_color: Optional[str] = Field(None, description="Cor do texto")
    background_color: Optional[str] = Field(None, description="Cor de fundo")
    
    # Metadados
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados adicionais")


class TableStructure(BaseModel):
    """Estrutura de tabela detectada"""
    table_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="ID da tabela")
    bbox: BoundingBox = Field(..., description="Bounding box da tabela")
    rows: int = Field(..., ge=1, description="Número de linhas")
    columns: int = Field(..., ge=1, description="Número de colunas")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confiança da detecção")
    
    # Células
    cells: List[Dict[str, Any]] = Field(default_factory=list, description="Células da tabela")
    headers: List[str] = Field(default_factory=list, description="Cabeçalhos identificados")
    
    # Propriedades
    has_headers: bool = Field(False, description="Se tem cabeçalhos")
    is_bordered: bool = Field(False, description="Se tem bordas visíveis")
    cell_spacing: Optional[float] = Field(None, description="Espaçamento entre células")
    
    @validator('cells')
    def validate_cells(cls, v, values):
        expected_cells = values.get('rows', 0) * values.get('columns', 0)
        if len(v) > expected_cells:
            raise ValueError(f"Too many cells: {len(v)} > {expected_cells}")
        return v


# === MODELOS DE RESULTADOS ===

class SingleEngineResult(BaseModel):
    """Resultado de um engine individual"""
    engine_name: str = Field(..., description="Nome do engine")
    engine_version: Optional[str] = Field(None, description="Versão do engine")
    
    # Resultado principal
    text: str = Field("", description="Texto extraído")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confiança geral")
    blocks: List[TextBlock] = Field(default_factory=list, description="Blocos de texto")
    
    # Estrutura e layout
    layout_elements: List[LayoutElement] = Field(default_factory=list, description="Elementos de layout")
    tables: List[TableStructure] = Field(default_factory=list, description="Tabelas detectadas")
    reading_order: List[str] = Field(default_factory=list, description="Ordem de leitura dos elementos")
    
    # Formatos de saída
    markdown: Optional[str] = Field(None, description="Versão em Markdown")
    html: Optional[str] = Field(None, description="Versão em HTML")
    json_structured: Optional[Dict[str, Any]] = Field(None, description="Dados estruturados")
    
    # Metadados
    processing_metadata: List[ProcessingMetadata] = Field(default_factory=list, description="Metadados de processamento")
    quality_metrics: Optional[QualityMetrics] = Field(None, description="Métricas de qualidade")
    statistics: OCRStatistics = Field(default_factory=OCRStatistics, description="Estatísticas")
    
    # Diagnósticos
    warnings: List[str] = Field(default_factory=list, description="Avisos")
    errors: List[str] = Field(default_factory=list, description="Erros não fatais")
    performance_metrics: Dict[str, float] = Field(default_factory=dict, description="Métricas de performance")
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now, description="Timestamp de criação")
    
    def get_total_processing_time(self) -> float:
        """Calcula tempo total de processamento"""
        return sum(meta.duration or 0 for meta in self.processing_metadata)
    
    def get_stage_duration(self, stage: ProcessingStage) -> Optional[float]:
        """Obtém duração de um estágio específico"""
        for meta in self.processing_metadata:
            if meta.stage == stage:
                return meta.duration
        return None
    
    def add_processing_stage(self, stage: ProcessingStage, start_time: float, **kwargs):
        """Adiciona estágio de processamento"""
        metadata = ProcessingMetadata(
            stage=stage,
            start_time=start_time,
            end_time=kwargs.get('end_time'),
            worker_name=kwargs.get('worker_name'),
            model_version=kwargs.get('model_version'),
            parameters=kwargs.get('parameters', {}),
            memory_usage=kwargs.get('memory_usage'),
            gpu_usage=kwargs.get('gpu_usage')
        )
        self.processing_metadata.append(metadata)


class AggregatedResult(BaseModel):
    """Resultado agregado de múltiplos engines"""
    aggregation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="ID da agregação")
    
    # Resultado final
    text: str = Field("", description="Texto final agregado")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confiança agregada")
    blocks: List[TextBlock] = Field(default_factory=list, description="Blocos agregados")
    
    # Resultados individuais
    individual_results: List[SingleEngineResult] = Field(..., description="Resultados individuais")
    aggregation_method: str = Field(..., description="Método de agregação usado")
    
    # Análise comparativa
    consensus_score: float = Field(0.0, ge=0.0, le=1.0, description="Score de consenso entre engines")
    variation_score: float = Field(0.0, ge=0.0, le=1.0, description="Score de variação entre engines")
    agreement_map: Dict[str, float] = Field(default_factory=dict, description="Mapa de concordância entre engines")
    
    # Estrutura final
    layout_elements: List[LayoutElement] = Field(default_factory=list, description="Layout agregado")
    tables: List[TableStructure] = Field(default_factory=list, description="Tabelas agregadas")
    
    # Metadados de agregação
    aggregation_metadata: ProcessingMetadata = Field(..., description="Metadados da agregação")
    quality_metrics: QualityMetrics = Field(..., description="Métricas de qualidade final")
    
    # Decisões tomadas
    resolution_decisions: List[Dict[str, Any]] = Field(default_factory=list, description="Decisões de resolução de conflitos")
    
    @validator('individual_results')
    def validate_individual_results(cls, v):
        if len(v) < 2:
            raise ValueError("Aggregated result must have at least 2 individual results")
        return v
    
    def get_engines_used(self) -> List[str]:
        """Retorna lista de engines usados"""
        return [result.engine_name for result in self.individual_results]
    
    def get_best_individual_result(self) -> SingleEngineResult:
        """Retorna resultado individual com maior confiança"""
        return max(self.individual_results, key=lambda r: r.confidence)
    
    def calculate_consensus_metrics(self) -> Dict[str, float]:
        """Calcula métricas de consenso"""
        if len(self.individual_results) < 2:
            return {"consensus": 0.0, "variation": 0.0}
        
        # Comparar textos (simplificado)
        texts = [result.text for result in self.individual_results]
        confidences = [result.confidence for result in self.individual_results]
        
        # Consenso baseado em similaridade de texto e confiança
        import statistics
        confidence_std = statistics.stdev(confidences) if len(confidences) > 1 else 0
        confidence_mean = statistics.mean(confidences)
        
        # Score de consenso (quanto menor a variação, maior o consenso)
        consensus = max(0.0, 1.0 - (confidence_std / max(confidence_mean, 0.1)))
        variation = confidence_std / max(confidence_mean, 0.1)
        
        return {
            "consensus": min(1.0, consensus),
            "variation": min(1.0, variation)
        }


class BatchProcessingResult(BaseModel):
    """Resultado de processamento em lote"""
    batch_id: str = Field(..., description="ID do lote")
    
    # Resultados individuais
    individual_results: List[Union[SingleEngineResult, AggregatedResult]] = Field(..., description="Resultados individuais")
    
    # Estatísticas do lote
    total_files: int = Field(..., ge=0, description="Total de arquivos processados")
    successful_files: int = Field(..., ge=0, description="Arquivos processados com sucesso")
    failed_files: int = Field(..., ge=0, description="Arquivos que falharam")
    
    # Métricas agregadas
    total_processing_time: float = Field(..., ge=0.0, description="Tempo total de processamento")
    avg_processing_time: float = Field(..., ge=0.0, description="Tempo médio por arquivo")
    total_characters: int = Field(..., ge=0, description="Total de caracteres extraídos")
    avg_confidence: float = Field(..., ge=0.0, le=1.0, description="Confiança média")
    
    # Distribuição por engine
    engine_usage: Dict[str, int] = Field(default_factory=dict, description="Uso por engine")
    engine_performance: Dict[str, Dict[str, float]] = Field(default_factory=dict, description="Performance por engine")
    
    # Análise de qualidade
    quality_distribution: Dict[QualityLevel, int] = Field(default_factory=dict, description="Distribuição de qualidade")
    confidence_distribution: Dict[ConfidenceLevel, int] = Field(default_factory=dict, description="Distribuição de confiança")
    
    # Metadados
    started_at: datetime = Field(..., description="Timestamp de início")
    completed_at: Optional[datetime] = Field(None, description="Timestamp de conclusão")
    batch_metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadados do lote")
    
    @validator('successful_files')
    def validate_successful_files(cls, v, values):
        total = values.get('total_files', 0)
        if v > total:
            raise ValueError("Successful files cannot exceed total files")
        return v
    
    @validator('failed_files')
    def validate_failed_files(cls, v, values):
        total = values.get('total_files', 0)
        successful = values.get('successful_files', 0)
        expected_failed = total - successful
        if v != expected_failed:
            raise ValueError(f"Failed files should be {expected_failed}, got {v}")
        return v
    
    def calculate_success_rate(self) -> float:
        """Calcula taxa de sucesso"""
        if self.total_files == 0:
            return 0.0
        return (self.successful_files / self.total_files) * 100
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """Retorna resumo de performance"""
        return {
            "success_rate": self.calculate_success_rate(),
            "avg_processing_time": self.avg_processing_time,
            "total_processing_time": self.total_processing_time,
            "throughput": self.total_files / max(self.total_processing_time, 1),  # files per second
            "avg_confidence": self.avg_confidence,
            "total_characters": self.total_characters,
            "chars_per_second": self.total_characters / max(self.total_processing_time, 1)
        }


# === MODELOS DE COMPARAÇÃO ===

class ResultComparison(BaseModel):
    """Comparação entre resultados"""
    comparison_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="ID da comparação")
    
    # Resultados comparados
    result_a: Union[SingleEngineResult, AggregatedResult] = Field(..., description="Primeiro resultado")
    result_b: Union[SingleEngineResult, AggregatedResult] = Field(..., description="Segundo resultado")
    
    # Métricas de similaridade
    text_similarity: float = Field(..., ge=0.0, le=1.0, description="Similaridade de texto")
    structure_similarity: float = Field(..., ge=0.0, le=1.0, description="Similaridade de estrutura")
    layout_similarity: float = Field(..., ge=0.0, le=1.0, description="Similaridade de layout")
    overall_similarity: float = Field(..., ge=0.0, le=1.0, description="Similaridade geral")
    
    # Diferenças identificadas
    text_differences: List[Dict[str, Any]] = Field(default_factory=list, description="Diferenças no texto")
    structure_differences: List[Dict[str, Any]] = Field(default_factory=list, description="Diferenças na estrutura")
    
    # Recomendação
    recommended_result: str = Field(..., description="Resultado recomendado (a ou b)")
    recommendation_reason: str = Field(..., description="Razão da recomendação")
    confidence_in_recommendation: float = Field(..., ge=0.0, le=1.0, description="Confiança na recomendação")
    
    # Metadados
    comparison_metadata: ProcessingMetadata = Field(..., description="Metadados da comparação")


# === FUNÇÕES UTILITÁRIAS ===

def create_quality_metrics(overall_score: float, **kwargs) -> QualityMetrics:
    """
    Factory para criar QualityMetrics
    
    Args:
        overall_score: Score geral de qualidade
        **kwargs: Outros parâmetros
        
    Returns:
        QualityMetrics instance
    """
    return QualityMetrics(
        overall_score=overall_score,
        text_quality=kwargs.get('text_quality', overall_score),
        layout_quality=kwargs.get('layout_quality', overall_score),
        confidence_consistency=kwargs.get('confidence_consistency', overall_score / 10),
        character_accuracy=kwargs.get('character_accuracy'),
        word_accuracy=kwargs.get('word_accuracy'),
        line_accuracy=kwargs.get('line_accuracy'),
        has_text_noise=kwargs.get('has_text_noise', False),
        has_layout_issues=kwargs.get('has_layout_issues', False),
        has_encoding_issues=kwargs.get('has_encoding_issues', False)
    )


def create_processing_metadata(stage: ProcessingStage, start_time: float, **kwargs) -> ProcessingMetadata:
    """
    Factory para criar ProcessingMetadata
    
    Args:
        stage: Estágio de processamento
        start_time: Timestamp de início
        **kwargs: Outros parâmetros
        
    Returns:
        ProcessingMetadata instance
    """
    return ProcessingMetadata(
        stage=stage,
        start_time=start_time,
        end_time=kwargs.get('end_time'),
        worker_name=kwargs.get('worker_name'),
        model_version=kwargs.get('model_version'),
        parameters=kwargs.get('parameters', {}),
        memory_usage=kwargs.get('memory_usage'),
        gpu_usage=kwargs.get('gpu_usage')
    )


if __name__ == "__main__":
    """Teste dos modelos de resultado"""
    import time
    
    print("=== Result Models Test ===")
    
    # Teste SingleEngineResult
    start_time = time.time()
    result = SingleEngineResult(
        engine_name="test_engine",
        text="Texto de teste",
        confidence=0.85
    )
    
    # Adicionar estágio de processamento
    result.add_processing_stage(
        ProcessingStage.OCR_EXTRACTION,
        start_time,
        end_time=time.time(),
        worker_name="test_worker"
    )
    
    print(f"Single engine result: {result.engine_name}")
    print(f"Processing time: {result.get_total_processing_time():.2f}s")
    
    # Teste QualityMetrics
    quality = create_quality_metrics(7.5, confidence_consistency=0.8)
    print(f"Quality level: {quality.quality_level}")
    print(f"Confidence level: {quality.confidence_level}")
    
    # Teste AggregatedResult
    result2 = SingleEngineResult(
        engine_name="test_engine_2",
        text="Texto de teste similar",
        confidence=0.78
    )
    
    aggregation_meta = create_processing_metadata(
        ProcessingStage.AGGREGATION,
        time.time()
    )
    
    aggregated = AggregatedResult(
        individual_results=[result, result2],
        aggregation_method="best_confidence",
        text="Texto de teste",
        confidence=0.85,
        aggregation_metadata=aggregation_meta,
        quality_metrics=quality
    )
    
    print(f"Aggregated result from engines: {aggregated.get_engines_used()}")
    print(f"Best individual confidence: {aggregated.get_best_individual_result().confidence}")
    
    print("\n✅ Result Models test completed")