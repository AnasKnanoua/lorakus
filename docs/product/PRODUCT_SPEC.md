# JARVIS — PRODUCT SPECIFICATION

Version: 1.0
Project type: Personal AI Platform
Status: Architecture and research phase

---

# 1. PROJECT VISION

JARVIS is a modular personal AI assistant platform.

The objective is to build a reliable, intelligent and extensible assistant that can understand a user's needs, manage personal information, interact with external services and proactively provide useful recommendations.

The first instance will be developed for personal use.

The long-term architecture should make it possible to offer customized assistants to other individuals.

The product must be maintainable for several years.

The goal is not to create another generic chatbot, but a personal intelligence and productivity platform.

## Core principles

- Modular by design.
- Secure by default.
- AI-assisted, not AI-dependent.
- Privacy-first.
- Extensible.
- Maintainable.
- Cost-efficient.
- Professional UX.
- Automation with human oversight.

---

# 2. USER PROFILE AND DEVELOPMENT ENVIRONMENT

The initial user is an engineering student interested in:
- Computer science.
- Cybersecurity.
- DevOps and DevSecOps.
- Machine Learning.
- Artificial Intelligence.
- Entrepreneurship.
- Personal productivity.

The user has some programming experience and is currently studying Machine Learning.

## Available hardware

- Samsung Galaxy S26 Ultra.
- Dell Inspiron running Ubuntu.
- Oracle Cloud Always Free ARM VPS.
- Possible access to a Mac computer.

## Available resources

- Claude Pro subscription for development assistance.
- Potential Gemini student benefits and Gemini API free tier.
- NVIDIA Developer Program / NVIDIA NIM.
- GitHub Student Developer Pack.
- Oracle Cloud Free Tier.
- Potential local AI capabilities on Android and other devices.

Important: verify actual access, quotas, commercial restrictions and current pricing. Never assume that a student offer includes API credits or unlimited usage.

The application must not depend on the continued availability of a specific free offer.

---

# 3. PRODUCT ARCHITECTURE

The target architecture should initially be a Modular Monolith.

Avoid premature microservices.

The platform should be organized around:

## A. Core Platform

Responsible for:
- Users.
- Authentication.
- Authorization.
- Conversations.
- Persistent memory.
- Module registry.
- Configuration.
- Events.
- Notifications.
- Scheduling.
- Tool execution.
- Audit logs.
- AI provider abstraction.

## B. AI Engine

Responsible for:
- Natural language understanding.
- Model selection.
- Tool calling.
- Context management.
- Reasoning.
- Summarization.
- Retrieval.
- Structured outputs.

Must support multiple providers.

## C. Intelligence Layer

Three distinct approaches:

1. Deterministic algorithms.
2. Machine Learning.
3. LLMs.

Choose the simplest reliable approach for each task.

## D. Module System

Modules must be independent and discoverable.

Each module should declare:
- Identifier.
- Name.
- Version.
- Dependencies.
- Permissions.
- Configuration schema.
- Events consumed.
- Events produced.
- Tools exposed.
- Scheduled jobs.
- API routes, if applicable.
- Health checks.

A module must be installable, configurable, disableable and updateable without breaking the Core.

Consider version compatibility and dependency conflicts.

## E. External Connectors

All external integrations must be isolated behind adapters.

Examples:
- Gemini.
- NVIDIA.
- Chess.com.
- Banking data imports.
- RSS.
- GitHub.
- Instagram.
- TikTok.
- Calendar services.

Do not let individual modules implement their own unrelated authentication or HTTP infrastructure.

---

# 4. INTELLIGENCE AND MEMORY

JARVIS should maintain different types of memory.

## Personal memory
Preferences, habits and user-defined information.

## Episodic memory
What happened, when it happened and what actions were taken.

## Semantic memory
Knowledge extracted from documents, resources and conversations.

## Operational memory
Tasks, projects, deadlines, budgets and current states.

Memory must be:
- Structured where possible.
- Searchable.
- Editable.
- Versioned when necessary.
- Deletable.
- Traceable to its source.

The system must distinguish verified facts from assumptions and AI-generated suggestions.

Do not automatically transform every conversation into permanent memory.

---

# 5. PERSONAL USE CASES

The following modules represent the initial personal use cases.

They must be implemented as reusable modules, not hardcoded personal features.

## MODULE 1 — PERSONAL ASSISTANT

Capabilities:
- Natural language conversation.
- Contextual answers.
- Memory retrieval.
- Tool execution.
- Voice interaction.
- Conversation history.
- Personalized recommendations.

Example:

"Jarvis, what should I do today?"

The assistant retrieves relevant tasks, deadlines, calendar events and personal priorities, then generates a structured briefing.

