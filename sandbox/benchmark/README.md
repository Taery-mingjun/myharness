# Benchmark Tasks (READ-ONLY)

> **This directory is mounted read-only in the sandbox container.**
> Sandbox code CANNOT modify these files. They serve as the external
> ground truth for evaluating skill mutations.
>
> **No code in this repository may write to this directory programmatically.**
> Changes to benchmarks are human-only, via git commits.

## Purpose

These 5 tasks are the fixed external standard. A skill mutation in the
sandbox must pass all 5 to be considered for human review. The sandbox
does NOT auto-merge — results are written to `sandbox/results/` and a
human decides whether to promote the mutation.

## Tasks

| ID | File | Description | Pass Criteria |
|----|------|-------------|---------------|
| T1 | `t1_arithmetic.json` | Basic arithmetic: "1+1=?" | Response contains "2" |
| T2 | `t2_greeting.json` | Greeting in Chinese | Response is in Chinese, contains a greeting |
| T3 | `t3_skill_query.json` | List available skills | Response lists ≥0 skills (empty list is valid) |
| T4 | `t4_identity_read.json` | Read agent identity | Response contains identity fields (name, mission) |
| T5 | `t5_plan_simple.json` | Plan a simple task | Response is valid JSON with goal + steps array |

## Evaluation

Each task is scored 0 (fail) or 1 (pass). A mutation must score 5/5
to be promoted to human review. Scores <5/5 are recorded but never
merged automatically.
