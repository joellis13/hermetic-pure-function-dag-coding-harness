# ADR 0003: Stateless HITL & Versioned Plan Refinement

## Context
Standard conversational LLM interfaces accumulate a raw chat transcript. Over many turns, this can cause the model to lose focus or hallucinate based on outdated instructions in the chat history.

## Decision
* **Functional Transition Model**: Every interactive turn is a pure state transition: `Plan_{n+1} = PlanningNode(IssueContext, Plan_n, UserFeedback_n)`.
* **Bounded Context**: The LLM sees only the immutable `IssueContext`, the current validated `plan.json`, an optional harness-controlled `feedback_history`, and the latest `UserFeedback`.
* **Versioned Artifacts**: Each refinement round generates a versioned artifact (`plan_v1.json`, etc.) persisted in SQLite, enabling instant rollback (`--revert-to 1`).
* **Semantic Diffs**: Instead of a conversational chat log, the human sees a computed semantic diff between the previous and new plan.
