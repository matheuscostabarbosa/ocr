#!/usr/bin/env python3
"""
Marker Worker - PDF para Markdown
=================================

Worker especializado para conversão de PDF para Markdown usando Marker.
Ideal para:
- Documentos acadêmicos e científicos
- PDFs com estrutura complexa
- Preservação de tabelas e equações
- Conversão de alta qualidade para Markdown
"""

import time
import tempfile
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
import fitz  # PyMuPDF

from app.workers.base_worker import BaseOCRWorker
from app.core.celery_app import celery_app
from app.core.config import settings, get_engine_config
from app.models.schemas import OCRRequest, OCRResponse

try:
    from marker.convert import convert_single_pdf
    from marker.models import load_all_models
    MARKER_AVAILABLE = True
except ImportError:
    MARKER_AVAILABLE = False


class MarkerWorker(BaseOCRWorker):
    """Worker Marker para conversão PDF→Markdown"""
    
    def __init__(self):
        super().__init__()
        self.engine_name = "marker"
        self.config = get_engine_config(self.engine_name)
        
        # Configurações Marker
        self.max_pages = self.config.get("max_pages", None)
        self.use_llm = self.config.get("use_llm", False)
        self.extract_images = self.config.get("extract_images", True)
        
        if not MARKER_AVAILABLE:
            raise ImportError("Marker dependencies not available. Install with: pip install marker-pdf")
    
    def load_model(self):
        """Carrega modelos Marker"""
        try:
            self.logger.info("Loading Marker models...")
            
            # Carregar todos os modelos necessários
            self.models = load_all_models()
            
            self.logger.info("Marker models loaded successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to load Marker models: {e}")
            raise
    
    def process_image(self, image_path: str, **kwargs) -> Dict[str, Any]:
        """Marker é específico para PDFs, mas pode processar imagens convertendo para PDF"""
        try:
            # Converter imagem para PDF temporário
            pdf_path = self._image_to_pdf(image_path)
            
            try:
                # Processar como PDF
                return self.process_pdf(pdf_path, **kwargs)
            finally:
                # Limpar PDF temporário
                try:
                    import os
                    os.unlink(pdf_path)
                except Exception:
                    pass
                    
        except Exception as e:
            self.logger.error(f"Marker image processing failed: {e}")
            raise
    
    def process_pdf(self, pdf_path: str, **kwargs) -> Dict[str, Any]:
        """Processa PDF com Marker"""
        try:
            start_time = time.time()
            
            # Analisar PDF primeiro
            pdf_info = self._analyze_pdf(pdf_path)
            
            # Aplicar filtros baseados nos parâmetros
            processed_pdf_path = self._preprocess_pdf(pdf_path, pdf_info, **kwargs)
            
            try:
                # Configurar parâmetros do Marker
                marker_kwargs = self._build_marker_config(**kwargs)
                
                # Executar conversão
                full_text, images, metadata = convert_single_pdf(
                    processed_pdf_path, 
                    self.models,
                    **marker_kwargs
                )
                
                # Processar resultado
                result = self._process_marker_result(
                    full_text, images, metadata, pdf_info, **kwargs
                )
                
                result['processing_time'] = time.time() - start_time
                return result
                
            finally:
                # Limpar arquivo temporário se foi criado
                if processed_pdf_path != pdf_path:
                    try:
                        import os
                        os.unlink(processed_pdf_path)
                    except Exception:
                        pass
                        
        except Exception as e:
            self.logger.error(f"Marker PDF processing failed: {e}")
            raise
    
    def _image_to_pdf(self, image_path: str) -> str:
        """Converte imagem para PDF temporário"""
        try:
            from PIL import Image
            
            # Carregar imagem
            with Image.open(image_path) as img:
                # Converter para RGB se necessário
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Criar PDF temporário
                with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                    img.save(tmp_file.name, 'PDF', quality=95)
                    return tmp_file.name
                    
        except Exception as e:
            self.logger.error(f"Image to PDF conversion failed: {e}")
            raise
    
    def _analyze_pdf(self, pdf_path: str) -> Dict[str, Any]:
        """Analisa PDF para otimizar processamento"""
        try:
            doc = fitz.open(pdf_path)
            
            analysis = {
                "total_pages": len(doc),
                "file_size": Path(pdf_path).stat().st_size,
                "has_text": False,
                "has_images": False,
                "has_tables": False,
                "estimated_complexity": "medium",
                "page_dimensions": [],
                "text_coverage": 0.0
            }
            
            total_text_length = 0
            pages_with_text = 0
            pages_with_images = 0
            
            # Analisar cada página (limite para performance)
            sample_pages = min(10, len(doc))
            for page_num in range(0, min(sample_pages, len(doc)), max(1, len(doc) // sample_pages)):
                page = doc.load_page(page_num)
                
                # Dimensões da página
                rect = page.rect
                analysis["page_dimensions"].append({
                    "width": rect.width,
                    "height": rect.height,
                    "page": page_num
                })
                
                # Analisar texto
                text = page.get_text()
                if text.strip():
                    analysis["has_text"] = True
                    total_text_length += len(text)
                    pages_with_text += 1
                
                # Analisar imagens
                image_list = page.get_images()
                if image_list:
                    analysis["has_images"] = True
                    pages_with_images += 1
                
                # Heurística simples para detectar tabelas
                if "table" in text.lower() or text.count("|") > 5 or text.count("\t") > 10:
                    analysis["has_tables"] = True
            
            doc.close()
            
            # Calcular métricas
            analysis["text_coverage"] = pages_with_text / min(sample_pages, len(doc))
            analysis["image_density"] = pages_with_images / min(sample_pages, len(doc))
            analysis["avg_text_per_page"] = total_text_length / pages_with_text if pages_with_text > 0 else 0
            
            # Estimar complexidade
            complexity_score = 0
            if analysis["has_tables"]:
                complexity_score += 2
            if analysis["has_images"]:
                complexity_score += 1
            if analysis["total_pages"] > 50:
                complexity_score += 2
            if analysis["avg_text_per_page"] > 3000:
                complexity_score += 1
            
            if complexity_score >= 4:
                analysis["estimated_complexity"] = "high"
            elif complexity_score <= 1:
                analysis["estimated_complexity"] = "low"
            
            return analysis
            
        except Exception as e:
            self.logger.warning(f"PDF analysis failed: {e}")
            return {
                "total_pages": 0,
                "estimated_complexity": "medium",
                "has_text": True,
                "has_images": False,
                "has_tables": False
            }
    
    def _preprocess_pdf(self, pdf_path: str, pdf_info: Dict[str, Any], **kwargs) -> str:
        """Pré-processa PDF se necessário"""
        try:
            # Verificar se precisa de pré-processamento
            needs_processing = False
            
            # Extrair páginas específicas se solicitado
            page_range = kwargs.get('page_range', None)
            if page_range:
                needs_processing = True
            
            # Limitar número de páginas se especificado
            max_pages = kwargs.get('max_pages', self.max_pages)
            if max_pages and pdf_info.get("total_pages", 0) > max_pages:
                needs_processing = True
                page_range = f"0-{max_pages-1}"
            
            if not needs_processing:
                return pdf_path
            
            # Processar PDF
            doc = fitz.open(pdf_path)
            new_doc = fitz.open()  # Novo documento
            
            # Determinar páginas a processar
            if page_range:
                pages_to_process = self._parse_page_range(page_range, len(doc))
            else:
                pages_to_process = list(range(min(max_pages or len(doc), len(doc))))
            
            # Copiar páginas selecionadas
            for page_num in pages_to_process:
                if page_num < len(doc):
                    new_doc.insert_pdf(doc, from_page=page_num, to_page=page_num)
            
            # Salvar PDF processado
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_file:
                new_doc.save(tmp_file.name)
                processed_path = tmp_file.name
            
            doc.close()
            new_doc.close()
            
            return processed_path
            
        except Exception as e:
            self.logger.warning(f"PDF preprocessing failed: {e}")
            return pdf_path
    
    def _parse_page_range(self, page_range: str, total_pages: int) -> List[int]:
        """Parseia range de páginas (ex: '1,3-5,10')"""
        try:
            pages = []
            
            for part in page_range.split(','):
                part = part.strip()
                
                if '-' in part:
                    # Range de páginas
                    start, end = part.split('-', 1)
                    start = int(start.strip())
                    end = int(end.strip())
                    pages.extend(range(start, min(end + 1, total_pages)))
                else:
                    # Página única
                    page = int(part)
                    if page < total_pages:
                        pages.append(page)
            
            return sorted(list(set(pages)))  # Remove duplicatas e ordena
            
        except Exception as e:
            self.logger.warning(f"Page range parsing failed: {e}")
            return list(range(total_pages))
    
    def _build_marker_config(self, **kwargs) -> Dict[str, Any]:
        """Constrói configuração para o Marker"""
        config = {}
        
        # Configurações básicas
        config["max_pages"] = kwargs.get('max_pages', self.max_pages)
        config["langs"] = kwargs.get('languages', None)
        config["batch_multiplier"] = kwargs.get('batch_multiplier', 2)
        
        # Configurações de qualidade
        if kwargs.get('use_llm', self.use_llm):
            config["use_llm"] = True
        
        # Configurações de extração
        config["extract_images"] = kwargs.get('extract_images', self.extract_images)
        
        # Configurações de formato
        config["paginate_output"] = kwargs.get('paginate_output', False)
        config["output_format"] = kwargs.get('output_format', 'markdown')
        
        return {k: v for k, v in config.items() if v is not None}
    
    def _process_marker_result(self, markdown_text: str, images: Dict, metadata: Dict, 
                             pdf_info: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Processa resultado do Marker"""
        try:
            result = {
                "text": markdown_text,
                "markdown": markdown_text,
                "confidence": 0.95,  # Marker geralmente tem alta qualidade
                "blocks": [],
                "images": images,
                "metadata": metadata,
                "pdf_info": pdf_info
            }
            
            # Processar estrutura do markdown
            if kwargs.get('analyze_structure', True):
                result["structure"] = self._analyze_markdown_structure(markdown_text)
            
            # Extrair blocos do markdown
            if kwargs.get('extract_blocks', True):
                result["blocks"] = self._extract_markdown_blocks(markdown_text)
            
            # Gerar texto plano se solicitado
            if kwargs.get('include_plain_text', True):
                result["plain_text"] = self._markdown_to_plain_text(markdown_text)
            
            # Estatísticas
            result["statistics"] = self._calculate_markdown_statistics(markdown_text, result.get("structure", {}))
            
            # Validar qualidade
            result["quality_score"] = self._assess_conversion_quality(result, pdf_info)
            
            return result
            
        except Exception as e:
            self.logger.error(f"Marker result processing failed: {e}")
            raise
    
    def _analyze_markdown_structure(self, markdown_text: str) -> Dict[str, Any]:
        """Analisa estrutura do markdown"""
        try:
            structure = {
                "headers": [],
                "tables": 0,
                "code_blocks": 0,
                "lists": 0,
                "links": 0,
                "images": 0,
                "equations": 0
            }
            
            lines = markdown_text.split('\n')
            in_code_block = False
            
            for i, line in enumerate(lines):
                line = line.strip()
                
                # Headers
                if line.startswith('#'):
                    level = len(line) - len(line.lstrip('#'))
                    header_text = line.lstrip('#').strip()
                    structure["headers"].append({
                        "level": level,
                        "text": header_text,
                        "line": i + 1
                    })
                
                # Code blocks
                if line.startswith('```'):
                    if in_code_block:
                        structure["code_blocks"] += 1
                    in_code_block = not in_code_block
                
                # Tables
                if '|' in line and not in_code_block:
                    # Verificar se é uma linha de tabela válida
                    if line.startswith('|') and line.endswith('|'):
                        structure["tables"] += 1
                
                # Lists
                if line.startswith(('- ', '* ', '+ ')) or (line.startswith(tuple(f'{i}. ' for i in range(10)))):
                    structure["lists"] += 1
                
                # Links
                structure["links"] += line.count('](')
                
                # Images
                structure["images"] += line.count('![')
                
                # Equations (LaTeX)
                structure["equations"] += line.count('$')
            
            return structure
            
        except Exception as e:
            self.logger.warning(f"Structure analysis failed: {e}")
            return {}
    
    def _extract_markdown_blocks(self, markdown_text: str) -> List[Dict[str, Any]]:
        """Extrai blocos estruturados do markdown"""
        try:
            blocks = []
            lines = markdown_text.split('\n')
            current_block = None
            
            for i, line in enumerate(lines):
                original_line = line
                line = line.strip()
                
                # Header
                if line.startswith('#'):
                    if current_block:
                        blocks.append(current_block)
                    
                    level = len(line) - len(line.lstrip('#'))
                    header_text = line.lstrip('#').strip()
                    
                    current_block = {
                        "type": "header",
                        "level": level,
                        "text": header_text,
                        "content": [original_line],
                        "start_line": i + 1,
                        "confidence": 0.95
                    }
                
                # Paragraph or continuation
                elif line:
                    if current_block:
                        current_block["content"].append(original_line)
                    else:
                        current_block = {
                            "type": "paragraph",
                            "text": line,
                            "content": [original_line],
                            "start_line": i + 1,
                            "confidence": 0.9
                        }
                
                # Empty line - end current block
                elif current_block:
                    current_block["text"] = "\n".join(current_block["content"])
                    blocks.append(current_block)
                    current_block = None
            
            # Add last block
            if current_block:
                current_block["text"] = "\n".join(current_block["content"])
                blocks.append(current_block)
            
            return blocks
            
        except Exception as e:
            self.logger.warning(f"Block extraction failed: {e}")
            return []
    
    def _markdown_to_plain_text(self, markdown_text: str) -> str:
        """Converte markdown para texto plano"""
        try:
            # Implementação simples - para algo mais robusto, usar biblioteca como markdown
            import re
            
            text = markdown_text
            
            # Remover headers
            text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
            
            # Remover links mas manter texto
            text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
            
            # Remover imagens
            text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
            
            # Remover código inline
            text = re.sub(r'`([^`]+)`', r'\1', text)
            
            # Remover blocos de código
            text = re.sub(r'```[\s\S]*?```', '', text)
            
            # Remover formatação de lista
            text = re.sub(r'^\s*[-*+]\s*', '', text, flags=re.MULTILINE)
            text = re.sub(r'^\s*\d+\.\s*', '', text, flags=re.MULTILINE)
            
            # Remover formatação de tabela
            text = re.sub(r'\|', ' ', text)
            text = re.sub(r'^[-\s:]+$', '', text, flags=re.MULTILINE)
            
            # Limpar espaços extras
            text = re.sub(r'\n\s*\n', '\n\n', text)
            text = re.sub(r'[ \t]+', ' ', text)
            
            return text.strip()
            
        except Exception as e:
            self.logger.warning(f"Markdown to plain text conversion failed: {e}")
            return markdown_text
    
    def _calculate_markdown_statistics(self, markdown_text: str, structure: Dict[str, Any]) -> Dict[str, Any]:
        """Calcula estatísticas do markdown"""
        try:
            return {
                "char_count": len(markdown_text),
                "word_count": len(markdown_text.split()),
                "line_count": len(markdown_text.split('\n')),
                "header_count": len(structure.get("headers", [])),
                "table_count": structure.get("tables", 0),
                "code_block_count": structure.get("code_blocks", 0),
                "list_item_count": structure.get("lists", 0),
                "link_count": structure.get("links", 0),
                "image_count": structure.get("images", 0),
                "equation_count": structure.get("equations", 0)
            }
            
        except Exception:
            return {
                "char_count": len(markdown_text),
                "word_count": len(markdown_text.split()),
                "line_count": len(markdown_text.split('\n'))
            }
    
    def _assess_conversion_quality(self, result: Dict[str, Any], pdf_info: Dict[str, Any]) -> float:
        """Avalia qualidade da conversão"""
        try:
            score = 8.0  # Base score para Marker (geralmente alta qualidade)
            
            # Verificar se há conteúdo
            if not result.get("text", "").strip():
                return 0.0
            
            # Bonificar estrutura detectada
            structure = result.get("structure", {})
            if structure.get("headers"):
                score += 0.5
            if structure.get("tables", 0) > 0:
                score += 0.3
            if structure.get("equations", 0) > 0:
                score += 0.2
            
            # Verificar consistência com PDF
            expected_pages = pdf_info.get("total_pages", 1)
            if expected_pages > 1:
                # Verificar se markdown tem separação de páginas ou estrutura
                if "---" in result["text"] or len(structure.get("headers", [])) > 1:
                    score += 0.3
            
            # Penalizar se muito pouco texto para o tamanho do PDF
            text_length = len(result.get("plain_text", result.get("text", "")))
            expected_min_chars = expected_pages * 200  # Estimativa mínima
            if text_length < expected_min_chars * 0.5:
                score -= 1.0
            
            return max(0.0, min(10.0, score))
            
        except Exception:
            return 7.0  # Score padrão


# Registrar tasks Celery
@celery_app.task(bind=True, base=MarkerWorker, queue='marker_queue')
def marker_process_pdf(self, request_data: dict):
    """Task para processar PDF com Marker"""
    request = OCRRequest(**request_data)
    
    # Marker é específico para PDFs
    if request.file_path.lower().endswith('.pdf'):
        worker = MarkerWorker()
        worker._ensure_model_loaded()
        result = worker.process_pdf(request.file_path, **request.parameters)
    else:
        # Para outros formatos, usar process_image (que converte para PDF)
        response = worker.execute_ocr(request)
        result = response.dict()
    
    return result


@celery_app.task(bind=True, base=MarkerWorker, queue='marker_queue')
def marker_analyze_pdf(self, pdf_path: str):
    """Task para analisar PDF sem processamento completo"""
    worker = MarkerWorker()
    worker.load_model()
    
    analysis = worker._analyze_pdf(pdf_path)
    return analysis


@celery_app.task(bind=True, base=MarkerWorker, queue='marker_queue')
def marker_health_check(self):
    """Task para verificar saúde do Marker"""
    return self.health_check()


# Configurações específicas do worker
def configure_marker_worker():
    """Configura worker Marker"""
    config = get_engine_config("marker")
    
    return {
        "queue": "marker_queue",
        "concurrency": config.get("max_workers", 4),
        "prefetch_multiplier": 1,  # Processamento intensivo
        "max_tasks_per_child": 50,  # Reiniciar periodicamente para evitar vazamentos
    }


if __name__ == "__main__":
    """Teste do worker Marker"""
    import os
    
    print("=== Marker Worker Test ===")
    
    if not MARKER_AVAILABLE:
        print("❌ Marker dependencies not available")
        exit(1)
    
    worker = MarkerWorker()
    
    # Teste de carregamento do modelo
    try:
        worker.load_model()
        print("✅ Models loaded successfully")
    except Exception as e:
        print(f"❌ Model loading failed: {e}")
        exit(1)
    
    # Teste de health check
    health = worker.health_check()
    print(f"Health status: {health['status']}")
    
    # Teste com PDF de exemplo
    test_pdf_path = "test_document.pdf"
    if os.path.exists(test_pdf_path):
        print(f"\n--- Testing with {test_pdf_path} ---")
        
        # Análise do PDF
        analysis = worker._analyze_pdf(test_pdf_path)
        print(f"PDF pages: {analysis.get('total_pages', 0)}")
        print(f"Has text: {analysis.get('has_text', False)}")
        print(f"Has tables: {analysis.get('has_tables', False)}")
        print(f"Complexity: {analysis.get('estimated_complexity', 'unknown')}")
        
        # Processamento
        request = OCRRequest(
            file_path=test_pdf_path,
            engine="marker",
            parameters={
                "max_pages": 5,
                "extract_images": True,
                "analyze_structure": True,
                "include_plain_text": True
            }
        )
        
        try:
            result = worker.process_pdf(test_pdf_path, **request.parameters)
            print(f"✅ PDF processing successful")
            print(f"Markdown length: {len(result.get('markdown', ''))}")
            print(f"Quality score: {result.get('quality_score', 0):.1f}")
            print(f"Processing time: {result.get('processing_time', 0):.2f}s")
            
            structure = result.get('structure', {})
            if structure:
                print(f"Headers: {len(structure.get('headers', []))}")
                print(f"Tables: {structure.get('tables', 0)}")
                print(f"Images: {structure.get('images', 0)}")
                
        except Exception as e:
            print(f"❌ PDF processing failed: {e}")
    else:
        print(f"⚠️  Test PDF {test_pdf_path} not found")
    
    print("\n✅ Marker Worker test completed")