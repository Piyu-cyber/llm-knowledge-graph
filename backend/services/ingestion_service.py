"""
OmniProf v3.0 — Multi-Format Ingestion Service
Handles PDF, DOCX, PPTX, and plain text file ingestion
"""

import os
import logging
from typing import Dict, Tuple
from pypdf import PdfReader

try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    from pptx import Presentation
    PPTX_AVAILABLE = True
except ImportError:
    PPTX_AVAILABLE = False

logger = logging.getLogger(__name__)


class MultiFormatExtractor:
    """Handles text extraction from multiple file formats"""
    
    # Supported file extensions
    SUPPORTED_FORMATS = {
        '.pdf': 'PDF',
        '.docx': 'DOCX',
        '.doc': 'DOC',
        '.pptx': 'PPTX',
        '.ppt': 'PPT',
        '.txt': 'Text'
    }
    
    @staticmethod
    def get_file_format(file_path: str) -> str:
        """Determine file format from extension"""
        _, ext = os.path.splitext(file_path.lower())
        return MultiFormatExtractor.SUPPORTED_FORMATS.get(ext, None)
    
    @staticmethod
    def extract_from_pdf(file_path: str) -> str:
        """Extract text from PDF files"""
        try:
            reader = PdfReader(file_path)
            text_chunks = []
            
            for i, page in enumerate(reader.pages):
                try:
                    extracted = page.extract_text()
                    if extracted:
                        text_chunks.append(extracted)
                except Exception as e:
                    logger.warning(f"⚠️ Skipping page {i}: {str(e)}")
            
            if not text_chunks:
                raise ValueError("No text could be extracted from any page")
            
            full_text = "\n".join(text_chunks)
            return full_text.strip()
        
        except Exception as e:
            raise Exception(f"PDF extraction failed: {str(e)}")
    
    @staticmethod
    def extract_from_docx(file_path: str) -> str:
        """Extract text from DOCX files"""
        if not DOCX_AVAILABLE:
            raise Exception("python-docx not installed. Run: pip install python-docx")
        
        try:
            doc = Document(file_path)
            text_chunks = []
            
            # Extract from paragraphs
            for paragraph in doc.paragraphs:
                if paragraph.text.strip():
                    text_chunks.append(paragraph.text)
            
            # Extract from tables
            for table in doc.tables:
                for row in table.rows:
                    row_text = []
                    for cell in row.cells:
                        if cell.text.strip():
                            row_text.append(cell.text.strip())
                    if row_text:
                        text_chunks.append(" | ".join(row_text))
            
            if not text_chunks:
                raise ValueError("No text could be extracted from document")
            
            full_text = "\n".join(text_chunks)
            return full_text.strip()
        
        except Exception as e:
            raise Exception(f"DOCX extraction failed: {str(e)}")
    
    @staticmethod
    def extract_from_pptx(file_path: str) -> str:
        """Extract text from PPTX (PowerPoint) files"""
        if not PPTX_AVAILABLE:
            raise Exception("python-pptx not installed. Run: pip install python-pptx")
        
        try:
            prs = Presentation(file_path)
            text_chunks = []
            
            for slide_num, slide in enumerate(prs.slides, 1):
                # Add slide number as section marker
                text_chunks.append(f"\n--- Slide {slide_num} ---\n")
                
                # Extract from shapes
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        text_chunks.append(shape.text)
                    elif hasattr(shape, "table"):
                        # Handle tables in slides
                        table = shape.table
                        for row in table.rows:
                            row_text = []
                            for cell in row.cells:
                                if cell.text.strip():
                                    row_text.append(cell.text.strip())
                            if row_text:
                                text_chunks.append(" | ".join(row_text))
            
            if len(text_chunks) <= len(prs.slides):  # Only slide markers, no content
                raise ValueError("No text could be extracted from slides")
            
            full_text = "\n".join(text_chunks)
            return full_text.strip()
        
        except Exception as e:
            raise Exception(f"PPTX extraction failed: {str(e)}")
    
    @staticmethod
    def extract_from_txt(file_path: str) -> str:
        """Extract text from plain text files"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                text = f.read().strip()
            
            if not text:
                raise ValueError("Text file is empty")
            
            return text
        
        except UnicodeDecodeError:
            # Try with different encoding
            try:
                with open(file_path, 'r', encoding='latin-1') as f:
                    text = f.read().strip()
                return text
            except Exception as e:
                raise Exception(f"Text file extraction failed: {str(e)}")
    
    @staticmethod
    def extract_text(file_path: str) -> Tuple[str, str]:
        """
        Extract text from any supported file format.
        
        Args:
            file_path: Path to the file
        
        Returns:
            Tuple of (text, file_format)
        
        Raises:
            Exception if format not supported or extraction fails
        """
        file_format = MultiFormatExtractor.get_file_format(file_path)
        
        if not file_format:
            raise Exception(
                f"Unsupported file format. Supported: {', '.join(MultiFormatExtractor.SUPPORTED_FORMATS.keys())}"
            )
        
        if file_format == 'PDF':
            text = MultiFormatExtractor.extract_from_pdf(file_path)
        elif file_format in ['DOCX', 'DOC']:
            text = MultiFormatExtractor.extract_from_docx(file_path)
        elif file_format in ['PPTX', 'PPT']:
            text = MultiFormatExtractor.extract_from_pptx(file_path)
        elif file_format == 'Text':
            text = MultiFormatExtractor.extract_from_txt(file_path)
        else:
            raise Exception(f"Unsupported format: {file_format}")
        
        return text, file_format


class IngestionService:
    """Handles document ingestion and knowledge extraction"""
    
    def __init__(self, llm_service, rag_service, graph_service):
        self.llm_service = llm_service
        self.rag_service = rag_service
        self.graph_service = graph_service
        self.extractor = MultiFormatExtractor()
    
    def _normalize_text(self, text: str) -> str:
        """Clean and normalize extracted text"""
        # Remove excessive whitespace
        text = "\n".join(line.strip() for line in text.split("\n") if line.strip())
        # Limit length for LLM processing
        MAX_CHARS = 15000
        return text[:MAX_CHARS]
    
    def _clean_text(self, value):
        """Clean text values"""
        if not value:
            return ""
        
        value = value.strip()
        
        # Remove common prefixes
        if value.lower().startswith("name:"):
            value = value.split(":", 1)[1].strip()
        
        return value
    
    def ingest(self, file_path: str, course_owner: str = "system") -> Dict:
        """
        Ingest a document in any supported format.
        
        Args:
            file_path: Path to the document
            course_owner: Course owner ID for hierarchy
        
        Returns:
            Dict with ingestion results including validation errors
        """
        try:
            # Step 1: Reset RAG
            self.rag_service.reset()
            
            # Step 2: Extract text from file
            logger.info(f"Extracting text from {file_path}")
            text, file_format = self.extractor.extract_text(file_path)
            
            if not text:
                raise ValueError("No text extracted from document")
            
            # Step 3: Normalize text
            text = self._normalize_text(text)
            
            # Step 4: Extract hierarchical concepts using LLM
            logger.info("Extracting hierarchical concepts using LLM")
            llm_data = self.llm_service.extract_concepts_hierarchical(text)
            
            if not llm_data or not llm_data.get("nodes"):
                return {
                    "status": "error",
                    "message": "Failed to extract concepts from document"
                }
            
            # Step 5: Insert into graph with hierarchical structure
            logger.info("Inserting into knowledge graph")
            insert_result = self.graph_service.insert_from_llm_hierarchical(
                data=llm_data,
                course_owner=course_owner,
                source_doc=os.path.basename(file_path),
                file_format=file_format
            )
            
            if insert_result["status"] != "success":
                return insert_result
            
            # Step 6: Validate graph integrity
            logger.info("Validating graph integrity")
            validation_result = self.graph_service.validate_graph()
            
            # Step 7: Store full text in RAG
            try:
                self.rag_service.ingest_documents(text)
                logger.info("Text stored in RAG system")
            except Exception as e:
                logger.warning(f"⚠️ RAG ingestion failed: {str(e)}")
            
            # Return results with validation info
            return {
                "status": "success",
                "file_format": file_format,
                "concepts_added": insert_result.get("concepts_added", 0),
                "relationships_added": insert_result.get("relationships_added", 0),
                "facts_added": insert_result.get("facts_added", 0),
                "modules_added": insert_result.get("modules_added", 0),
                "topics_added": insert_result.get("topics_added", 0),
                "validation": {
                    "is_valid": validation_result["status"] == "valid",
                    "issue_count": validation_result.get("issue_count", 0),
                    "issues": validation_result.get("issues", [])
                }
            }
        
        except Exception as e:
            logger.error(f"Ingestion error: {str(e)}")
            return {
                "status": "error",
                "message": str(e)
            }
