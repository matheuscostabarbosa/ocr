#!/usr/bin/env python3
"""
Rotas de OCR - API Endpoints
============================

Endpoints principais para:
- Processamento de documentos únicos
- Processamento em lote
- Consulta de status de tasks
- Recuperação de resultados
"""

import asyncio
import tempfile
import uuid
from typing import Dict, Any, List, Optional, Union
from pathlib import Path
import json
import logging

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Query, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from app.core.config import settings
from app.core.redis_client import get_redis_client
from app.models.schemas import (
    OCRRequest, OCRResponse, BatchOCRRequest, BatchOCRResponse,
    TaskInfo, TaskStatus, OCREngine, OutputFormat, OCRParameters,
    ErrorResponse, FileInfo
)
from app.services.file_detector import FileTypeDetector
from app.workers.orchestrator_worker import orchestrate_ocr_task

logger = logging.getLogger(__name__)
router = APIRouter()

# Instâncias de serviços
file_detector = FileTypeDetector()
redis_client = get_redis_client()


async def save_uploaded_file(upload_file: UploadFile) -> str:
    """Salva arquivo enviado temporariamente"""
    try:
        # Criar arquivo temporário
        suffix = Path(upload_file.filename).suffix if upload_file.filename else ""
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            # Ler e salvar conteúdo
            content = await upload_file.read()
            tmp_file.write(content)
            return tmp_file.name
            
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}")
        raise HTTPException(status_code=500, detail="Failed to save file")


def validate_file_size(file_size: int) -> bool:
    """Valida tamanho do arquivo"""
    return file_size <= settings.MAX_FILE_SIZE


def validate_file_type(file_info: FileInfo) -> bool:
    """Valida tipo do arquivo"""
    return file_info.supported


async def cleanup_temp_file(file_path: str):
    """Limpa arquivo temporário"""
    try:
        Path(file_path).unlink(missing_ok=True)
    except Exception as e:
        logger.warning(f"Failed to cleanup temp file {file_path}: {e}")


