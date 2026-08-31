# CRM V3 Launch Roadmap

This document outlines the roadmap for restoring performance, stabilizing queue operations, and launching the autonomous learning loop for CRM V3.

## Project Stages

### R0: UI RESTORE / FREEZE
- **Status**: `ACCEPTED`
- **Details**: Analytics UI has been restored to the accepted S13 production baseline commit `f5285b6dade45a21df5b055fb7048835090de24a` and UI development is frozen to prevent regressions.

### R1: RUNTIME + GIT AUDIT
- **Status**: `AGENT_PASS`
- **Details**: Authoritative runtime state audit, verification of uncommitted changes, git state synchronization, and mapping of pipeline file authorities completed.

### R2: 223-FZ DATE RECONCILIATION
- **Status**: `TODO`
- **Details**: Reconcile date inconsistencies where contract execution dates are incorrectly mapped as tender deadlines.

### R3: GOLD/SILVER HUNTER QUEUE
- **Status**: `TODO`
- **Details**: Implement priority queueing logic utilizing Qwen blind predictions to process high-value opportunities first.

### R4: EXHAUSTIVE FACTUAL RESEARCH
- **Status**: `TODO`
- **Details**: Verify that the document parser, downloader, and phrase matcher process the incoming queue automatically with high quality.

### R5: STRUCTURED PRODUCT NORMALIZATION
- **Status**: `TODO`
- **Details**: Normalize unstructured product findings into structured attributes according to the commercial taxonomy.

### R6: LEARNING TARGET COMPLETION
- **Status**: `TODO`
- **Details**: Implement all required target tasks (e.g. document relevance, categories, commercial medals) in the learning example builder.

### R7: FINE-TUNE / HOLDOUT / PROMOTION
- **Status**: `TODO`
- **Details**: Create model fine-tuning loops and implement strict evaluation gating using holdout datasets before promotion.

### R8: HOURLY CRM OPERATING METRICS
- **Status**: `TODO`
- **Details**: Develop dashboard widgets/scripts tracking real-time queue states and processing latencies.

### R9: CRM FILTERS + READ-ONLY RESEARCH RESULT
- **Status**: `TODO`
- **Details**: Safely re-introduce read-only filters for research status and structured findings.

### R10: 24H PRODUCTION SLA RUN
- **Status**: `TODO`
- **Details**: Run the complete automated pipeline for a full 24-hour cycle under production load with zero failures.
