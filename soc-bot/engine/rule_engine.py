"""
Rule engine for severity classification and action determination.
"""
import logging
import yaml
from pathlib import Path

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / 'config.yaml'

# Default severity map (used as fallback if config not found)
_DEFAULT_SEVERITY_RANGES = [
    (range(12, 16), 'CRITICAL'),
    (range(8, 12),  'HIGH'),
    (range(6, 8),   'MEDIUM'),
    (range(4, 6),   'LOW'),
    (range(0, 4),   'INFO'),
]

_DEFAULT_ACTIONS = {
    'CRITICAL': ['ai_analyze', 'create_thehive', 'notify_line', 'save_dashboard'],
    'HIGH':     ['ai_analyze', 'create_thehive', 'notify_line', 'save_dashboard'],
    'MEDIUM':   ['ai_analyze', 'notify_line', 'save_dashboard'],
    'LOW':      ['save_dashboard'],
    'INFO':     ['save_dashboard'],
}


def load_config() -> dict:
    """Load configuration from config.yaml."""
    try:
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.warning(f"config.yaml not found at {_CONFIG_PATH}, using defaults")
        return {}
    except Exception as e:
        logger.error(f"Error loading config.yaml: {e}")
        return {}


def classify_severity(rule_level: int, config: dict | None = None) -> str:
    """
    Classify rule_level into a severity string.
    Returns: CRITICAL, HIGH, MEDIUM, LOW, or INFO
    """
    if config is None:
        config = load_config()

    thresholds = config.get('severity_thresholds', {})

    if thresholds:
        # Use config-based thresholds
        order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
        for severity in order:
            limits = thresholds.get(severity, {})
            min_lv = limits.get('min_level', 0)
            max_lv = limits.get('max_level', 0)
            if min_lv <= rule_level <= max_lv:
                return severity
        return 'INFO'
    else:
        # Fall back to default ranges
        for level_range, severity in _DEFAULT_SEVERITY_RANGES:
            if rule_level in level_range:
                return severity
        return 'INFO'


def get_actions(severity: str, config: dict | None = None) -> list[str]:
    """
    Return list of actions to perform for the given severity.
    """
    if config is None:
        config = load_config()

    actions = config.get('actions', _DEFAULT_ACTIONS)
    return actions.get(severity, ['save_dashboard'])


def should_process(rule_level: int, config: dict | None = None) -> bool:
    """
    Check if an alert at this rule_level should be processed at all.
    """
    if config is None:
        config = load_config()

    min_level = config.get('wazuh', {}).get('min_rule_level', 3)
    return rule_level >= min_level