@router.post(
    "/ocr",
    response_model=Union[OCRResponse, TaskInfo],
    summary="Process single document",
    description="""
    Processa um documento único com OCR.
    
    ## Parâmetros
    
    - **file**: Arquivo a ser processado
    - **engine**: Engine OCR (auto, trocr, surya, paddleocr, easyocr, tesseract, marker)
    - **output_format**: Formato de saída (text, markdown, json)
    - **async_processing**: Se deve processar de forma assíncrona
    - **languages**: Lista de idiomas (pt, en, es, etc.)
    - **parameters**: Parâmetros específicos do engine
    
    ## Engines Recomendados
    
    - **auto**: Escolha automática baseada no documento
    - **trocr**: Manuscritos e textos degradados
    - **surya**: Documentos com layout complexo
    - **paddleocr**: Processamento rápido em produção
    - **marker**: PDFs para conversão Markdown
    - **tesseract**: Fallback confiável
    
    ## Resposta
    
    - **Síncrono**: Retorna OCRResponse com resultado
    - **Assíncrono**: Retorna TaskInfo com task_id para consulta
    """
)
async def process_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Arquivo a ser processado"),
    engine: OCREngine = Form(OCREngine.AUTO, description="Engine OCR"),
    output_format: OutputFormat = Form(OutputFormat.TEXT, description="Formato de saída"),
    async_processing: bool = Form(False, description="Processamento assíncrono"),
    languages: Optional[str] = Form(None, description="Idiomas separados por vírgula (pt,en)"),
    min_confidence: float = Form(0.0, description="Confiança mínima", ge=0.0, le=1.0),
    enhance_contrast: bool = Form(False, description="Melhorar contraste"),
    use_cache: bool = Form(True, description="Usar cache"),
    priority: int = Form(5, description="Prioridade (1-10)", ge=1, le=10),
    parameters: Optional[str] = Form(None, description="Parâmetros JSON adicionais")
):
    """Processa documento único"""
    
    # Validar arquivo
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")
    
    if not validate_file_size(file.size):
        raise HTTPException(
            status_code=413, 
            detail=f"File too large. Max size: {settings.MAX_FILE_SIZE / (1024*1024):.1f}MB"
        )
    
    # Salvar arquivo
    file_path = await save_uploaded_file(file)
    
    try:
        # Detectar tipo de arquivo
        file_info = file_detector.detect_file_type(file_path)
        
        if not validate_file_type(file_info):
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported file type: {file_info.get('extension', 'unknown')}"
            )
        
        # Processar parâmetros
        ocr_params = {
            "languages": languages.split(",") if languages else None,
            "output_format": output_format,
            "min_confidence": min_confidence,
            "enhance_contrast": enhance_contrast,
            "use_cache": use_cache
        }
        
        # Adicionar parâmetros customizados
        if parameters:
            try:
                custom_params = json.loads(parameters)
                ocr_params.update(custom_params)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Invalid JSON in parameters")
        
        # Criar request
        ocr_request = OCRRequest(
            file_path=file_path,
            engine=engine,
            parameters=OCRParameters(**ocr_params),
            priority=priority,
            metadata={
                "original_filename": file.filename,
                "file_size": file.size,
                "file_info": file_info
            }
        )
        
        if async_processing:
            # Processamento assíncrono
            task = orchestrate_ocr_task.apply_async(
                args=[ocr_request.dict()],
                priority=priority
            )
            
            # Agendar limpeza do arquivo
            background_tasks.add_task(cleanup_temp_file, file_path)
            
            # Criar TaskInfo
            task_info = TaskInfo(
                task_id=task.id,
                status=TaskStatus.PENDING,
                engine=engine,
                queue="orchestrator_queue",
                priority=priority,
                created_at=datetime.now(),
                progress=0.0
            )
            
            # Salvar info da task no Redis
            redis_client.store_task_result(task.id, {
                "task_info": task_info.dict(),
                "original_filename": file.filename,
                "file_size": file.size
            })
            
            return task_info
        
        else:
            # Processamento síncrono
            try:
                result = orchestrate_ocr_task.apply_async(
                    args=[ocr_request.dict()],
                    priority=priority
                ).get(timeout=settings.WORKER_TASK_TIME_LIMIT)
                
                # Converter para OCRResponse
                response = OCRResponse(**result)
                
                # Adicionar informações do arquivo
                response.file_info = FileInfo(
                    filename=file.filename,
                    file_size=file.size,
                    **file_info
                )
                
                return response
                
            finally:
                # Limpar arquivo
                await cleanup_temp_file(file_path)
    
    except HTTPException:
        await cleanup_temp_file(file_path)
        raise
    except Exception as e:
        await cleanup_temp_file(file_path)
        logger.error(f"OCR processing failed: {e}")
        raise HTTPException(status_code=500, detail="OCR processing failed")