## MODULE 2 — ACADEMIC MANAGER

Capabilities:
- Courses.
- Assignments.
- Exams.
- Deadlines.
- Revision sessions.
- Estimated workload.
- Progress tracking.
- Smart reminders.

Intelligence:
- Deterministic deadline management.
- Historical estimation of task duration.
- Personalized revision planning.
- Detection of overdue work.
- Recommendation of realistic daily objectives.

The system should learn from actual completion times instead of assuming every task takes the same amount of time.

## MODULE 3 — NOTIFICATION INTELLIGENCE

This is a central component of the product.

Notifications must consider:
- Deadlines.
- Tasks.
- User activity.
- Priorities.
- Available time.
- Previous notifications.
- User response patterns.
- Configured quiet hours.

Three categories:

1. Scheduled notifications.
2. Contextual notifications.
3. Proactive recommendations.

Prevent notification spam through:
- Priority scoring.
- Deduplication.
- Rate limiting.
- Notification grouping.
- Quiet hours.
- User preferences.

The engine should be independent of the AI provider.

## MODULE 4 — CHESS ACTIVITY MONITOR

The initial user plays Chess.com exclusively on a PC.

Preferred architecture:

### Local PC tracker

A lightweight local component detects:
- Chess.com browser tab activity.
- Active window or browser usage.
- Session start and end.
- Actual active time where measurable.
- Idle periods.

Do not count an open but inactive browser tab as active playing time.

The tracker should send minimal usage events to the central backend.

### Chess.com PubAPI

Use the official public API to retrieve:
- Completed games.
- Game timestamps.
- Results.
- Time controls.
- Ratings.
- Historical activity.

Important technical limitation:

Chess.com PubAPI endpoints refresh at most once every 12 hours according to its documentation.

Therefore, the PubAPI must not be the sole source of real-time activity detection.

Use it for historical game data and reconciliation.

### Intelligent features

- Daily playing time.
- Weekly playing time.
- Number of games.
- Time-control distribution.
- Correlation between playing habits and academic deadlines.
- Personalized warnings.
- Detection of excessive playing sessions.

Do not automatically classify chess as bad. It is a leisure activity.

The objective is to help the user maintain balance.

## MODULE 5 — FINANCE MANAGER

Initial approach:

Manual upload of CSV, OFX or other supported bank-export files.

The system should:
- Parse transactions locally or within the protected backend.
- Identify transaction dates and amounts.
- Categorize expenses.
- Detect recurring payments.
- Detect duplicates.
- Calculate budgets.
- Generate spending reports.
- Estimate month-end spending.
- Detect unusual transactions.

Future possibility:
Official Open Banking integrations.

Security requirements:
- Never request banking passwords.
- Never store banking credentials.
- Never send raw transaction files to external LLM providers.
- Restrict access to financial information.
- Protect uploaded documents.
- Provide deletion and export functionality.

Use deterministic financial calculations.

ML may be used for categorization, anomaly detection and forecasts, with confidence scores and user corrections.

## MODULE 6 — KNOWLEDGE COLLECTOR

The user frequently saves resources on:
- TikTok.
- Instagram.
- GitHub.
- Websites.
- Articles.
- Conversations.
- Personal notes.

Initial approach:

A universal inbox where the user can share:
- TikTok links.
- Instagram Reels.
- GitHub repositories.
- Articles.
- Documents.
- Images.
- Voice messages.
- Text ideas.

The assistant should:
1. Receive the resource.
2. Identify its type.
3. Extract accessible information.
4. Summarize it.
5. Classify it.
6. Identify possible projects or opportunities.
7. Store it with its original source.
8. Make it searchable.

Possible categories:
- Business ideas.
- Technical projects.
- Cybersecurity.
- Learning.
- Tools.
- Research.
- Inspiration.
- To review.

Do not assume every external link can be fully accessed.

## MODULE 7 — NEWS INTELLIGENCE

Use RSS and official sources whenever possible.

Potential sources:
- The Hacker News.
- BleepingComputer.
- Krebs on Security.
- SANS Internet Storm Center.
- Google Project Zero.
- Synacktiv.
- Other relevant technology publications.

Capabilities:
- Scheduled collection.
- Deduplication.
- Relevance scoring.
- Topic classification.
- Summarization.
- Source attribution.
- Personalized daily briefings.

The system should prioritize information related to the user's current projects and studies.

## MODULE 8 — PROJECT MANAGER

Capabilities:
- Capture ideas.
- Convert ideas into projects.
- Break projects into tasks.
- Set priorities.
- Track progress.
- Identify inactive projects.
- Detect dependencies.
- Generate weekly plans.
- Link saved resources to projects.

