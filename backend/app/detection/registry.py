from app.detection.base import BaseDetector
from app.detection.detectors.anomaly import AnomalyDetector
from app.detection.detectors.custom_rules import CustomRulesDetector
from app.detection.detectors.data_exfil import DataExfiltrationDetector
from app.detection.detectors.jailbreak import JailbreakDetector
from app.detection.detectors.privilege_esc import PrivilegeEscalationDetector
from app.detection.detectors.prompt_injection import PromptInjectionDetector
from app.detection.detectors.tool_misuse import ToolMisuseDetector

# All registered detectors — order matters for the pipeline
DETECTORS: list[BaseDetector] = [
    PromptInjectionDetector(),
    JailbreakDetector(),
    ToolMisuseDetector(),
    DataExfiltrationDetector(),
    PrivilegeEscalationDetector(),
    CustomRulesDetector(),
    AnomalyDetector(),
]

DETECTOR_MAP: dict[str, BaseDetector] = {d.name: d for d in DETECTORS}


def get_detector(name: str) -> BaseDetector | None:
    return DETECTOR_MAP.get(name)


def get_all_detectors() -> list[BaseDetector]:
    return DETECTORS