@router.post(
    "/batch",
    response_model=Union[BatchOCRResponse, TaskInfo],
    summary="Process multiple documents",
    description="""
    Processa múltiplos documentos em lote.
    
    ## Uso
    
    Envie múltiplos arquivos para processamento simultâneo ou sequencial.
    O sistema otimiza automaticamente a distribuição entre workers.
    
    ## Parâmetros
    
    - **files**: Lista de arquivos
    - **engine**: Engine para todos os arquivos
    - **parallel**: Processamento paralelo ou sequencial
    - **max_workers**: Número máximo de workers simultâneos
    
    ## Resposta
    
    - **Síncrono**: BatchOCRResponse com todos os resultados
    - **Assíncrono**: TaskInfo para monitoramento do lote
    """
)
async def process_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(..., description="Arquivos a processar"),
    engine: OCREngine = Form(OCREngine.AUTO, description="Engine OCR"),
    output_format: OutputFormat = Form(OutputFormat.TEXT, description="Formato de saída"),
    async_processing: bool = Form(True, description="Processamento assíncrono"),
    parallel: bool = Form(True, description="Processamento paralelo"),
    max_workers: int = Form(5, description="Máximo workers simultâneos", ge=1, le=20),
    languages: Optional[str] = Form(None, description="Idiomas separados por vírgula"),
    priority: int = Form(5, description="Prioridade", ge=1, le=10)
):
    """Processa múltiplos documentos"""
    
    if len(files) == 0:
        raise HTTPException(status_code=400, detail="No files provided")
    
    if len(files) > 50:  # Limite razoável
        raise HTTPException(status_code=400, detail="Too many files. Maximum 50 files per batch")
    
    # Salvar todos os arquivos
    file_paths = []
    total_size = 0
    
    try:
        for file in files:
            if not file.filename:
                raise HTTPException(status_code=400, detail="All files must have filenames")
            
            total_size += file.size
            if total_size > settings.MAX_FILE_SIZE * 10:  # 10x o limite individual
                raise HTTPException(status_code=413, detail="Batch total size too large")
            
            file_path = await save_uploaded_file(file)
            file_paths.append(file_path)
        
        # Criar parâmetros
        ocr_params = {
            "languages": languages.split(",") if languages else None,
            "output_format": output_format,
            "use_cache": True
        }
        
        # Criar batch request
        batch_request = BatchOCRRequest(
            file_paths=file_paths,
            engine=engine,
            parameters=OCRParameters(**ocr_params),
            priority=priority,
            metadata={
                "original_filenames": [f.filename for f in files],
                "file_sizes": [f.size for f in files],
                "parallel": parallel,
                "max_workers": max_workers
            }
        )
        
        if async_processing:
            # Criar tasks individuais
            task_ids = []
            
            if parallel:
                # Processamento paralelo
                tasks = []
                for i, file_path in enumerate(file_paths):
                    ocr_request = OCRRequest(
                        file_path=file_path,
                        engine=engine,
                        parameters=batch_request.parameters,
                        priority=priority,
                        metadata={
                            "batch_id": batch_request.batch_id,
                            "batch_index": i,
                            "original_filename": files[i].filename
                        }
                    )
                    
                    task = orchestrate_ocr_task.apply_async(
                        args=[ocr_request.dict()],
                        priority=priority
                    )
                    tasks.append(task)
                    task_ids.append(task.id)
            
            else:
                # Processamento sequencial
                for i, file_path in enumerate(file_paths):
                    ocr_request = OCRRequest(
                        file_path=file_path,
                        engine=engine,
                        parameters=batch_request.parameters,
                        priority=priority,
                        metadata={
                            "batch_id": batch_request.batch_id,
                            "batch_index": i,
                            "original_filename": files[i].filename,
                            "depends_on": task_ids[-1] if task_ids else None
                        }
                    )
                    
                    task = orchestrate_ocr_task.apply_async(
                        args=[ocr_request.dict()],
                        priority=priority
                    )
                    task_ids.append(task.id)
            
            # Salvar informações do lote
            batch_info = {
                "batch_id": batch_request.batch_id,
                "task_ids": task_ids,
                "total_files": len(files),
                "status": TaskStatus.PENDING,
                "created_at": datetime.now().isoformat(),
                "metadata": batch_request.metadata
            }
            
            redis_client.store_task_result(f"batch:{batch_request.batch_id}", batch_info)
            
            # Agendar limpeza
            for file_path in file_paths:
                background_tasks.add_task(cleanup_temp_file, file_path)
            
            return TaskInfo(
                task_id=batch_request.batch_id,
                status=TaskStatus.PENDING,
                engine=engine,
                queue="batch_processing",
                priority=priority,
                created_at=datetime.now(),
                progress=0.0
            )
        
        else:
            # Processamento síncrono
            results = []
            
            try:
                for i, file_path in enumerate(file_paths):
                    ocr_request = OCRRequest(
                        file_path=file_path,
                        engine=engine,
                        parameters=batch_request.parameters,
                        priority=priority,
                        metadata={
                            "original_filename": files[i].filename,
                            "batch_index": i
                        }
                    )
                    
                    result = orchestrate_ocr_task.apply_async(
                        args=[ocr_request.dict()],
                        priority=priority
                    ).get(timeout=settings.WORKER_TASK_TIME_LIMIT)
                    
                    # Converter para OCRResponse
                    response = OCRResponse(**result)
                    response.file_info = FileInfo(
                        filename=files[i].filename,
                        file_size=files[i].size
                    )
                    
                    results.append(response)
                
                # Criar resposta do lote
                batch_response = BatchOCRResponse(
                    batch_id=batch_request.batch_id,
                    total_files=len(files),
                    processed_files=len(results),
                    failed_files=0,
                    results=results,
                    summary={
                        "avg_confidence": sum(r.confidence for r in results) / len(results),
                        "total_chars": sum(len(r.text) for r in results),
                        "engines_used": list(set(r.engine for r in results))
                    },
                    total_processing_time=sum(r.processing_time for r in results)
                )
                
                return batch_response
                
            finally:
                # Limpar arquivos
                for file_path in file_paths:
                    await cleanup_temp_file(file_path)
    
    except HTTPException:
        # Limpar arquivos em caso de erro
        for file_path in file_paths:
            await cleanup_temp_file(file_path)
        raise
    except Exception as e:
        # Limpar arquivos em caso de erro
        for file_path in file_paths:
            await cleanup_temp_file(file_path)
        logger.error(f"Batch processing failed: {e}")
        raise HTTPException(status_code=500, detail="Batch processing failed")