The assistant should help users finish projects instead of constantly suggesting new ones.

---

# 6. FRONTEND AND USER EXPERIENCE

The application should eventually have a modern web interface and an Android application.

The initial frontend technology must be selected after comparing suitable options.

The visual direction:

## Conversation interface

Inspired by ChatGPT and Gemini.

Requirements:
- Minimalist.
- Beautiful typography.
- Streaming responses.
- Conversation history.
- Voice input.
- Voice output.
- File uploads.
- Source citations.
- Tool execution indicators.
- Responsive layout.

## Dashboard

A professional productivity dashboard.

Potential sections:
- Today.
- Tasks.
- Academic calendar.
- Finances.
- Projects.
- Activity.
- News.
- Notifications.
- Memory.

## Design principles

- Consistent design system.
- Elegant spacing.
- Clear hierarchy.
- Smooth transitions.
- Light and dark themes.
- Responsive.
- Accessible.
- No unnecessary visual clutter.

The interface should feel like a finished commercial product.

---

# 7. DEVOPS AND DEVSECOPS

Security and maintenance are core product requirements.

Expected practices:

## Code quality
- Automated tests.
- Static analysis.
- Type checking.
- Linting.
- Dependency scanning.
- Code reviews.

## CI/CD
- GitHub Actions.
- Automated test pipeline.
- Security checks.
- Reproducible builds.
- Controlled deployments.
- Rollbacks.

## Security tools to evaluate
- Semgrep.
- Bandit.
- CodeQL.
- Gitleaks.
- pip-audit.
- Dependabot.
- Trivy.
- OWASP ZAP.
- Nuclei.

## Red Team

Consider an isolated security-testing agent.

It should test:
- API security.
- Authentication.
- Authorization.
- Input validation.
- Prompt injection.
- Tool permissions.
- Data isolation.
- Information leakage.

It must operate only against controlled test environments.

Its results must be reproducible and converted into actionable security reports.

Never grant it unrestricted production access.

## Infrastructure

Initial hosting:
Oracle Cloud ARM Free Tier.

Expected capabilities:
- Docker Compose.
- HTTPS.
- Reverse proxy.
- Firewall.
- Secrets management.
- Monitoring.
- Structured logging.
- Automated backups.
- Recovery procedures.

Design a migration path to paid infrastructure if the product acquires users.

---

# 8. MULTI-USER AND COMMERCIAL FUTURE

The architecture must anticipate the possibility of serving multiple users.

Even if the first deployment is personal, avoid assumptions that prevent multi-tenancy.

Consider:
- User isolation.
- Tenant-specific configurations.
- Module permissions.
- Separate memories.
- Individual API credentials.
- Usage limits.
- Subscription capabilities.
- Module entitlements.
- Audit logs.

Do not build a complex billing system prematurely.

However, the Core must not assume that there is only one user.

---

# 9. LONG-TERM MAINTENANCE

The project must remain maintainable over several years.

Required documentation:
- README.
- Architecture documentation.
- Module specifications.
- API documentation.
- Deployment guide.
- Security documentation.
- Database schema.
- ADRs.
- Changelog.
- Troubleshooting guide.

Maintain:
- Semantic versioning.
- Database migrations.
- Dependency updates.
- Backward compatibility.
- Automated regression tests.
- Monitoring.
- Backup verification.
- Incident recovery procedures.

Never make a breaking change without identifying its impact on existing modules.

---

# 10. INITIAL PRODUCT ROADMAP

The exact roadmap must be decided after the architecture study.

The expected direction is:

Phase 0: Research and architecture.

Phase 1: Core platform and infrastructure.

Phase 2: Authentication, conversations and AI abstraction.

Phase 3: Memory and task management.

Phase 4: Academic manager and notification engine.

Phase 5: Initial web frontend and dashboard.

Phase 6: Chess activity tracking.

Phase 7: Finance manager.

Phase 8: Knowledge collector.

Phase 9: News intelligence.

Phase 10: Voice interaction and Android.

Phase 11: ML personalization.

Phase 12: Red Team automation and production hardening.

This order is indicative, not mandatory.

Prioritize a coherent, usable product rather than implementing every module independently.

---

# 11. PRODUCT SUCCESS CRITERIA

JARVIS must not become an application that is entertaining for one day and then abandoned.

Every module must solve a recurring problem.

Measure:
- Daily and weekly usage.
- Tasks completed.
- Reminder usefulness.
- False notifications.
- Recommendation acceptance.
- Forecast accuracy.
- User corrections.
- System reliability.
- API costs.
- Maintenance effort.

The assistant should become more useful through real usage and feedback.

The ultimate goal is to create a platform that users trust and naturally integrate into their daily lives.
