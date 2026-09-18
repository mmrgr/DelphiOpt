# Adaptive scheduling

All policies implement `schedule(state) -> SchedulingDecision`:

* `fixed` uses the strong model and constant token/tool budgets.
* `difficulty` routes high-complexity contexts to the strong model.
* `adaptive_voi` scores `disagreement * reliability * candidate_gain * remaining_budget / estimated_cost` and records the score and reason in the trace.

The scheduler controls expert order, model alias, token budget, tool budget, and cost estimate. Runtime invocation follows `decision.expert_id` directly, resolves `cheap`/`strong` onto each expert's configured pool, and passes `max_tokens` to the provider. Completed experts are excluded within a round.

The global `BudgetManager` accounts for actual provider tokens/cost/latency plus implementation, compile, lint, test, warmup, and benchmark calls. `StoppingPolicy` compares marginal gain and utility per dollar; `ConvergencePolicy` combines disagreement, ranking stability, stagnant rounds, remaining budget, and maximum rounds.
