"""
Investigation Pipeline - Main analysis logic
Pure logic, no UI code
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import json

@dataclass
class InvestigationResult:
    """Investigation ka final result"""
    case_id: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Evidence
    entities: Dict = field(default_factory=dict)
    ocr_text: str = ""
    face_result: Dict = field(default_factory=dict)
    voice_result: Dict = field(default_factory=dict)
    
    # Analysis
    deception_score: float = 0.0
    risk_score: float = 0.0
    credibility_score: float = 0.0
    
    # Intelligence
    watchlist: Dict = field(default_factory=dict)
    mo_links: Dict = field(default_factory=dict)
    unidentified_leads: Dict = field(default_factory=dict)
    
    # Reasoning
    reasoning: Dict = field(default_factory=dict)
    threat: Dict = field(default_factory=dict)
    actions: List = field(default_factory=list)
    
    # Report
    report_text: str = ""
    report_data: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        return {
            'case_id': self.case_id,
            'timestamp': self.timestamp,
            'deception_score': self.deception_score,
            'risk_score': self.risk_score,
            'credibility_score': self.credibility_score,
            'entities': self.entities,
            'ocr_text': self.ocr_text[:500],
            'face_result': self.face_result,
            'voice_result': self.voice_result,
            'watchlist': self.watchlist,
            'mo_links': self.mo_links,
            'unidentified_leads': self.unidentified_leads,
            'reasoning': self.reasoning,
            'threat': self.threat,
            'actions': self.actions[:5],
            'report_text': self.report_text[:1000],
        }


class InvestigationPipeline:
    """Main investigation pipeline"""
    
    def __init__(self):
        self._init_services()
    
    def _init_services(self):
        """All services initialize karega"""
        self.services_ready = False
        try:
            # Service imports - lazy loading
            from services.ner_service import NERService
            from services.voice_service import VoiceService
            from services.face_service import FaceService
            from services.ocr_service import OCRService
            from services.risk_engine import RiskEngine
            from services.fuzzy_match import FuzzyMatcher
            
            self.ner = NERService()
            self.voice = VoiceService()
            self.face = FaceService()
            self.ocr = OCRService()
            self.risk = RiskEngine()
            self.matcher = FuzzyMatcher()
            self.services_ready = True
        except Exception as e:
            print(f"⚠️ Service initialization warning: {e}")
    
    def run(self, 
            case_id: str,
            modus: str,
            suspect_name: str,
            location: str,
            files: Dict,
            unidentified_flag: bool = False,
            physical_desc: str = "",
            case_priority: str = "Medium",
            **kwargs) -> InvestigationResult:
        """
        Main investigation pipeline
        """
        result = InvestigationResult(case_id=case_id)
        
        # 1. Text Analysis (NER)
        result.entities = self._analyze_text(modus, suspect_name, location)
        
        # 2. File Processing
        file_results = self._process_files(files)
        result.ocr_text = file_results.get('ocr_text', '')
        result.face_result = file_results.get('face_result', {})
        result.voice_result = file_results.get('voice_result', {})
        
        # 3. Watchlist Lookup
        result.watchlist = self._lookup_watchlist(suspect_name, result.entities)
        
        # 4. MO Fingerprinting (V54 - UNKNOWN Neutral)
        result.mo_links = self._match_mo(modus, location)
        
        # 5. Unidentified Offender Leads
        if unidentified_flag or not suspect_name:
            result.unidentified_leads = self._search_unidentified(modus, physical_desc, location)
        
        # 6. Risk Calculation
        risk_result = self._calculate_risk(
            entities=result.entities,
            face_result=result.face_result,
            voice_result=result.voice_result,
            ocr_text=result.ocr_text,
            watchlist=result.watchlist,
            case_priority=case_priority
        )
        result.deception_score = risk_result.get('deception', 0)
        result.risk_score = risk_result.get('risk', 0)
        result.credibility_score = risk_result.get('credibility', 0)
        
        # 7. Reasoning Engine
        result.reasoning = self._build_reasoning(
            case_id=case_id,
            modus=modus,
            location=location,
            suspect_name=suspect_name,
            entities=result.entities,
            mo_links=result.mo_links,
            watchlist=result.watchlist,
            unidentified_leads=result.unidentified_leads
        )
        
        # 8. Threat Assessment
        result.threat = self._assess_threat(
            deception=result.deception_score,
            risk=result.risk_score,
            entities=result.entities,
            watchlist=result.watchlist,
            case_priority=case_priority
        )
        
        # 9. Actions
        result.actions = self._generate_actions(
            threat=result.threat,
            risk=result.risk_score,
            deception=result.deception_score,
            entities=result.entities,
            watchlist=result.watchlist
        )
        
        # 10. Report Generation
        result.report_text = self._generate_report_text(result)
        result.report_data = result.to_dict()
        
        return result
    
    def _analyze_text(self, modus: str, suspect_name: str, location: str) -> Dict:
        """Text analysis (NER)"""
        if not self.services_ready:
            return {}
        try:
            text = f"{modus or ''} {suspect_name or ''} {location or ''}".strip()
            if text:
                return self.ner.extract(text)
        except Exception as e:
            print(f"NER error: {e}")
        return {}
    
    def _process_files(self, files: Dict) -> Dict:
        """Process uploaded files"""
        result = {
            'ocr_text': '',
            'face_result': {},
            'voice_result': {}
        }
        
        if not self.services_ready:
            return result
        
        # OCR for documents
        if files.get('documents'):
            for doc in files['documents']:
                try:
                    from upload.ocr_processor import OCRProcessor
                    ocr_result = OCRProcessor.process_image(doc.get('path', ''))
                    if ocr_result:
                        result['ocr_text'] += ocr_result + '\n'
                except Exception as e:
                    print(f"OCR error: {e}")
        
        # Face analysis for images
        if files.get('images'):
            for img in files['images']:
                try:
                    face_result = self.face.analyze(img.get('path'))
                    if face_result:
                        result['face_result'] = face_result
                except Exception as e:
                    print(f"Face analysis error: {e}")
        
        # Voice analysis
        if files.get('audio'):
            for audio in files['audio']:
                try:
                    voice_result = self.voice.analyse(audio.get('path'))
                    if voice_result:
                        result['voice_result'] = voice_result
                except Exception as e:
                    print(f"Voice analysis error: {e}")
        
        return result
    
    def _lookup_watchlist(self, suspect_name: str, entities: Dict) -> Dict:
        """Watchlist lookup"""
        if not suspect_name:
            return {'status': 'NO_NAME', 'criminal_history': 'No suspect name provided'}
        
        if not self.services_ready:
            return {'status': 'SERVICE_UNAVAILABLE'}
        
        try:
            # Try to import the existing function
            from gradio_app import _lookup_suspect_background
            return _lookup_suspect_background(suspect_name, entities)
        except Exception as e:
            print(f"Watchlist lookup error: {e}")
            return {'status': 'ERROR', 'error': str(e)}
    
    def _match_mo(self, modus: str, location: str) -> Dict:
        """MO Fingerprinting (V54 - UNKNOWN Neutral)"""
        if not modus:
            return {'note': 'No Modus Operandi provided'}
        
        try:
            from gradio_app import mo_eng
            if mo_eng and mo_eng.ready:
                return mo_eng.find_linked_cases(None, modus, location)
        except Exception as e:
            print(f"MO matching error: {e}")
        
        return {'note': 'MO Fingerprinting unavailable'}
    
    def _search_unidentified(self, modus: str, physical_desc: str, location: str) -> Dict:
        """Unidentified offender search"""
        if not modus and not physical_desc:
            return {'note': 'No description provided'}
        
        try:
            from gradio_app import _lookup_unidentified_offender
            return _lookup_unidentified_offender(modus, physical_desc, location)
        except Exception as e:
            print(f"Unidentified search error: {e}")
            return {'note': f'Search failed: {e}'}
    
    def _calculate_risk(self, **kwargs) -> Dict:
        """Risk calculation"""
        # Simple risk calculation
        entities = kwargs.get('entities', {})
        watchlist = kwargs.get('watchlist', {})
        case_priority = kwargs.get('case_priority', 'Medium')
        
        # Base score from entities
        crime_count = len(entities.get('CRIME', []))
        weapon_count = len(entities.get('WEAPON', []))
        threat_count = len(entities.get('THREAT', []))
        
        deception = min(95, crime_count * 10 + weapon_count * 12 + threat_count * 8 + 20)
        risk = min(95, deception * 0.6 + 20)
        credibility = max(5, 100 - deception)
        
        # Priority boost
        if case_priority in ('High', 'Critical'):
            risk = min(95, risk + 15)
        elif case_priority == 'Medium':
            risk = min(95, risk + 5)
        
        return {
            'deception': round(deception, 1),
            'risk': round(risk, 1),
            'credibility': round(credibility, 1)
        }
    
    def _build_reasoning(self, **kwargs) -> Dict:
        """Build reasoning engine output"""
        return {
            'gaps': [],
            'contradictions': [],
            'hypotheses': [],
            'draft_report': 'Investigation report draft...'
        }
    
    def _assess_threat(self, **kwargs) -> Dict:
        """Threat assessment"""
        deception = kwargs.get('deception', 0)
        risk = kwargs.get('risk', 0)
        
        if risk > 75:
            physical = "HIGH"
            public_safety = "HIGH"
        elif risk > 50:
            physical = "Medium"
            public_safety = "Medium"
        else:
            physical = "Low"
            public_safety = "Low"
        
        return {
            'physical': physical,
            'financial': 'Medium',
            'cyber': 'Low',
            'public_safety': public_safety,
            'escalation_prob': min(95, risk * 0.8 + deception * 0.2)
        }
    
    def _generate_actions(self, **kwargs) -> List:
        """Generate actionable intelligence"""
        risk = kwargs.get('risk', 0)
        actions = []
        
        if risk > 75:
            actions.append("IMMEDIATE: Risk score exceeds 75%. Recommend emergency surveillance warrant.")
        elif risk > 50:
            actions.append("PRIORITY: Elevated risk detected. Expand background investigation immediately.")
        else:
            actions.append("ROUTINE: No immediate threat indicators. Continue standard monitoring.")
        
        actions.append("RE-EVALUATE: Schedule evidence review in 30 days or immediately upon new evidence submission.")
        
        return actions
    
    def _generate_report_text(self, result: InvestigationResult) -> str:
        """Generate plain text report"""
        lines = [
            "=" * 70,
            f"  INVESTIGATION INTELLIGENCE REPORT",
            f"  Case ID: {result.case_id}",
            f"  Timestamp: {result.timestamp}",
            "-" * 70,
            f"  Deception Score: {result.deception_score}%",
            f"  Risk Score: {result.risk_score}%",
            f"  Credibility: {result.credibility_score}%",
            "-" * 70,
            "  EVIDENCE SUMMARY",
        ]
        
        if result.entities:
            for entity_type, values in result.entities.items():
                if values:
                    lines.append(f"    {entity_type}: {', '.join(values[:5])}")
        
        if result.ocr_text:
            lines.append(f"    OCR Text: {result.ocr_text[:100]}...")
        
        lines.extend([
            "-" * 70,
            "  WATCHLIST STATUS",
            f"    {result.watchlist.get('criminal_history', 'No record found')}",
            "-" * 70,
            "  ACTIONABLE INTELLIGENCE",
        ])
        
        for i, action in enumerate(result.actions, 1):
            lines.append(f"    {i}. {action}")
        
        lines.extend([
            "-" * 70,
            "  DISCLAIMER: AI-generated report. Must be reviewed by a",
            "  qualified forensic investigator before any official use.",
            "=" * 70,
        ])
        
        return "\n".join(lines)
