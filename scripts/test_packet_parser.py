from offense_parser import parse_offense_template

sample_packet = """
offense_id: 462687
client_id: default
evidence_mode: INOFFENSE_ONLY
evidence_summary:
  evidence_mode: INOFFENSE_ONLY
  collection_mode: FAST
  qradar_event_count: 330
  primary_source_ip: 172.21.23.247
  primary_destination_ip: 208.67.222.222
  primary_qid: 53512404
rule_id: 100102
top_qids: [{"qid":53512404,"event_count":293},{"qid":67500131,"event_count":37}]
combined_distribution: [{"sourceip":"172.21.23.247","destinationip":"208.67.222.222","qid":53512404,"event_count":293}]
representative_events: [{"starttime":1784028494073,"qid":53512404}]
why_false_positive: test
desired_outcome: test
analyst_notes: test
"""

parsed = parse_offense_template(sample_packet)

print("evidence_mode:", parsed["evidence_mode"])
print("evidence_summary:", parsed["evidence_summary"])
print("top_qids type:", type(parsed["top_qids"]))
print("top_qids:", parsed["top_qids"])
print("combined_distribution type:", type(parsed["combined_distribution"]))
print("representative_events type:", type(parsed["representative_events"]))