@router.get(
    "/status/{task_id}",
    response_model=TaskInfo,
    summary="Get task status",
    description="Consulta status de uma task específica"
)
async def get_task_status(task_id: str):
    """Consulta status de uma task"""
    
    try:
        # Buscar no Redis primeiro
        task_data = redis_client.get_task_result(task_id)
        
        if task_data:
            return TaskInfo(**task_data.get("task_info", {}))
        
        # Buscar no Celery
        from app.core.celery_app import celery_app
        task = celery_app.AsyncResult(task_id)
        
        if task.state == "PENDING":
            status = TaskStatus.PENDING
        elif task.state == "STARTED":
            status = TaskStatus.PROCESSING
        elif task.state == "SUCCESS":
            status = TaskStatus.COMPLETED
        elif task.state == "FAILURE":
            status = TaskStatus.FAILED
        elif task.state == "RETRY":
            status = TaskStatus.RETRYING
        else:
            status = TaskStatus.PENDING
        
        task_info = TaskInfo(
            task_id=task_id,
            status=status,
            engine="unknown",
            queue="unknown",
            priority=5,
            created_at=datetime.now(),
            progress=1.0 if status == TaskStatus.COMPLETED else 0.0,
            result=OCRResponse(**task.result) if task.state == "SUCCESS" and task.result else None,
            error=str(task.info) if task.state == "FAILURE" else None
        )
        
        return task_info
        
    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        raise HTTPException(status_code=404, detail="Task not found")


@router.get(
    "/result/{task_id}",
    response_model=OCRResponse,
    summary="Get task result",
    description="Recupera resultado de uma task completada"
)
async def get_task_result(task_id: str):
    """Recupera resultado de uma task"""
    
    try:
        # Buscar resultado
        from app.core.celery_app import celery_app
        task = celery_app.AsyncResult(task_id)
        
        if task.state != "SUCCESS":
            if task.state == "PENDING":
                raise HTTPException(status_code=202, detail="Task still pending")
            elif task.state in ["STARTED", "RETRY"]:
                raise HTTPException(status_code=202, detail="Task still processing")
            elif task.state == "FAILURE":
                raise HTTPException(status_code=500, detail=f"Task failed: {task.info}")
            else:
                raise HTTPException(status_code=404, detail="Task not found")
        
        result = task.result
        if not result:
            raise HTTPException(status_code=404, detail="No result available")
        
        return OCRResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get task result: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve result")


