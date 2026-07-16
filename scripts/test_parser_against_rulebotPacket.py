import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from offense_parser import parse_offense_template

packet_path = PROJECT_ROOT / "tools" / "windows" / "output" / "RulebotPacket-462687.txt"

text = packet_path.read_text(encoding="utf-8")
parsed = parse_offense_template(text)

print("evidence_mode:", parsed["evidence_mode"])
print("top_qids type:", type(parsed["top_qids"]))
print("combined_distribution type:", type(parsed["combined_distribution"]))
print("representative_events type:", type(parsed["representative_events"]))
print("resolved_rule_bindings type:", type(parsed["resolved_rule_bindings"]))
print("qradar_rule_api_metadata type:", type(parsed["qradar_rule_api_metadata"]))
print("offense_rules_raw type:", type(parsed["offense_rules_raw"]))
print("resolved_rule_bindings:", parsed["resolved_rule_bindings"])