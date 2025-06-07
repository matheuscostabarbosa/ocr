#!/usr/bin/env python3
"""
Processador de Resultados
=========================

Processa e agrega resultados OCR:
- Validação de resultados
- Normalização de formatos
- Agregação de múltiplos engines
- Pós-processamento inteligente
- Métricas de qualidade
- Formatação de saída
"""

import time
import re
import json
import logging
from typing import Dict, Any, List, Optional, Union, Tuple
from datetime import datetime
from collections import defaultdict
import hashlib

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.models.schemas import OCRResponse, TextBlock, OCRStatistics, OutputFormat

logger = logging.getLogger(__name__)


class ResultProcessor:
    """Processador de resultados OCR"""
    
    def __init__(self):
        self.redis_client = get_redis_client()
        
        # Configurações
        self.enable_text_cleaning = True
        self.enable_quality_scoring = True
        self.enable_result_caching = True
        
        # Thresholds de qualidade
        self.min_confidence_threshold = 0.3
        self.min_text_length = 3
        self.max_special_char_ratio = 0.5
        
        # Métricas
        self.results_processed = 0
        self.aggregations_performed = 0
        self.quality_improvements = 0
    
    def process_single_result(self, result: Dict[str, Any], **kwargs) -> OCRResponse:
        """
        Processa resultado de um único engine
        
        Args:
            result: Resultado bruto do engine
            **kwargs: Parâmetros de processamento
            
        Returns:
            OCRResponse processado
        """
        try:
            self.results_processed += 1
            start_time = time.time()
            
            # Validar entrada
            if not self._validate_result_structure(result):
                logger.warning("Invalid result structure received")
                result = self._create_fallback_result(result)
            
            # Converter para OCRResponse se necessário
            if isinstance(result, dict):
                ocr_response = OCRResponse(**result)
            else:
                ocr_response = result
            
            # Aplicar processamentos
            if self.enable_text_cleaning:
                ocr_response = self._clean_text_result(ocr_response, **kwargs)
            
            if self.enable_quality_scoring:
                ocr_response = self._score_result_quality(ocr_response)
            
            # Aplicar filtros
            ocr_response = self._apply_confidence_filters(ocr_response, **kwargs)
            
            # Formatação de saída
            output_format = kwargs.get('output_format', OutputFormat.TEXT)
            ocr_response = self._format_output(ocr_response, output_format, **kwargs)
            
            # Normalizar estrutura
            ocr_response = self._normalize_result_structure(ocr_response)
            
            # Adicionar metadados de processamento
            ocr_response = self._add_processing_metadata(ocr_response, start_time)
            
            # Calcular estatísticas finais
            ocr_response.statistics = self._calculate_final_statistics(ocr_response)
            
            # Registrar métricas
            self._record_processing_metrics(ocr_response)
            
            return ocr_response
            
        except Exception as e:
            logger.error(f"Single result processing failed: {e}")
            return self._create_error_result(str(e))
    
    def aggregate_multiple_results(self, results: List[Dict[str, Any]], method: str = "best_confidence", **kwargs) -> OCRResponse:
        """
        Agrega resultados de múltiplos engines
        
        Args:
            results: Lista de resultados
            method: Método de agregação
            **kwargs: Parâmetros adicionais
            
        Returns:
            OCRResponse agregado
        """
        try:
            self.aggregations_performed += 1
            start_time = time.time()
            
            if not results:
                return self._create_error_result("No results to aggregate")
            
            # Processar cada resultado individualmente primeiro
            processed_results = []
            for result in results:
                try:
                    processed = self.process_single_result(result, **kwargs)
                    processed_results.append(processed)
                except Exception as e:
                    logger.warning(f"Failed to process individual result: {e}")
                    continue
            
            if not processed_results:
                return self._create_error_result("No valid results to aggregate")
            
            # Aplicar método de agregação
            if method == "best_confidence":
                aggregated = self._aggregate_by_best_confidence(processed_results)
            elif method == "weighted_average":
                aggregated = self._aggregate_by_weighted_average(processed_results)
            elif method == "consensus":
                aggregated = self._aggregate_by_consensus(processed_results)
            elif method == "longest_text":
                aggregated = self._aggregate_by_longest_text(processed_results)
            elif method == "majority_vote":
                aggregated = self._aggregate_by_majority_vote(processed_results)
            else:
                logger.warning(f"Unknown aggregation method: {method}, using best_confidence")
                aggregated = self._aggregate_by_best_confidence(processed_results)
            
            # Adicionar informações de agregação
            aggregated = self._add_aggregation_metadata(aggregated, processed_results, method, start_time)
            
            # Pós-processamento específico para agregação
            aggregated = self._post_process_aggregated_result(aggregated, processed_results, **kwargs)
            
            return aggregated
            
        except Exception as e:
            logger.error(f"Result aggregation failed: {e}")
            return self._create_error_result(f"Aggregation failed: {str(e)}")
    
    def _validate_result_structure(self, result: Dict[str, Any]) -> bool:
        """Valida estrutura do resultado"""
        try:
            required_fields = ['text', 'confidence']
            return all(field in result for field in required_fields)
        except Exception:
            return False
    
    def _create_fallback_result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Cria resultado fallback para estruturas inválidas"""
        return {
            "text": result.get("text", ""),
            "confidence": result.get("confidence", 0.0),
            "blocks": result.get("blocks", []),
            "engine": result.get("engine", "unknown"),
            "processing_time": result.get("processing_time", 0.0),
            "statistics": OCRStatistics().dict(),
            "warnings": ["Invalid result structure - fallback applied"]
        }
    
    def _clean_text_result(self, response: OCRResponse, **kwargs) -> OCRResponse:
        """Limpa e normaliza texto"""
        try:
            if not response.text:
                return response
            
            original_text = response.text
            cleaned_text = original_text
            
            # Remover caracteres de controle
            cleaned_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]', '', cleaned_text)
            
            # Normalizar espaços em branco
            cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
            cleaned_text = re.sub(r'\n\s*\n', '\n\n', cleaned_text)  # Preservar quebras de parágrafo
            
            # Limpar caracteres especiais em excesso
            if kwargs.get('remove_excess_punctuation', True):
                cleaned_text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\(\)\[\]\{\}\"\']+', '', cleaned_text)
            
            # Correções específicas para OCR
            if kwargs.get('apply_ocr_corrections', True):
                cleaned_text = self._apply_ocr_corrections(cleaned_text)
            
            # Normalizar quebras de linha
            if kwargs.get('normalize_line_breaks', True):
                cleaned_text = self._normalize_line_breaks(cleaned_text)
            
            # Atualizar response
            response.text = cleaned_text.strip()
            
            # Limpar blocos também
            if response.blocks:
                for block in response.blocks:
                    if hasattr(block, 'text'):
                        block.text = self._clean_block_text(block.text)
            
            # Registrar se houve melhoria
            if len(cleaned_text.strip()) > len(original_text.strip()):
                self.quality_improvements += 1
            
            return response
            
        except Exception as e:
            logger.warning(f"Text cleaning failed: {e}")
            return response
    
    def _apply_ocr_corrections(self, text: str) -> str:
        """Aplica correções comuns de OCR"""
        try:
            corrections = {
                # Correções de caracteres comuns
                r'\b0\b(?=\w)': 'O',  # 0 -> O quando seguido de letra
                r'\b1\b(?=\w)': 'l',  # 1 -> l quando seguido de letra
                r'\brn\b': 'm',       # rn -> m
                r'\bvv\b': 'w',       # vv -> w
                
                # Correções de pontuação
                r'\.{3,}': '...',     # Múltiplos pontos
                r'\,{2,}': ',',       # Múltiplas vírgulas
                
                # Espaços antes de pontuação
                r'\s+([\.!?,:;])': r'\1',
                
                # Espaços após parênteses/colchetes de abertura
                r'([\(\[\{])\s+': r'\1',
                r'\s+([\)\]\}])': r'\1',
            }
            
            for pattern, replacement in corrections.items():
                text = re.sub(pattern, replacement, text)
            
            return text
            
        except Exception as e:
            logger.warning(f"OCR corrections failed: {e}")
            return text
    
    def _normalize_line_breaks(self, text: str) -> str:
        """Normaliza quebras de linha"""
        try:
            # Detectar se é texto em parágrafos ou lista
            lines = text.split('\n')
            
            # Se muitas linhas curtas, pode ser lista
            short_lines = sum(1 for line in lines if len(line.strip()) < 50)
            if short_lines / len(lines) > 0.7:
                # Preservar quebras para lista
                return text
            
            # Para texto em prosa, juntar linhas quebradas
            normalized_lines = []
            current_paragraph = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    if current_paragraph:
                        normalized_lines.append(' '.join(current_paragraph))
                        current_paragraph = []
                    normalized_lines.append('')
                else:
                    # Se linha termina com pontuação, é fim de sentença
                    if line.endswith(('.', '!', '?', ':', ';')):
                        current_paragraph.append(line)
                        normalized_lines.append(' '.join(current_paragraph))
                        current_paragraph = []
                    else:
                        current_paragraph.append(line)
            
            # Adicionar último parágrafo
            if current_paragraph:
                normalized_lines.append(' '.join(current_paragraph))
            
            return '\n'.join(normalized_lines)
            
        except Exception as e:
            logger.warning(f"Line break normalization failed: {e}")
            return text
    
    def _clean_block_text(self, text: str) -> str:
        """Limpa texto de um bloco individual"""
        if not text:
            return text
        
        # Limpeza básica
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]', '', text)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        return cleaned.strip()
    
    def _score_result_quality(self, response: OCRResponse) -> OCRResponse:
        """Calcula score de qualidade do resultado"""
        try:
            quality_score = 5.0  # Base score
            
            # Fatores positivos
            if response.confidence > 0.8:
                quality_score += 2.0
            elif response.confidence > 0.6:
                quality_score += 1.0
            
            if len(response.text) > 100:
                quality_score += 1.0
            
            if response.blocks and len(response.blocks) > 1:
                quality_score += 0.5
            
            # Fatores negativos
            if response.confidence < 0.3:
                quality_score -= 2.0
            
            if len(response.text) < 10:
                quality_score -= 1.0
            
            # Verificar caracteres especiais em excesso
            special_chars = sum(1 for c in response.text if not c.isalnum() and not c.isspace())
            if special_chars > len(response.text) * self.max_special_char_ratio:
                quality_score -= 1.0
            
            # Verificar consistência entre blocos e texto
            if response.blocks:
                blocks_text = ' '.join(block.text for block in response.blocks if hasattr(block, 'text'))
                if abs(len(blocks_text) - len(response.text)) > len(response.text) * 0.3:
                    quality_score -= 0.5
            
            response.quality_score = max(0.0, min(10.0, quality_score))
            
            return response
            
        except Exception as e:
            logger.warning(f"Quality scoring failed: {e}")
            response.quality_score = 5.0
            return response
    
    def _apply_confidence_filters(self, response: OCRResponse, **kwargs) -> OCRResponse:
        """Aplica filtros de confiança"""
        try:
            min_confidence = kwargs.get('min_confidence', self.min_confidence_threshold)
            
            if not response.blocks:
                return response
            
            # Filtrar blocos por confiança
            filtered_blocks = [
                block for block in response.blocks
                if getattr(block, 'confidence', 1.0) >= min_confidence
            ]
            
            if filtered_blocks != response.blocks:
                response.blocks = filtered_blocks
                
                # Reconstruir texto com blocos filtrados
                if filtered_blocks:
                    response.text = '\n'.join(block.text for block in filtered_blocks if hasattr(block, 'text'))
                    
                    # Recalcular confiança média
                    confidences = [getattr(block, 'confidence', 1.0) for block in filtered_blocks]
                    response.confidence = sum(confidences) / len(confidences)
                else:
                    response.text = ""
                    response.confidence = 0.0
                
                if not hasattr(response, 'warnings'):
                    response.warnings = []
                response.warnings.append(f"Filtered {len(response.blocks) - len(filtered_blocks)} low-confidence blocks")
            
            return response
            
        except Exception as e:
            logger.warning(f"Confidence filtering failed: {e}")
            return response
    
    def _format_output(self, response: OCRResponse, output_format: OutputFormat, **kwargs) -> OCRResponse:
        """Formata saída no formato especificado"""
        try:
            if output_format == OutputFormat.MARKDOWN:
                response.markdown = self._convert_to_markdown(response, **kwargs)
            elif output_format == OutputFormat.HTML:
                response.html = self._convert_to_html(response, **kwargs)
            elif output_format == OutputFormat.JSON:
                response.json_data = self._convert_to_json(response, **kwargs)
            
            return response
            
        except Exception as e:
            logger.warning(f"Output formatting failed: {e}")
            return response
    
    def _convert_to_markdown(self, response: OCRResponse, **kwargs) -> str:
        """Converte resultado para Markdown"""
        try:
            if hasattr(response, 'markdown') and response.markdown:
                return response.markdown
            
            # Markdown básico baseado nos blocos
            markdown_parts = []
            
            if response.blocks:
                for block in response.blocks:
                    if not hasattr(block, 'text') or not block.text.strip():
                        continue
                    
                    block_type = getattr(block, 'type', 'text')
                    text = block.text.strip()
                    
                    if block_type in ['title', 'header']:
                        # Determinar nível do cabeçalho baseado no tamanho/posição
                        if len(text) < 30:
                            markdown_parts.append(f"# {text}")
                        else:
                            markdown_parts.append(f"## {text}")
                    elif block_type == 'list':
                        # Formatar como lista
                        lines = text.split('\n')
                        for line in lines:
                            if line.strip():
                                markdown_parts.append(f"- {line.strip()}")
                    else:
                        # Texto normal
                        markdown_parts.append(text)
            else:
                # Fallback para texto simples
                markdown_parts.append(response.text)
            
            return '\n\n'.join(markdown_parts)
            
        except Exception as e:
            logger.warning(f"Markdown conversion failed: {e}")
            return response.text
    
    def _convert_to_html(self, response: OCRResponse, **kwargs) -> str:
        """Converte resultado para HTML"""
        try:
            if hasattr(response, 'html') and response.html:
                return response.html
            
            html_parts = ['<div class="ocr-result">']
            
            if response.blocks:
                for block in response.blocks:
                    if not hasattr(block, 'text') or not block.text.strip():
                        continue
                    
                    block_type = getattr(block, 'type', 'text')
                    text = block.text.strip()
                    confidence = getattr(block, 'confidence', 1.0)
                    
                    css_class = f"ocr-block ocr-{block_type}"
                    confidence_class = "high" if confidence > 0.8 else "medium" if confidence > 0.5 else "low"
                    
                    if block_type in ['title', 'header']:
                        html_parts.append(f'<h2 class="{css_class} confidence-{confidence_class}">{text}</h2>')
                    elif block_type == 'list':
                        lines = text.split('\n')
                        html_parts.append('<ul class="ocr-list">')
                        for line in lines:
                            if line.strip():
                                html_parts.append(f'<li>{line.strip()}</li>')
                        html_parts.append('</ul>')
                    else:
                        html_parts.append(f'<p class="{css_class} confidence-{confidence_class}">{text}</p>')
            else:
                # Fallback para texto simples
                paragraphs = response.text.split('\n\n')
                for paragraph in paragraphs:
                    if paragraph.strip():
                        html_parts.append(f'<p>{paragraph.strip()}</p>')
            
            html_parts.append('</div>')
            
            return '\n'.join(html_parts)
            
        except Exception as e:
            logger.warning(f"HTML conversion failed: {e}")
            return f"<div class='ocr-result'><p>{response.text}</p></div>"
    
    def _convert_to_json(self, response: OCRResponse, **kwargs) -> Dict[str, Any]:
        """Converte resultado para JSON estruturado"""
        try:
            json_data = {
                "text": response.text,
                "confidence": response.confidence,
                "metadata": {
                    "engine": response.engine,
                    "processing_time": response.processing_time,
                    "timestamp": response.timestamp.isoformat() if hasattr(response, 'timestamp') else datetime.now().isoformat()
                },
                "blocks": [],
                "statistics": response.statistics.dict() if response.statistics else {}
            }
            
            # Adicionar blocos
            if response.blocks:
                for i, block in enumerate(response.blocks):
                    block_data = {
                        "id": i,
                        "text": getattr(block, 'text', ''),
                        "confidence": getattr(block, 'confidence', 1.0),
                        "type": getattr(block, 'type', 'text')
                    }
                    
                    # Adicionar bbox se disponível
                    if hasattr(block, 'bbox') and block.bbox:
                        if hasattr(block.bbox, 'dict'):
                            block_data["bbox"] = block.bbox.dict()
                        else:
                            block_data["bbox"] = block.bbox
                    
                    json_data["blocks"].append(block_data)
            
            return json_data
            
        except Exception as e:
            logger.warning(f"JSON conversion failed: {e}")
            return {"text": response.text, "error": str(e)}
    
    def _normalize_result_structure(self, response: OCRResponse) -> OCRResponse:
        """Normaliza estrutura do resultado"""
        try:
            # Garantir que campos obrigatórios existem
            if not hasattr(response, 'text') or response.text is None:
                response.text = ""
            
            if not hasattr(response, 'confidence') or response.confidence is None:
                response.confidence = 0.0
            
            if not hasattr(response, 'blocks'):
                response.blocks = []
            
            if not hasattr(response, 'processing_time'):
                response.processing_time = 0.0
            
            if not hasattr(response, 'engine'):
                response.engine = "unknown"
            
            # Validar valores
            response.confidence = max(0.0, min(1.0, response.confidence))
            response.processing_time = max(0.0, response.processing_time)
            
            return response
            
        except Exception as e:
            logger.warning(f"Result normalization failed: {e}")
            return response
    
    def _add_processing_metadata(self, response: OCRResponse, start_time: float) -> OCRResponse:
        """Adiciona metadados de processamento"""
        try:
            if not hasattr(response, 'metadata'):
                response.metadata = {}
            
            processing_metadata = {
                "post_processing_time": time.time() - start_time,
                "text_cleaned": self.enable_text_cleaning,
                "quality_scored": self.enable_quality_scoring,
                "processor_version": settings.VERSION
            }
            
            if hasattr(response, 'quality_score'):
                processing_metadata["quality_score"] = response.quality_score
            
            # Adicionar warnings se existem
            if hasattr(response, 'warnings') and response.warnings:
                processing_metadata["warnings"] = response.warnings
            
            response.metadata.update(processing_metadata)
            
            return response
            
        except Exception as e:
            logger.warning(f"Failed to add processing metadata: {e}")
            return response
    
    def _calculate_final_statistics(self, response: OCRResponse) -> OCRStatistics:
        """Calcula estatísticas finais"""
        try:
            text = response.text or ""
            blocks = response.blocks or []
            
            # Contar palavras e caracteres
            char_count = len(text)
            word_count = len(text.split()) if text else 0
            line_count = len(text.split('\n')) if text else 0
            
            # Estatísticas dos blocos
            total_blocks = len(blocks)
            confidences = [getattr(block, 'confidence', 1.0) for block in blocks if hasattr(block, 'confidence')]
            
            if confidences:
                avg_confidence = sum(confidences) / len(confidences)
                min_confidence = min(confidences)
                max_confidence = max(confidences)
            else:
                avg_confidence = response.confidence
                min_confidence = response.confidence
                max_confidence = response.confidence
            
            return OCRStatistics(
                total_blocks=total_blocks,
                avg_confidence=avg_confidence,
                min_confidence=min_confidence,
                max_confidence=max_confidence,
                char_count=char_count,
                word_count=word_count,
                line_count=line_count,
                processing_time=response.processing_time
            )
            
        except Exception as e:
            logger.warning(f"Statistics calculation failed: {e}")
            return OCRStatistics()
    
    def _aggregate_by_best_confidence(self, results: List[OCRResponse]) -> OCRResponse:
        """Agrega selecionando resultado com melhor confiança"""
        if not results:
            return self._create_error_result("No results to aggregate")
        
        best_result = max(results, key=lambda r: r.confidence)
        return best_result
    
    def _aggregate_by_weighted_average(self, results: List[OCRResponse]) -> OCRResponse:
        """Agrega usando média ponderada por confiança"""
        if not results:
            return self._create_error_result("No results to aggregate")
        
        if len(results) == 1:
            return results[0]
        
        # Usar o melhor resultado como base
        best_result = max(results, key=lambda r: r.confidence)
        aggregated = best_result
        
        # Calcular confiança média ponderada
        total_weight = sum(r.confidence for r in results)
        if total_weight > 0:
            weighted_confidence = sum(r.confidence * r.confidence for r in results) / total_weight
            aggregated.confidence = weighted_confidence
        
        return aggregated
    
    def _aggregate_by_consensus(self, results: List[OCRResponse]) -> OCRResponse:
        """Agrega usando consenso entre resultados"""
        if not results:
            return self._create_error_result("No results to aggregate")
        
        if len(results) == 1:
            return results[0]
        
        # Por simplicidade, usar resultado com maior confiança
        # Em implementação completa, compararia similaridade de texto
        best_result = max(results, key=lambda r: r.confidence)
        
        # Calcular confiança de consenso
        confidences = [r.confidence for r in results]
        consensus_confidence = sum(confidences) / len(confidences)
        best_result.confidence = consensus_confidence
        
        return best_result
    
    def _aggregate_by_longest_text(self, results: List[OCRResponse]) -> OCRResponse:
        """Agrega selecionando resultado com texto mais longo"""
        if not results:
            return self._create_error_result("No results to aggregate")
        
        longest_result = max(results, key=lambda r: len(r.text or ""))
        return longest_result
    
    def _aggregate_by_majority_vote(self, results: List[OCRResponse]) -> OCRResponse:
        """Agrega usando voto majoritário"""
        if not results:
            return self._create_error_result("No results to aggregate")
        
        if len(results) == 1:
            return results[0]
        
        # Implementação simples: usar resultado mais comum (por similaridade)
        # Por agora, usar melhor confiança
        return self._aggregate_by_best_confidence(results)
    
    def _add_aggregation_metadata(self, result: OCRResponse, original_results: List[OCRResponse], 
                                method: str, start_time: float) -> OCRResponse:
        """Adiciona metadados de agregação"""
        try:
            if not hasattr(result, 'metadata'):
                result.metadata = {}
            
            aggregation_info = {
                "aggregation_method": method,
                "source_engines": [r.engine for r in original_results],
                "source_confidences": [r.confidence for r in original_results],
                "aggregation_time": time.time() - start_time,
                "results_count": len(original_results)
            }
            
            result.metadata.update(aggregation_info)
            result.strategy = "multi_engine_aggregated"
            
            return result
            
        except Exception as e:
            logger.warning(f"Failed to add aggregation metadata: {e}")
            return result
    
    def _post_process_aggregated_result(self, result: OCRResponse, original_results: List[OCRResponse], **kwargs) -> OCRResponse:
        """Pós-processamento específico para resultados agregados"""
        try:
            # Combinar warnings de todos os resultados
            all_warnings = []
            for original in original_results:
                if hasattr(original, 'warnings') and original.warnings:
                    all_warnings.extend(original.warnings)
            
            if all_warnings:
                if not hasattr(result, 'warnings'):
                    result.warnings = []
                result.warnings.extend(all_warnings)
            
            # Melhorar qualidade baseado em múltiplas fontes
            if hasattr(result, 'quality_score'):
                result.quality_score = min(10.0, result.quality_score + 0.5)  # Bonus por agregação
            
            return result
            
        except Exception as e:
            logger.warning(f"Aggregated result post-processing failed: {e}")
            return result
    
    def _create_error_result(self, error_message: str) -> OCRResponse:
        """Cria resultado de erro"""
        return OCRResponse(
            text="",
            confidence=0.0,
            blocks=[],
            engine="error",
            processing_time=0.0,
            statistics=OCRStatistics(),
            warnings=[error_message]
        )
    
    def _record_processing_metrics(self, response: OCRResponse):
        """Registra métricas de processamento"""
        try:
            self.redis_client.increment_metric("result_processor_results_processed")
            
            # Métricas por engine
            if response.engine:
                self.redis_client.increment_metric("result_processor_by_engine", tags={"engine": response.engine})
            
            # Métricas de qualidade
            if hasattr(response, 'quality_score'):
                quality_level = "high" if response.quality_score > 7 else "medium" if response.quality_score > 4 else "low"
                self.redis_client.increment_metric("result_processor_quality", tags={"level": quality_level})
            
            # Métricas de tamanho de texto
            text_length = len(response.text or "")
            if text_length > 1000:
                size_category = "large"
            elif text_length > 100:
                size_category = "medium"
            else:
                size_category = "small"
            
            self.redis_client.increment_metric("result_processor_text_size", tags={"category": size_category})
            
        except Exception as e:
            logger.warning(f"Failed to record processing metrics: {e}")
    
    def get_processor_stats(self) -> Dict[str, Any]:
        """Retorna estatísticas do processador"""
        try:
            stats = {
                "results_processed": self.results_processed,
                "aggregations_performed": self.aggregations_performed,
                "quality_improvements": self.quality_improvements,
                "improvement_rate": 0.0,
                "configuration": {
                    "text_cleaning_enabled": self.enable_text_cleaning,
                    "quality_scoring_enabled": self.enable_quality_scoring,
                    "result_caching_enabled": self.enable_result_caching,
                    "min_confidence_threshold": self.min_confidence_threshold
                }
            }
            
            # Calcular taxa de melhoria
            if self.results_processed > 0:
                stats["improvement_rate"] = (self.quality_improvements / self.results_processed) * 100
            
            # Métricas do Redis
            try:
                stats["total_results_processed"] = self.redis_client.get_metric("result_processor_results_processed") or 0
                
                # Distribuição por engine
                engine_stats = {}
                for engine in ["trocr", "surya", "paddleocr", "easyocr", "tesseract", "marker"]:
                    count = self.redis_client.get_metric("result_processor_by_engine", tags={"engine": engine}) or 0
                    engine_stats[engine] = count
                stats["results_by_engine"] = engine_stats
                
                # Distribuição de qualidade
                quality_stats = {}
                for level in ["high", "medium", "low"]:
                    count = self.redis_client.get_metric("result_processor_quality", tags={"level": level}) or 0
                    quality_stats[level] = count
                stats["quality_distribution"] = quality_stats
                
            except Exception as e:
                logger.warning(f"Failed to get Redis metrics: {e}")
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get processor stats: {e}")
            return {"error": str(e)}


# Instância global do processador
result_processor = ResultProcessor()


def get_result_processor() -> ResultProcessor:
    """Retorna instância global do processador de resultados"""
    return result_processor


if __name__ == "__main__":
    """Teste do processador de resultados"""
    print("=== Result Processor Test ===")
    
    processor = get_result_processor()
    
    # Resultado de teste
    test_result = {
        "text": "Este é um texto de teste   com espaços extras.\n\nSegundo parágrafo.",
        "confidence": 0.85,
        "blocks": [
            {"text": "Este é um texto de teste", "confidence": 0.9},
            {"text": "com espaços extras.", "confidence": 0.8},
            {"text": "Segundo parágrafo.", "confidence": 0.85}
        ],
        "engine": "test_engine",
        "processing_time": 1.5
    }
    
    # Teste de processamento único
    processed = processor.process_single_result(test_result, 
                                              min_confidence=0.7,
                                              output_format=OutputFormat.MARKDOWN)
    
    print(f"Single result processing:")
    print(f"  Original text: {repr(test_result['text'][:50])}")
    print(f"  Processed text: {repr(processed.text[:50])}")
    print(f"  Quality score: {getattr(processed, 'quality_score', 'N/A')}")
    print(f"  Blocks: {len(processed.blocks)}")
    
    # Teste de agregação
    test_results = [
        test_result,
        {
            "text": "Este é um texto de teste com pequenas diferenças.",
            "confidence": 0.75,
            "blocks": [],
            "engine": "test_engine_2",
            "processing_time": 2.0
        }
    ]
    
    aggregated = processor.aggregate_multiple_results(test_results, method="best_confidence")
    print(f"\nAggregated result:")
    print(f"  Text: {repr(aggregated.text[:50])}")
    print(f"  Confidence: {aggregated.confidence:.2f}")
    print(f"  Strategy: {getattr(aggregated, 'strategy', 'N/A')}")
    
    # Estatísticas
    stats = processor.get_processor_stats()
    print(f"\nProcessor stats:")
    print(f"  Results processed: {stats.get('results_processed', 0)}")
    print(f"  Aggregations performed: {stats.get('aggregations_performed', 0)}")
    print(f"  Quality improvements: {stats.get('quality_improvements', 0)}")
    
    print("\n✅ Result Processor test completed")