@router.delete(
    "/task/{task_id}",
    summary="Cancel task",
    description="Cancela uma task pendente ou em processamento"
)
async def cancel_task(task_id: str):
    """Cancela uma task"""
    
    try:
        from app.core.celery_app import celery_app
        
        # Tentar cancelar task
        celery_app.control.revoke(task_id, terminate=True)
        
        # Limpar do Redis
        redis_client.delete_task_result(task_id)
        
        return {"message": "Task cancelled successfully", "task_id": task_id}
        
    except Exception as e:
        logger.error(f"Failed to cancel task: {e}")
        raise HTTPException(status_code=500, detail="Failed to cancel task")


@router.get(
    "/batch/{batch_id}",
    response_model=Dict[str, Any],
    summary="Get batch status",
    description="Consulta status de um lote de processamento"
)
async def get_batch_status(batch_id: str):
    """Consulta status de um lote"""
    
    try:
        # Buscar informações do lote
        batch_data = redis_client.get_task_result(f"batch:{batch_id}")
        
        if not batch_data:
            raise HTTPException(status_code=404, detail="Batch not found")
        
        task_ids = batch_data.get("task_ids", [])
        
        # Consultar status de cada task
        task_statuses = []
        completed_count = 0
        failed_count = 0
        
        for task_id in task_ids:
            try:
                task_info = await get_task_status(task_id)
                task_statuses.append({
                    "task_id": task_id,
                    "status": task_info.status,
                    "progress": task_info.progress
                })
                
                if task_info.status == TaskStatus.COMPLETED:
                    completed_count += 1
                elif task_info.status == TaskStatus.FAILED:
                    failed_count += 1
                    
            except Exception:
                task_statuses.append({
                    "task_id": task_id,
                    "status": TaskStatus.FAILED,
                    "progress": 0.0
                })
                failed_count += 1
        
        # Calcular progresso geral
        total_tasks = len(task_ids)
        overall_progress = completed_count / total_tasks if total_tasks > 0 else 0.0
        
        # Determinar status geral
        if completed_count == total_tasks:
            overall_status = TaskStatus.COMPLETED
        elif failed_count == total_tasks:
            overall_status = TaskStatus.FAILED
        elif completed_count + failed_count == total_tasks:
            overall_status = TaskStatus.COMPLETED  # Alguns falharam, mas todos terminaram
        else:
            overall_status = TaskStatus.PROCESSING
        
        return {
            "batch_id": batch_id,
            "status": overall_status,
            "progress": overall_progress,
            "total_tasks": total_tasks,
            "completed_tasks": completed_count,
            "failed_tasks": failed_count,
            "pending_tasks": total_tasks - completed_count - failed_count,
            "task_statuses": task_statuses,
            "metadata": batch_data.get("metadata", {})
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get batch status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get batch status")


@router.get(
    "/engines",
    response_model=Dict[str, Any],
    summary="List available engines",
    description="Lista engines OCR disponíveis e suas características"
)
async def list_engines():
    """Lista engines disponíveis"""
    
    try:
        from app.core.config import get_available_engines, get_engine_config
        
        available_engines = get_available_engines()
        engine_details = {}
        
        for engine in available_engines:
            config = get_engine_config(engine)
            engine_details[engine] = {
                "name": engine,
                "use_cases": config.get("use_cases", []),
                "accuracy_rating": config.get("accuracy_rating", 0),
                "avg_processing_time": config.get("avg_processing_time", 0),
                "gpu_required": config.get("gpu_memory_required", 0) > 0,
                "memory_required_gb": config.get("gpu_memory_required", 0),
                "enabled": config.get("enabled", False)
            }
        
        return {
            "available_engines": available_engines,
            "engine_details": engine_details,
            "recommendations": {
                "handwritten_text": "trocr",
                "complex_layout": "surya", 
                "fast_production": "paddleocr",
                "pdf_to_markdown": "marker",
                "general_purpose": "easyocr",
                "simple_fallback": "tesseract",
                "auto_selection": "auto"
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to list engines: {e}")
        raise HTTPException(status_code=500, detail="Failed to list engines")