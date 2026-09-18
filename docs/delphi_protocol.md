# Delphi protocol

`DelphiProtocol` implements independent elicitation, anonymous aggregation, controlled feedback, revision, and convergence analysis. Round-one prompts contain project evidence only. Later prompts contain candidate summaries and benchmark evidence, not provider or model identity.

The candidate score is configurable in code and combines support, expected gain, confidence, novelty, reputation, implementation cost, and correctness risk. The minority bonus is intentionally evidence-seeking rather than a majority vote: high-upside, plausible minority transformations are still benchmarked.

Debate mode is available for comparison and deliberately exposes peer summaries. Single mode uses one expert. These modes share the same implementation, gate, benchmark, and trace path so ablations compare mechanisms rather than unrelated programs.

